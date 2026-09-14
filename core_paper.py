"""Máquina de estados de Paper Trading.

    vigilancia -> parcial_entrada -> abierta -> parcial_salida -> cerrada
         \\-> descartada (solo sin acciones vivas: con posición hay que cerrarla)

El estado NO se guarda como verdad: se deriva de las ejecuciones de nivel
(`paper_ejecuciones`) y se copia a `paper_planes.estado` solo para que el
cron de alertas y `plan_activo_para` puedan filtrar sin recalcular.

Tamaño de cada nivel: el plan lleva un capital nominal (PAPER_CAPITAL_DEFECTO
salvo que se cambie al ejecutar el primer nivel) y las entradas lo reparten
con los pesos DCA; cada salida vende su peso sobre el total COMPRADO, la
última salida pendiente (o el STOP) liquida lo que quede. Las ejecuciones se
registran en la divisa del plan; el rendimiento simulado se calcula con
core_cartera.libro sobre esas ejecuciones (mismo motor que la cartera real).
"""

from __future__ import annotations

from datetime import date

from config_settings import (
    CARTERA_TOLERANCIA_ACCIONES,
    PAPER_CAPITAL_DEFECTO,
    PAPER_NIVEL_STOP,
    PAPER_NIVELES_ENTRADA,
    PAPER_NIVELES_SALIDA,
)
from core_cartera import libro
from core_ponderar import es_dato

NIVELES_VENTA = PAPER_NIVELES_SALIDA + (PAPER_NIVEL_STOP,)


def _por_nivel(plan: dict) -> dict[str, dict]:
    d = {e["nivel"]: e for e in (plan.get("entradas") or [])}
    d.update({s["nivel"]: s for s in (plan.get("salidas") or [])})
    if es_dato(plan.get("stop")):
        d[PAPER_NIVEL_STOP] = {"nivel": PAPER_NIVEL_STOP, "precio": plan["stop"], "peso": 1.0}
    return d


def precio_nivel(plan: dict, nivel: str) -> float | None:
    n = _por_nivel(plan).get(nivel)
    return float(n["precio"]) if n and es_dato(n.get("precio")) else None


def ejecutadas(ejecuciones: list[dict]) -> set[str]:
    return {e["nivel"] for e in ejecuciones}


def acciones_vivas(ejecuciones: list[dict]) -> float:
    compradas = sum(float(e["acciones"]) for e in ejecuciones if e["nivel"] in PAPER_NIVELES_ENTRADA)
    vendidas = sum(float(e["acciones"]) for e in ejecuciones if e["nivel"] in NIVELES_VENTA)
    vivas = compradas - vendidas
    return 0.0 if vivas <= CARTERA_TOLERANCIA_ACCIONES else vivas


def estado(plan: dict, ejecuciones: list[dict]) -> str:
    """Estado derivado. 'descartada' es manual y se respeta si está guardado."""
    if plan.get("estado") == "descartada":
        return "descartada"
    hechas = ejecutadas(ejecuciones)
    entradas = hechas & set(PAPER_NIVELES_ENTRADA)
    salidas = hechas & set(NIVELES_VENTA)
    if not entradas:
        return "vigilancia"
    if not salidas:
        return "abierta" if entradas == set(PAPER_NIVELES_ENTRADA) else "parcial_entrada"
    return "parcial_salida" if acciones_vivas(ejecuciones) > 0 else "cerrada"


def niveles_pendientes(plan: dict, ejecuciones: list[dict]) -> list[str]:
    """Qué se puede ejecutar ahora, en orden de la escalera. Tras un STOP o
    con la posición liquidada no queda nada; sin acciones vivas no hay
    salidas ni stop."""
    if estado(plan, ejecuciones) in ("cerrada", "descartada"):
        return []
    hechas = ejecutadas(ejecuciones)
    if PAPER_NIVEL_STOP in hechas:
        return []
    niveles = _por_nivel(plan)
    out = [n for n in PAPER_NIVELES_ENTRADA if n in niveles and n not in hechas]
    if acciones_vivas(ejecuciones) > 0:
        out += [n for n in PAPER_NIVELES_SALIDA if n in niveles and n not in hechas]
        if PAPER_NIVEL_STOP in niveles:
            out.append(PAPER_NIVEL_STOP)
    return out


