"""Motor de Timing 0-100: ¿es buen momento para entrar?

Quince componentes en cinco familias (config_settings.TIMING_PESOS y
TIMING_FAMILIAS), cada uno convertido a 0-100 por tramos (TIMING_TRAMOS) y
ponderado con `ponderar()`: un componente sin dato se excluye y su peso se
reparte, y la cobertura se enseña. Gate de calidad: sin salud >= 60 la nota
se topa en TIMING_TOPE_SIN_SALUD (buen timing en mala empresa es trading).

Función pura sobre (histórico, indicadores, fundamentales, calidad, fair
value, earnings, plan): reconstruible para el backtesting a cualquier fecha.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from config_settings import (
    CALIDAD_MINIMA_TIMING,
    MOTOR_VERSION,
    TIMING_FAMILIAS,
    TIMING_OBV_SESIONES,
    TIMING_PESOS,
    TIMING_TOPE_SIN_SALUD,
    TIMING_TRAMOS,
    TIMING_VOLUMEN_DISTRIBUCION,
)
from core_indicadores import obv
from core_plan_dca import senal_timing
from core_ponderar import es_dato, ponderar, puntuar_tramos

ETIQUETAS = {
    "rsi": "RSI", "macd": "MACD", "obv": "OBV (acumulación)", "adx": "ADX (tendencia)",
    "mm50": "MM50", "mm100": "MM100", "mm200": "MM200", "ath_atl": "Distancia a máximos",
    "variacion_1a": "Variación 1 año", "upside": "Upside (fair value)", "peg": "PEG",
    "salud_fundamental": "Calidad fundamental", "proximidad_earnings": "Proximidad a earnings",
    "confluencia_dca": "Cercanía a la zona de entrada", "volumen_relativo": "Volumen relativo",
}


def _obv_normalizado(df: pd.DataFrame | None) -> float | None:
    """Variación del OBV en TIMING_OBV_SESIONES sesiones, en unidades de
    "sesiones de volumen medio": +1 = la presión compradora neta equivale a
    todo el volumen medio de esas sesiones."""
    if df is None or len(df) < 63 + TIMING_OBV_SESIONES:
        return None
    serie = obv(df)
    base = df["Volume"].iloc[-63:].mean()
    if not es_dato(base) or base <= 0:
        return None
    return float((serie.iloc[-1] - serie.iloc[-1 - TIMING_OBV_SESIONES]) / (base * TIMING_OBV_SESIONES))


def _dias_hasta(fecha) -> float | None:
    if isinstance(fecha, date):
        return float((fecha - date.today()).days)
    return None


def valores(df, ind: dict, fund: dict, calidad: dict | None, fair_value: dict | None,
            earnings: dict | None, plan: dict | None) -> tuple[dict[str, float | None], dict[str, str]]:
    """Valor crudo de cada componente (en la unidad que espera su tramo) y
    motivo cuando falta."""
    m: dict[str, float | None] = {}
    motivos: dict[str, str] = {}
    atr = ind.get("atr")
    m["rsi"] = ind.get("rsi")
    m["macd"] = (ind["macd_hist"] / atr) if es_dato(ind.get("macd_hist")) and es_dato(atr) and atr > 0 else None
    if m["macd"] is None:
        motivos["macd"] = "sin histograma o sin ATR"
    m["obv"] = _obv_normalizado(df)
    if m["obv"] is None:
        motivos["obv"] = "histórico insuficiente"
    # ADX: se puntúa directamente (no por tramos): 50 +- fuerza según dirección
    if es_dato(ind.get("adx")) and es_dato(ind.get("di_pos")) and es_dato(ind.get("di_neg")):
        fuerza = min(float(ind["adx"]), 50.0)
        m["adx"] = 50 + fuerza if ind["di_pos"] >= ind["di_neg"] else 50 - fuerza
    else:
        m["adx"] = None
        motivos["adx"] = "sin ADX"
    m["mm50"], m["mm100"], m["mm200"] = ind.get("dist_mm50"), ind.get("dist_mm100"), ind.get("dist_mm200")
    for k in ("mm50", "mm100", "mm200"):
        if m[k] is None:
            motivos[k] = "histórico más corto que la media"
    m["ath_atl"] = ind.get("dist_ath")
    m["variacion_1a"] = ind.get("variacion_1a")
    if m["variacion_1a"] is None:
        motivos["variacion_1a"] = "menos de un año de histórico"
    m["upside"] = (fair_value or {}).get("upside_pct")
    if m["upside"] is None:
        motivos["upside"] = "sin fair value"
    peg = fund.get("peg")
    m["peg"] = peg if es_dato(peg) and peg > 0 else None
    if m["peg"] is None:
        motivos["peg"] = "PEG no positivo o ausente"
    m["salud_fundamental"] = (calidad or {}).get("nota")
    if m["salud_fundamental"] is None:
        motivos["salud_fundamental"] = "calidad sin nota fiable"
    proximo = (earnings or {}).get("proximo") if earnings else None
    m["proximidad_earnings"] = _dias_hasta(proximo.get("fecha")) if proximo else None
    if m["proximidad_earnings"] is None:
        motivos["proximidad_earnings"] = "fecha del próximo earnings desconocida"
    m["confluencia_dca"] = (plan or {}).get("n1_dist_atr")
    if m["confluencia_dca"] is None:
        motivos["confluencia_dca"] = "sin plan o sin ATR"
    m["volumen_relativo"] = ind.get("volumen_relativo")
    if m["volumen_relativo"] is None:
        motivos["volumen_relativo"] = "histórico insuficiente"
    return m, motivos


def _puntos(clave: str, valor, df) -> float | None:
    if not es_dato(valor):
        return None
    if clave == "adx" or clave == "salud_fundamental":
        return float(max(0.0, min(100.0, valor)))
    if clave == "volumen_relativo":
        # volumen alto con precio cayendo en la ventana corta es distribución
        if df is not None and len(df) > 6 and valor > 1.3:
            ret5 = df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1
            if ret5 < -0.01:
                return float(TIMING_VOLUMEN_DISTRIBUCION)
    return puntuar_tramos(valor, TIMING_TRAMOS[clave])


def calcular(df, ind: dict, fund: dict, calidad: dict | None, fair_value: dict | None,
             earnings: dict | None, plan: dict | None) -> dict:
    crudos, motivos = valores(df, ind, fund, calidad, fair_value, earnings, plan)
    componentes, detalle = {}, {}
    for clave, peso in TIMING_PESOS.items():
        pts = _puntos(clave, crudos.get(clave), df)
        componentes[clave] = (peso, pts)
        if pts is None and clave not in motivos:
            motivos[clave] = "sin dato"
        detalle[clave] = {"etiqueta": ETIQUETAS[clave], "valor": crudos.get(clave), "puntos": pts, "peso": peso,
                          "motivo": motivos.get(clave) if pts is None else None}
    p = ponderar(componentes, motivos=motivos)
    for clave in detalle:
        detalle[clave]["peso_efectivo"] = p.usados.get(clave)

    familias = {}
    for nombre, claves in TIMING_FAMILIAS.items():
        pf = ponderar({k: componentes[k] for k in claves})
        familias[nombre] = {"nota": pf.valor, "peso": sum(TIMING_PESOS[k] for k in claves), "cobertura": pf.cobertura,
                            "componentes": {k: detalle[k] for k in claves}}

    nota_bruta = p.valor
    salud = (calidad or {}).get("nota")
    gate = es_dato(nota_bruta) and (not es_dato(salud) or salud < CALIDAD_MINIMA_TIMING) and nota_bruta > TIMING_TOPE_SIN_SALUD
    nota = float(min(nota_bruta, TIMING_TOPE_SIN_SALUD)) if gate else nota_bruta

    con_puntos = [(d["puntos"], d["etiqueta"]) for d in detalle.values() if d["puntos"] is not None]
    mejores = [e for pts, e in sorted(con_puntos, key=lambda x: -x[0]) if pts >= 70][:3]
    peores = [e for pts, e in sorted(con_puntos, key=lambda x: x[0]) if pts <= 40][:3]
    return {
        "nota": nota,
        "nota_bruta": nota_bruta,
        "gate": bool(gate),
        "senal": senal_timing(nota),
        "cobertura": p.cobertura,
        "familias": familias,
        "componentes": detalle,
        "mejores": mejores,
        "peores": peores,
        "version": MOTOR_VERSION,
    }
