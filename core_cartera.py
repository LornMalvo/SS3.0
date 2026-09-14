"""Motor de Gestión de Cartera. Todo se DERIVA del libro de operaciones
(`cartera_operaciones`): no hay estado redundante que pueda desincronizarse.

Funciones puras sobre listas de dicts y DataFrames: sin Streamlit, sin red.
Las usa también Paper Trading (operaciones con origen 'paper'), así el
rendimiento simulado y el real salen del mismo código.

Dos costes medios, a propósito:
- PONDERADO: (suma de compras + comisiones) / acciones. Es el que se enseña
  en la ficha y sobre el que trabaja el stop del plan DCA.
- FIFO: las primeras acciones compradas son las primeras que salen. Es el
  que manda en el beneficio REALIZADO (criterio fiscal español).
Las comisiones de compra se capitalizan en el coste; las de venta restan del
realizado. Divisa base EUR: aquí ya no hay divisas, entran `precio_eur`.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from config_settings import (
    CARTERA_CORRELACION_ALTA,
    CARTERA_CORRELACION_MIN_SESIONES,
    CARTERA_PESO_ALERTA,
    CARTERA_SECTOR_ALERTA,
    CARTERA_TOLERANCIA_ACCIONES,
)
from core_ponderar import es_dato


def _f(v, defecto: float = 0.0) -> float:
    return float(v) if es_dato(v) else defecto


def _fecha(v) -> date:
    if isinstance(v, date):
        return v
    return pd.Timestamp(v).date()


# -------------------------------------------------------------------- libro --
def _posicion_vacia(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "acciones": 0.0,
        "coste_medio_eur": None,     # ponderado, con comisiones de compra
        "coste_total_eur": 0.0,      # acciones * coste_medio
        "invertido_eur": 0.0,        # todo lo que ha entrado en compras (histórico)
        "comisiones_eur": 0.0,
        "realizado_fifo_eur": 0.0,
        "lotes": [],                 # FIFO: [{fecha, acciones, precio_eur (con comisión prorrateada)}]
        "n_compras": 0,
        "n_ventas": 0,
        "primera_fecha": None,
        "ultima_fecha": None,
        "cerrada": True,
    }


def _comprar(pos: dict, op: dict) -> None:
    acc, precio, com = _f(op["acciones"]), _f(op["precio_eur"]), _f(op.get("comision_eur"))
    importe = acc * precio + com
    pos["coste_total_eur"] += importe
    pos["acciones"] += acc
    pos["coste_medio_eur"] = pos["coste_total_eur"] / pos["acciones"]
    pos["invertido_eur"] += importe
    pos["comisiones_eur"] += com
    pos["n_compras"] += 1
    pos["lotes"].append({"fecha": _fecha(op["fecha"]), "acciones": acc, "precio_eur": importe / acc if acc else precio})


def _vender(pos: dict, op: dict) -> None:
    """Venta: el coste medio ponderado no cambia (solo salen acciones); el
    realizado sale del FIFO. Una venta mayor que la posición se recorta a
    lo que hay (la interfaz ya la bloquea antes de insertarla)."""
    acc = min(_f(op["acciones"]), pos["acciones"])
    precio, com = _f(op["precio_eur"]), _f(op.get("comision_eur"))
    coste_fifo, restante = 0.0, acc
    while restante > CARTERA_TOLERANCIA_ACCIONES and pos["lotes"]:
        lote = pos["lotes"][0]
        tomo = min(lote["acciones"], restante)
        coste_fifo += tomo * lote["precio_eur"]
        lote["acciones"] -= tomo
        restante -= tomo
        if lote["acciones"] <= CARTERA_TOLERANCIA_ACCIONES:
            pos["lotes"].pop(0)
    pos["realizado_fifo_eur"] += acc * precio - com - coste_fifo
    pos["comisiones_eur"] += com
    pos["acciones"] -= acc
    if pos["acciones"] <= CARTERA_TOLERANCIA_ACCIONES:
        pos["acciones"] = 0.0
        pos["coste_total_eur"] = 0.0
        pos["lotes"] = []
    else:
        pos["coste_total_eur"] = pos["acciones"] * (pos["coste_medio_eur"] or 0.0)
    pos["n_ventas"] += 1


def orden_cronologico(operaciones: list[dict]) -> list[dict]:
    """Orden (fecha, id). El id desempata dentro del mismo día; los ids en
    memoria (sin Supabase) son negativos y crecen en valor absoluto, de ahí
    el abs(): sin él, una venta registrada después de la compra del mismo
    día se procesaría antes y el FIFO no encontraría lote que vender."""
    return sorted(operaciones, key=lambda o: (str(o.get("fecha")), abs(o.get("id") or 0)))


def libro(operaciones: list[dict]) -> dict[str, dict]:
    """Reproduce el libro en orden cronológico y devuelve ticker -> posición."""
    posiciones: dict[str, dict] = {}
    for op in orden_cronologico(operaciones):
        t = op["ticker"]
        pos = posiciones.setdefault(t, _posicion_vacia(t))
        f = _fecha(op["fecha"])
        pos["primera_fecha"] = pos["primera_fecha"] or f
        pos["ultima_fecha"] = f
        if op["tipo"] == "compra":
            _comprar(pos, op)
        else:
            _vender(pos, op)
        pos["cerrada"] = pos["acciones"] <= CARTERA_TOLERANCIA_ACCIONES
    return posiciones


def disponibles(operaciones: list[dict], ticker: str) -> float:
    """Acciones que se pueden vender hoy de un ticker (bloqueo de sobreventa)."""
    pos = libro([o for o in operaciones if o.get("ticker") == ticker]).get(ticker)
    return pos["acciones"] if pos else 0.0


# --------------------------------------------------------------- valoración --
def valorar(posiciones: dict[str, dict], precios_eur: dict[str, float | None]) -> dict[str, dict]:
    """Añade valor actual, latente y peso a cada posición ABIERTA. Sin precio
    en EUR (ticker sin dato o divisa no convertible) el valor queda None y la
    posición no entra en los pesos: nunca se inventa un cero."""
    abiertas = {t: p for t, p in posiciones.items() if not p["cerrada"]}
    for p in abiertas.values():
        precio = precios_eur.get(p["ticker"])
        if es_dato(precio):
            p["precio_eur"] = float(precio)
            p["valor_eur"] = p["acciones"] * float(precio)
            p["latente_eur"] = p["valor_eur"] - p["coste_total_eur"]
            p["latente_pct"] = (p["latente_eur"] / p["coste_total_eur"] * 100) if p["coste_total_eur"] else None
        else:
            p["precio_eur"] = p["valor_eur"] = p["latente_eur"] = p["latente_pct"] = None
    total = sum(p["valor_eur"] for p in abiertas.values() if es_dato(p.get("valor_eur")))
    for p in abiertas.values():
        p["peso_pct"] = (p["valor_eur"] / total * 100) if total and es_dato(p.get("valor_eur")) else None
        p["peso_alto"] = es_dato(p.get("peso_pct")) and p["peso_pct"] / 100 >= CARTERA_PESO_ALERTA
    return posiciones


def resumen(posiciones: dict[str, dict]) -> dict:
    """Totales de la cartera. `retorno_total_pct` es (latente + realizado)
    sobre todo lo invertido históricamente: una sola cifra de "cómo va"."""
    abiertas = [p for p in posiciones.values() if not p["cerrada"]]
    con_precio = [p for p in abiertas if es_dato(p.get("valor_eur"))]
    coste = sum(p["coste_total_eur"] for p in abiertas)
    valor = sum(p["valor_eur"] for p in con_precio)
    latente = sum(p["latente_eur"] for p in con_precio)
    realizado = sum(p["realizado_fifo_eur"] for p in posiciones.values())
    invertido = sum(p["invertido_eur"] for p in posiciones.values())
    comisiones = sum(p["comisiones_eur"] for p in posiciones.values())
    return {
        "n_abiertas": len(abiertas),
        "n_cerradas": sum(1 for p in posiciones.values() if p["cerrada"]),
        "n_sin_precio": len(abiertas) - len(con_precio),
        "coste_eur": coste,
        "valor_eur": valor if con_precio else None,
        "latente_eur": latente if con_precio else None,
        "latente_pct": (latente / sum(p["coste_total_eur"] for p in con_precio) * 100)
                        if con_precio and sum(p["coste_total_eur"] for p in con_precio) else None,
        "realizado_eur": realizado,
        "invertido_eur": invertido,
        "comisiones_eur": comisiones,
        # Con todo cerrado no hay latente pero sí un resultado: se informa igual.
        "retorno_total_pct": ((latente + realizado) / invertido * 100) if invertido and (con_precio or not abiertas) else None,
    }


# -------------------------------------------------------------- benchmark ----
def curva_vs_benchmark(operaciones: list[dict], cierres_eur: pd.DataFrame,
                       bench_eur: pd.Series | None) -> pd.DataFrame | None:
    """Curva diaria del valor de la cartera frente a una "cartera sombra"
    que hace EXACTAMENTE los mismos movimientos en el benchmark: cada compra
    de X EUR compra X EUR de SPY ese día; cada venta de una fracción de la
    posición vende la misma fracción de su sombra. Así se compara el mismo
    dinero en las mismas fechas (money-weighted), no dos índices base 100.

    Columnas: cartera, benchmark, invertido (coste vivo). None sin datos."""
    if not operaciones or cierres_eur is None or cierres_eur.empty or bench_eur is None or bench_eur.empty:
        return None
    ops = orden_cronologico(operaciones)
    inicio = pd.Timestamp(_fecha(ops[0]["fecha"]))
    idx = cierres_eur.index.union(bench_eur.index)
    idx = idx[idx >= inicio]
    if len(idx) == 0:
        return None
    cierres = cierres_eur.reindex(idx).ffill()
    bench = bench_eur.reindex(idx).ffill()

    acciones: dict[str, float] = {}
    sombra: dict[str, float] = {}      # unidades de benchmark por ticker
    coste: dict[str, float] = {}
    filas = []
    i_op = 0
    for dia in idx:
        while i_op < len(ops) and pd.Timestamp(_fecha(ops[i_op]["fecha"])) <= dia:
            op = ops[i_op]
            i_op += 1
            t, acc = op["ticker"], _f(op["acciones"])
            b = bench.get(dia)
            if op["tipo"] == "compra":
                importe = acc * _f(op["precio_eur"]) + _f(op.get("comision_eur"))
                acciones[t] = acciones.get(t, 0.0) + acc
                coste[t] = coste.get(t, 0.0) + importe
                if es_dato(b) and b:
                    sombra[t] = sombra.get(t, 0.0) + importe / float(b)
            else:
                tenia = acciones.get(t, 0.0)
                if tenia <= CARTERA_TOLERANCIA_ACCIONES:
                    continue
                frac = min(acc, tenia) / tenia
                acciones[t] = tenia * (1 - frac)
                coste[t] = coste.get(t, 0.0) * (1 - frac)
                sombra[t] = sombra.get(t, 0.0) * (1 - frac)
                if acciones[t] <= CARTERA_TOLERANCIA_ACCIONES:
                    acciones[t] = coste[t] = sombra[t] = 0.0
        valor = 0.0
        for t, n in acciones.items():
            if n <= 0 or t not in cierres.columns:
                continue
            c = cierres.at[dia, t]
            if es_dato(c):
                valor += n * float(c)
        b = bench.get(dia)
        filas.append({
            "fecha": dia,
            "cartera": valor,
            "benchmark": sum(sombra.values()) * float(b) if es_dato(b) else np.nan,
            "invertido": sum(coste.values()),
        })
    df = pd.DataFrame(filas).set_index("fecha")
    return df if not df.empty else None


def retorno_curva(df: pd.DataFrame | None) -> dict:
    """Retorno final de cada curva sobre el coste vivo (misma base para ambas)."""
    if df is None or df.empty:
        return {"cartera_pct": None, "benchmark_pct": None, "diferencia_pp": None}
    ult = df.iloc[-1]
    inv = ult["invertido"]
    if not inv:
        return {"cartera_pct": None, "benchmark_pct": None, "diferencia_pp": None}
    c = (ult["cartera"] / inv - 1) * 100
    b = (ult["benchmark"] / inv - 1) * 100 if es_dato(ult["benchmark"]) else None
    return {"cartera_pct": c, "benchmark_pct": b, "diferencia_pp": (c - b) if es_dato(b) else None}


# ------------------------------------------------------------------ riesgo --
def exposicion_sector(posiciones: dict[str, dict], sectores: dict[str, str | None]) -> list[dict]:
    """Peso de cada sector sobre el valor de las posiciones abiertas con
    precio. Sin sector conocido -> "Sin sector" (no se inventa uno)."""
    abiertas = [p for p in posiciones.values() if not p["cerrada"] and es_dato(p.get("valor_eur"))]
    total = sum(p["valor_eur"] for p in abiertas)
    if not total:
        return []
    acum: dict[str, dict] = {}
    for p in abiertas:
        s = sectores.get(p["ticker"]) or "Sin sector"
        d = acum.setdefault(s, {"sector": s, "valor_eur": 0.0, "tickers": []})
        d["valor_eur"] += p["valor_eur"]
        d["tickers"].append(p["ticker"])
    out = sorted(acum.values(), key=lambda d: -d["valor_eur"])
    for d in out:
        d["peso_pct"] = d["valor_eur"] / total * 100
        d["alerta"] = d["peso_pct"] / 100 >= CARTERA_SECTOR_ALERTA
    return out


def correlacion(cierres: pd.DataFrame | None) -> tuple[pd.DataFrame | None, list[dict]]:
    """Correlación de rendimientos diarios entre posiciones (matriz) y lista
    de pares por encima del umbral "misma apuesta". Tickers con menos de
    CARTERA_CORRELACION_MIN_SESIONES sesiones comunes quedan fuera."""
    if cierres is None or cierres.empty or cierres.shape[1] < 2:
        return None, []
    rend = cierres.pct_change().dropna(how="all")
    rend = rend.dropna(axis=1, thresh=CARTERA_CORRELACION_MIN_SESIONES)
    if rend.shape[1] < 2:
        return None, []
    m = rend.corr(min_periods=CARTERA_CORRELACION_MIN_SESIONES)
    pares = []
    cols = list(m.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            v = m.at[a, b]
            if es_dato(v) and v >= CARTERA_CORRELACION_ALTA:
                pares.append({"a": a, "b": b, "corr": float(v)})
    pares.sort(key=lambda d: -d["corr"])
    return m, pares