def puede_descartar(plan: dict, ejecuciones: list[dict]) -> bool:
    return estado(plan, ejecuciones) == "vigilancia"


def acciones_para(plan: dict, nivel: str, precio: float, ejecuciones: list[dict], fx: float | None = 1.0) -> float | None:
    """Tamaño de la ejecución. Entradas: capital * peso / precio, con el
    capital (EUR) pasado a la divisa del plan mediante `fx` (EUR por unidad
    de esa divisa; None si no es convertible: entonces el capital se toma
    como nominal en la divisa del plan). Salidas: peso sobre el total
    comprado, recortado a lo vivo; la última salida pendiente y el STOP
    liquidan todo."""
    if not es_dato(precio) or precio <= 0:
        return None
    n = _por_nivel(plan).get(nivel)
    if n is None:
        return None
    if nivel in PAPER_NIVELES_ENTRADA:
        capital = float(plan.get("capital_eur") or PAPER_CAPITAL_DEFECTO)
        if es_dato(fx) and fx:
            capital = capital / float(fx)
        return round(capital * float(n.get("peso") or 0) / precio, 4)
    vivas = acciones_vivas(ejecuciones)
    if vivas <= 0:
        return None
    pendientes = [s for s in niveles_pendientes(plan, ejecuciones) if s in PAPER_NIVELES_SALIDA]
    if nivel == PAPER_NIVEL_STOP or pendientes == [nivel]:
        return round(vivas, 4)
    compradas = sum(float(e["acciones"]) for e in ejecuciones if e["nivel"] in PAPER_NIVELES_ENTRADA)
    return round(min(vivas, compradas * float(n.get("peso") or 0)), 4)


def como_operaciones(plan: dict, ejecuciones: list[dict]) -> list[dict]:
    """Ejecuciones en el formato de core_cartera (en la divisa del plan;
    `precio_eur` es solo el nombre del campo que espera el motor)."""
    return [{
        "id": e.get("id"),
        "ticker": plan["ticker"],
        "tipo": "compra" if e["nivel"] in PAPER_NIVELES_ENTRADA else "venta",
        "fecha": e["fecha"],
        "acciones": e["acciones"],
        "precio_eur": e["precio"],
        "comision_eur": 0.0,
    } for e in ejecuciones]


def rendimiento(plan: dict, ejecuciones: list[dict], precio_actual: float | None) -> dict | None:
    """Rendimiento simulado en la divisa del plan: invertido, valor, latente,
    realizado (FIFO) y retorno total sobre lo invertido. None sin ejecuciones."""
    if not ejecuciones:
        return None
    pos = libro(como_operaciones(plan, ejecuciones)).get(plan["ticker"])
    if pos is None:
        return None
    valor = pos["acciones"] * precio_actual if es_dato(precio_actual) and not pos["cerrada"] else (0.0 if pos["cerrada"] else None)
    latente = (valor - pos["coste_total_eur"]) if es_dato(valor) and not pos["cerrada"] else (0.0 if pos["cerrada"] else None)
    total = (latente + pos["realizado_fifo_eur"]) if es_dato(latente) else None
    return {
        "acciones": pos["acciones"],
        "coste_medio": pos["coste_medio_eur"],
        "invertido": pos["invertido_eur"],
        "coste_vivo": pos["coste_total_eur"],
        "valor": valor,
        "latente": latente,
        "latente_pct": (latente / pos["coste_total_eur"] * 100) if es_dato(latente) and pos["coste_total_eur"] else None,
        "realizado": pos["realizado_fifo_eur"],
        "total": total,
        "total_pct": (total / pos["invertido_eur"] * 100) if es_dato(total) and pos["invertido_eur"] else None,
        "cerrada": pos["cerrada"],
    }


def fila_ejecucion(plan_id: int, nivel: str, fecha: date, precio: float, acciones: float,
                   operacion_id: int | None = None) -> dict:
    return {"plan_id": plan_id, "nivel": nivel, "fecha": fecha.isoformat(), "precio": float(precio),
            "acciones": float(acciones), "operacion_id": operacion_id}
