"""Rastreador: funciones puras sobre los resultados de N análisis
(datos_analisis.analizar en modo ligero) y sobre el histórico propio de
análisis para evaluar las señales.

- `fila()` comprime un análisis a lo que necesita la tabla: sin DataFrames
  ni objetos Dato, así N análisis caben en session_state.
- `fila_desde_historico()` hace lo mismo desde una fila persistida de
  `analisis_historico` (modo Screener: lo que el cron rastreó de noche).
- `puntuacion()` es el ranking por defecto (RASTREADOR_PESOS) con veto por
  veredicto: el orden de VEREDICTO_ORDEN manda y la puntuación desempata.
- `evaluar_senales()` mide qué pasó después de cada análisis guardado
  (retorno a 3/6/12 meses y hasta hoy, frente al benchmark) agrupado por
  veredicto y por señal de timing. No inventa señales pasadas: solo evalúa
  las que el motor emitió.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from config_settings import (
    RASTREADOR_EVALUACION_MIN_DIAS,
    RASTREADOR_HORIZONTES,
    RASTREADOR_PESOS,
    TIMING_TRAMOS,
    VEREDICTO_ORDEN,
)
from core_ponderar import es_dato, ponderar, puntuar_tramos


# ---------------------------------------------------------------- filas ----
def fila(a: dict) -> dict:
    """Resumen plano de un análisis para tabla, filtros y comparación."""
    info = (a.get("info").valor if a.get("info") is not None else None) or {}
    fund, ind = a.get("fundamentales") or {}, a.get("indicadores") or {}
    cal, fv, t, p, v = a.get("calidad") or {}, a.get("fair_value") or {}, a.get("timing") or {}, a.get("plan"), a.get("veredicto") or {}
    precio = fv.get("precio") or ind.get("precio")
    e1 = p["entradas"][0]["precio"] if p else None
    senal = t.get("senal")
    f = {
        "ticker": a["ticker"],
        "nombre": info.get("shortName") or info.get("longName") or "",
        "sector": fund.get("sector"),
        "precio": precio,
        "divisa": fund.get("divisa_cotizacion") or fund.get("divisa"),
        "calidad": cal.get("nota"),
        "calidad_cobertura": cal.get("cobertura"),
        "perfil": cal.get("perfil"),
        "bloques": {n: b.get("nota") for n, b in (cal.get("bloques") or {}).items()},
        "fair_value": fv.get("fair_value"),
        "upside_pct": fv.get("upside_pct"),
        "banda": (fv.get("banda") or (None, None))[0],
        "sensibilidad": {k: (d or {}).get("fair_value") for k, d in (fv.get("sensibilidad") or {}).items()},
        "anomalia": bool(fv.get("anomalia")),
        "timing": t.get("nota"),
        "senal": senal[0] if senal else None,
        "senal_color": senal[1] if senal else None,
        "familias": {n: d.get("nota") for n, d in (t.get("familias") or {}).items()},
        "veredicto": v.get("etiqueta"),
        "veredicto_color": v.get("color"),
        "veredicto_motivo": v.get("motivo"),
        "e1": e1,
        "dist_e1_pct": (precio / e1 - 1) * 100 if es_dato(precio) and es_dato(e1) and e1 else None,
        "stop": p["stop"] if p else None,
        "riesgo_pct": p["riesgo_pct"] if p else None,
        "beneficio_pct": p["beneficio_pct"] if p else None,
        "ratio_br": p.get("ratio_br") if p else None,
        "entradas": [(e["nivel"], e["precio"]) for e in p["entradas"]] if p else [],
        "salidas": [(s_["nivel"], s_["precio"]) for s_ in p["salidas"]] if p else [],
        # métricas sueltas para la comparación lado a lado
        "per_forward": fund.get("per_forward"),
        "peg": fund.get("peg"),
        "ev_ebitda": fund.get("ev_ebitda"),
        "roic": fund.get("roic"),
        "margen_operativo": fund.get("margen_operativo"),
        "deuda_patrimonio": fund.get("deuda_patrimonio"),
        "capitalizacion": fund.get("capitalizacion"),
        "rsi": ind.get("rsi"),
        "dist_mm50": ind.get("dist_mm50"),
        "dist_mm200": ind.get("dist_mm200"),
        "variacion_1a": ind.get("variacion_1a"),
        "dist_ath": ind.get("dist_ath"),
        "narrativa": a.get("narrativa"),
        "posicion": a.get("posicion") or {},
    }
    f["puntuacion"], f["puntuacion_cobertura"] = puntuacion(f)
    return f


def fila_desde_historico(h: dict) -> dict:
    """Resumen plano de una fila de `analisis_historico` (Screener): las
    mismas claves que `fila()` que se pueden rellenar sin el análisis vivo;
    las demás quedan None y la comparación lado a lado no se ofrece."""
    plan = h.get("plan") or {}
    entradas = [tuple(e) for e in (plan.get("entradas") or [])]
    salidas = [tuple(x) for x in (plan.get("salidas") or [])]
    precio = h.get("precio")
    e1 = entradas[0][1] if entradas else None
    f = {
        "ticker": h["ticker"], "nombre": h.get("nombre") or "", "sector": h.get("sector"),
        "precio": precio, "divisa": h.get("divisa"),
        "calidad": h.get("calidad"), "perfil": h.get("perfil"),
        "fair_value": h.get("fair_value"), "upside_pct": h.get("upside_pct"), "banda": h.get("banda"),
        "timing": h.get("timing"), "timing_bruto": h.get("timing_bruto"), "senal": h.get("senal_timing"),
        "veredicto": h.get("veredicto"), "fecha": str(h.get("fecha_analisis") or "")[:10],
        "motor_version": h.get("motor_version"),
        "e1": e1, "dist_e1_pct": (precio / e1 - 1) * 100 if es_dato(precio) and es_dato(e1) and e1 else None,
        "stop": plan.get("stop"), "entradas": entradas, "salidas": salidas,
        "ratio_br": None, "riesgo_pct": None, "beneficio_pct": None,
    }
    f["puntuacion"], f["puntuacion_cobertura"] = puntuacion(f)
    return f


def puntuacion(f: dict) -> tuple[float | None, float]:
    """Puntuación de rastreo 0-100 (RASTREADOR_PESOS). El upside se pasa a
    0-100 con el tramo del Timing. Devuelve (nota, cobertura)."""
    up = f.get("upside_pct")
    comp = {
        "calidad": (RASTREADOR_PESOS["calidad"], f.get("calidad")),
        "timing": (RASTREADOR_PESOS["timing"], f.get("timing")),
        "upside": (RASTREADOR_PESOS["upside"], puntuar_tramos(up, TIMING_TRAMOS["upside"]) if es_dato(up) else None),
    }
    p = ponderar(comp, cobertura_minima=0.5)
    return p.valor, p.cobertura


def _orden_veredicto(v: str | None) -> int:
    return VEREDICTO_ORDEN.index(v) if v in VEREDICTO_ORDEN else len(VEREDICTO_ORDEN)


CRITERIOS_ORDEN = {
    "Veredicto y puntuación": lambda f: (_orden_veredicto(f.get("veredicto")), -(f.get("puntuacion") if es_dato(f.get("puntuacion")) else -1)),
    "Puntuación": lambda f: -(f.get("puntuacion") if es_dato(f.get("puntuacion")) else -1),
    "Upside": lambda f: -(f.get("upside_pct") if es_dato(f.get("upside_pct")) else -1e9),
    "Calidad": lambda f: -(f.get("calidad") if es_dato(f.get("calidad")) else -1),
    "Timing": lambda f: -(f.get("timing") if es_dato(f.get("timing")) else -1),
    "Cercanía a E1": lambda f: (abs(f["dist_e1_pct"]) if es_dato(f.get("dist_e1_pct")) else 1e9),
}


def ordenar(filas: list[dict], criterio: str) -> list[dict]:
    return sorted(filas, key=CRITERIOS_ORDEN.get(criterio, CRITERIOS_ORDEN["Veredicto y puntuación"]))


def filtrar(filas: list[dict], calidad_min: float = 0, upside_min: float = -100, timing_min: float = 0,
            veredictos: tuple[str, ...] | list[str] | None = None, solo_con_dato: bool = False,
            senales: tuple[str, ...] | list[str] | None = None, sectores: tuple[str, ...] | list[str] | None = None,
            bandas: tuple[str, ...] | list[str] | None = None, timing_bruto: bool = False) -> list[dict]:
    """Filtro por umbrales. Un valor SIN dato en la métrica filtrada pasa
    (no se descarta lo que no se ha podido medir) salvo `solo_con_dato`.
    `timing_bruto`: filtra por la nota SIN el gate de calidad (modo
    "trading" del Screener, etiquetado como tal en la vista)."""
    def ok(v, minimo):
        return (v >= minimo) if es_dato(v) else not solo_con_dato
    out = []
    for f in filas:
        t = f.get("timing_bruto") if timing_bruto and es_dato(f.get("timing_bruto")) else f.get("timing")
        if not ok(f.get("calidad"), calidad_min) or not ok(f.get("upside_pct"), upside_min) or not ok(t, timing_min):
            continue
        if veredictos and f.get("veredicto") not in veredictos:
            continue
        if senales and f.get("senal") not in senales:
            continue
        if sectores and f.get("sector") not in sectores:
            continue
        if bandas and (f.get("banda") or "").split(" — ")[0] not in bandas:
            continue
        out.append(f)
    return out


# --------------------------------------------------- evaluación de señales --
def _retorno(serie: pd.Series | None, desde: date, dias: int | None, precio0: float | None) -> float | None:
    """Retorno % desde `precio0` (o el cierre del día del análisis) hasta
    `desde + dias` (último cierre disponible hasta esa fecha) o hasta hoy."""
    if serie is None or serie.empty:
        return None
    v = serie.dropna()
    if v.empty:
        return None
    p0 = float(precio0) if es_dato(precio0) and precio0 > 0 else None
    if p0 is None:
        hasta0 = v.loc[:pd.Timestamp(desde)]
        if hasta0.empty:
            return None
        p0 = float(hasta0.iloc[-1])
    if dias is None:
        p1 = float(v.iloc[-1])
    else:
        fin = pd.Timestamp(desde + timedelta(days=dias))
        if v.index[-1] < fin:                    # horizonte aún no cumplido
            return None
        tramo = v.loc[:fin]
        if tramo.empty:
            return None
        p1 = float(tramo.iloc[-1])
    return (p1 / p0 - 1) * 100 if p0 else None


def evaluar_senales(analisis: list[dict], cierres: dict[str, pd.Series], bench: pd.Series | None,
                    hoy: date | None = None) -> tuple[list[dict], dict[str, list[dict]]]:
    """Por cada análisis guardado: retorno hasta hoy y a cada horizonte
    cumplido, y lo mismo del benchmark desde la misma fecha. Devuelve
    (detalle por análisis, resúmenes agrupados por 'veredicto' y 'senal').
    El precio de partida es el guardado en el análisis (divisa de
    cotización); los cierres deben ir en esa misma divisa."""
    hoy = hoy or date.today()
    detalle = []
    for a in analisis:
        f = pd.Timestamp(a["fecha_analisis"]).date()
        if (hoy - f).days < RASTREADOR_EVALUACION_MIN_DIAS:
            continue
        serie = cierres.get(a["ticker"])
        d = {"ticker": a["ticker"], "fecha": f, "veredicto": a.get("veredicto"), "senal": a.get("senal_timing"),
             "motor_version": a.get("motor_version"), "precio": a.get("precio"), "dias": (hoy - f).days,
             "ret_hoy": _retorno(serie, f, None, a.get("precio")),
             "bench_hoy": _retorno(bench, f, None, None)}
        for nombre, dias in RASTREADOR_HORIZONTES.items():
            d[f"ret_{nombre}"] = _retorno(serie, f, dias, a.get("precio"))
            d[f"bench_{nombre}"] = _retorno(bench, f, dias, None)
        if d["ret_hoy"] is None:
            continue
        detalle.append(d)

    def resumen(clave: str) -> list[dict]:
        grupos: dict[str, list[dict]] = {}
        for d in detalle:
            grupos.setdefault(d.get(clave) or "Sin dato", []).append(d)
        filas = []
        for nombre, items in grupos.items():
            r = {"grupo": nombre, "n": len(items)}
            hoy_ = [x["ret_hoy"] for x in items if es_dato(x["ret_hoy"])]
            r["ret_hoy"] = sum(hoy_) / len(hoy_) if hoy_ else None
            r["pct_positivos"] = sum(1 for x in hoy_ if x > 0) / len(hoy_) * 100 if hoy_ else None
            dif = [x["ret_hoy"] - x["bench_hoy"] for x in items if es_dato(x["ret_hoy"]) and es_dato(x["bench_hoy"])]
            r["vs_bench_hoy"] = sum(dif) / len(dif) if dif else None
            for h in RASTREADOR_HORIZONTES:
                vals = [x[f"ret_{h}"] for x in items if es_dato(x.get(f"ret_{h}"))]
                r[f"ret_{h}"] = sum(vals) / len(vals) if vals else None
                r[f"n_{h}"] = len(vals)
            filas.append(r)
        orden = VEREDICTO_ORDEN if clave == "veredicto" else ("ENTRAR", "ACUMULAR", "VIGILAR", "ESPERAR", "EVITAR")
        return sorted(filas, key=lambda r: orden.index(r["grupo"]) if r["grupo"] in orden else 99)

    return detalle, {"veredicto": resumen("veredicto"), "senal": resumen("senal")}


def filas_backtest(detalle: list[dict], origen: str | None = None) -> list[dict]:
    """Filas para `backtest_resultados` (solo análisis con al menos el primer
    horizonte cumplido: antes no hay nada que persistir). `origen` queda en
    `parametros` para distinguir las señales del cron."""
    out = []
    for d in detalle:
        if not es_dato(d.get("ret_3m")):
            continue
        out.append({
            "motor_version": d.get("motor_version") or "", "ticker": d["ticker"], "fecha_senal": d["fecha"].isoformat(),
            "senal": d.get("veredicto") or d.get("senal") or "", "precio": d.get("precio"),
            "retorno_3m": d.get("ret_3m"), "retorno_6m": d.get("ret_6m"), "retorno_12m": d.get("ret_12m"),
            "bench_3m": d.get("bench_3m"), "bench_6m": d.get("bench_6m"), "bench_12m": d.get("bench_12m"),
            "parametros": {"senal_timing": d.get("senal"), **({"origen": origen} if origen else {})},
        })
    return out


def resumen_backtest(filas: list[dict]) -> dict[str, list[dict]]:
    """Resúmenes por veredicto (`senal`) y por señal de timing
    (`parametros.senal_timing`) de las filas persistidas en
    `backtest_resultados`: n, retorno medio y diferencia media frente al
    benchmark a cada horizonte, % de positivos a 3 meses."""
    def resumen(clave_fn) -> list[dict]:
        grupos: dict[str, list[dict]] = {}
        for f in filas:
            grupos.setdefault(clave_fn(f) or "Sin dato", []).append(f)
        out = []
        for nombre, items in grupos.items():
            r = {"grupo": nombre, "n": len(items)}
            for h in RASTREADOR_HORIZONTES:
                rets = [x[f"retorno_{h}"] for x in items if es_dato(x.get(f"retorno_{h}"))]
                difs = [x[f"retorno_{h}"] - x[f"bench_{h}"] for x in items
                        if es_dato(x.get(f"retorno_{h}")) and es_dato(x.get(f"bench_{h}"))]
                r[f"ret_{h}"] = sum(rets) / len(rets) if rets else None
                r[f"vs_bench_{h}"] = sum(difs) / len(difs) if difs else None
                r[f"n_{h}"] = len(rets)
            pos = [x["retorno_3m"] for x in items if es_dato(x.get("retorno_3m"))]
            r["pct_positivos_3m"] = sum(1 for x in pos if x > 0) / len(pos) * 100 if pos else None
            out.append(r)
        return out
    orden_v = VEREDICTO_ORDEN
    orden_s = ("ENTRAR", "ACUMULAR", "VIGILAR", "ESPERAR", "EVITAR")
    por_v = sorted(resumen(lambda f: f.get("senal")), key=lambda r: orden_v.index(r["grupo"]) if r["grupo"] in orden_v else 99)
    por_s = sorted(resumen(lambda f: (f.get("parametros") or {}).get("senal_timing")),
                   key=lambda r: orden_s.index(r["grupo"]) if r["grupo"] in orden_s else 99)
    return {"veredicto": por_v, "senal": por_s}
