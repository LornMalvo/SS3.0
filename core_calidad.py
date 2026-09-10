"""Motor de Calidad 0-100: ¿es una buena empresa?

Tres bloques (Crecimiento 30, Rentabilidad y foso 40, Salud financiera 30).
La valoración relativa al sector NO entra aquí: mide precio y ya vive en el
Fair Value y en el Timing (ver comentario en config_settings.CALIDAD_BLOQUES).

Función pura: (fundamentales, estados financieros) -> resultado. Cada métrica
sale con valor crudo, puntos 0-100, peso y referencia usada, para que la
interfaz enseñe exactamente qué falla y cuánto pesa, y para que el
backtesting pueda reconstruirla sobre estados de otra fecha.
"""

from __future__ import annotations

import math

import pandas as pd

import config_sectores as sec
from config_settings import (
    CALIDAD_ANIOS_CRECIMIENTO,
    CALIDAD_BLOQUES,
    CALIDAD_COBERTURA_MINIMA,
    CALIDAD_METRICAS_NO_FINANCIERAS,
    CALIDAD_METRICAS_RELATIVAS,
    CALIDAD_TRAMOS,
    CALIDAD_TRAMOS_APALANCADOS,
    CALIDAD_TRAMOS_RELATIVOS,
    MOTOR_VERSION,
    PERFIL_PRE_RENTABILIDAD,
    PERFIL_RENTABLE,
)
from core_ponderar import es_dato, ponderar, puntuar_tramos

ETIQUETAS = {
    "cagr_ingresos_3a": "Crecimiento ingresos (CAGR 3a)",
    "cagr_bpa_3a": "Crecimiento BPA (CAGR 3a)",
    "consistencia_ingresos": "Consistencia de ingresos",
    "crecimiento_fcf": "Crecimiento FCF (CAGR 3a)",
    "roic": "ROIC",
    "margen_bruto": "Margen bruto",
    "margen_operativo": "Margen operativo",
    "margen_fcf": "Margen FCF",
    "calidad_beneficio": "Calidad del beneficio (FCF / BN)",
    "roe": "ROE",
    "deuda_neta_ebitda": "Deuda neta / EBITDA",
    "cobertura_intereses": "Cobertura de intereses",
    "dilucion": "Dilución (acciones 3a)",
    "current_ratio": "Current ratio",
    "fcf_positivo": "Ejercicios con FCF positivo",
    "deuda_patrimonio": "Deuda / Equity",
}
REFERENCIAS_SECTOR = {
    "roic": sec.ROIC_SECTOR,
    "margen_bruto": sec.MARGEN_BRUTO_SECTOR,
    "margen_operativo": sec.MARGEN_OPERATIVO_SECTOR,
    "roe": sec.ROE_SECTOR,
}


# ------------------------------------------------------ lectura de estados --
def serie(df: pd.DataFrame | None, *nombres: str) -> list[float]:
    """Valores anuales de la primera fila que exista, del ejercicio más
    antiguo al más reciente, saltando huecos."""
    if df is None or df.empty:
        return []
    for nombre in nombres:
        if nombre in df.index:
            valores = [float(v) for v in reversed(df.loc[nombre].tolist()) if es_dato(v)]
            if valores:
                return valores
    return []


def cagr(valores: list[float], anios: int = CALIDAD_ANIOS_CRECIMIENTO) -> float | None:
    """CAGR entre el primer y el último valor de la ventana. Sin definición si
    algún extremo no es positivo (un BPA que pasa de negativo a positivo no
    tiene tasa compuesta; el hueco lo absorbe ponderar())."""
    v = valores[-(anios + 1):]
    if len(v) < 2 or v[0] <= 0 or v[-1] <= 0:
        return None
    n = len(v) - 1
    return (v[-1] / v[0]) ** (1 / n) - 1


def consistencia(valores: list[float]) -> float | None:
    v = valores[-(CALIDAD_ANIOS_CRECIMIENTO + 1):]
    if len(v) < 2:
        return None
    subidas = sum(1 for a, b in zip(v, v[1:]) if b > a)
    return subidas / (len(v) - 1)


# ------------------------------------------------------------ métricas -------
def metricas(fund: dict, estados: dict | None) -> tuple[dict[str, float | None], dict[str, str]]:
    """Valor crudo de cada métrica y motivo de ausencia cuando lo hay."""
    e = estados or {}
    res, bal, fc = e.get("resultados"), e.get("balance"), e.get("flujo_caja")
    motivos: dict[str, str] = {}
    sector = fund.get("sector")
    financiera = sector == "Financial Services"

    ingresos = serie(res, "Total Revenue", "Operating Revenue")
    bpa = serie(res, "Diluted EPS", "Basic EPS")
    fcf = serie(fc, "Free Cash Flow")
    acciones = serie(res, "Diluted Average Shares", "Basic Average Shares") or serie(bal, "Ordinary Shares Number", "Share Issued")
    ebit = serie(res, "EBIT", "Operating Income")
    intereses = serie(res, "Interest Expense", "Interest Expense Non Operating")

    m: dict[str, float | None] = {}
    m["cagr_ingresos_3a"] = cagr(ingresos)
    if m["cagr_ingresos_3a"] is None:
        motivos["cagr_ingresos_3a"] = "serie de ingresos insuficiente"
    m["cagr_bpa_3a"] = cagr(bpa)
    if m["cagr_bpa_3a"] is None:
        motivos["cagr_bpa_3a"] = "BPA no positivo en los extremos del periodo" if bpa else "sin serie de BPA"
    m["consistencia_ingresos"] = consistencia(ingresos)
    m["crecimiento_fcf"] = cagr(fcf)
    if m["crecimiento_fcf"] is None:
        motivos["crecimiento_fcf"] = "FCF no positivo en los extremos del periodo" if fcf else "sin serie de FCF"

    m["roic"] = fund.get("roic")
    m["margen_bruto"] = fund.get("margen_bruto")
    m["margen_operativo"] = fund.get("margen_operativo")
    m["roe"] = fund.get("roe")
    fcf_ttm, ingresos_ttm = fund.get("flujo_caja_libre"), fund.get("ingresos_ttm")
    m["margen_fcf"] = fcf_ttm / ingresos_ttm if es_dato(fcf_ttm) and es_dato(ingresos_ttm) and ingresos_ttm > 0 else None
    beneficio = serie(res, "Net Income", "Net Income Common Stockholders")
    if es_dato(fcf_ttm) and beneficio and beneficio[-1] > 0:
        m["calidad_beneficio"] = fcf_ttm / beneficio[-1]
    else:
        m["calidad_beneficio"] = None
        motivos["calidad_beneficio"] = "beneficio neto no positivo"

    # --- salud financiera
    deuda, caja, ebitda = fund.get("deuda_total"), fund.get("caja_total"), fund.get("ebitda")
    if financiera:
        for k in CALIDAD_METRICAS_NO_FINANCIERAS:
            m[k] = None
            motivos[k] = "no aplicable a financieras"
    else:
        if es_dato(deuda) and es_dato(ebitda) and ebitda > 0:
            m["deuda_neta_ebitda"] = (deuda - (caja or 0.0)) / ebitda
        else:
            m["deuda_neta_ebitda"] = None
            motivos["deuda_neta_ebitda"] = "EBITDA no positivo" if es_dato(ebitda) else "sin EBITDA"
        if es_dato(deuda) and deuda == 0:
            m["cobertura_intereses"] = CALIDAD_TRAMOS["cobertura_intereses"][-1][0]   # sin deuda: cobertura plena
        elif ebit and intereses and abs(intereses[-1]) > 0:
            m["cobertura_intereses"] = ebit[-1] / abs(intereses[-1])
        else:
            m["cobertura_intereses"] = None
            motivos["cobertura_intereses"] = "sin gasto por intereses informado"
        m["current_ratio"] = fund.get("current_ratio")
        m["deuda_patrimonio"] = fund.get("deuda_patrimonio")

    ventana = acciones[-(CALIDAD_ANIOS_CRECIMIENTO + 1):]
    if len(ventana) >= 2 and ventana[0] > 0:
        m["dilucion"] = ventana[-1] / ventana[0] - 1
    else:
        m["dilucion"] = None
        motivos["dilucion"] = "sin serie de acciones"
    ult = fcf[-CALIDAD_ANIOS_CRECIMIENTO:]
    m["fcf_positivo"] = sum(1 for v in ult if v > 0) / len(ult) if ult else None
    return m, motivos


def perfil(fund: dict) -> str:
    ttm, fwd = fund.get("bpa_ttm"), fund.get("bpa_forward")
    if (not es_dato(ttm) or ttm <= 0) and (not es_dato(fwd) or fwd <= 0):
        return PERFIL_PRE_RENTABILIDAD
    return PERFIL_RENTABLE


# ------------------------------------------------------------- puntuación ----
def _puntuar(clave: str, valor, sector: str | None) -> tuple[float | None, str | None]:
    """(puntos, referencia legible)."""
    if not es_dato(valor):
        return None, None
    if clave in CALIDAD_METRICAS_RELATIVAS:
        ref = REFERENCIAS_SECTOR[clave].get(sector) if sector else None
        if not es_dato(ref) or ref <= 0:
            return None, None
        return puntuar_tramos(valor / ref, CALIDAD_TRAMOS_RELATIVOS), f"sector {ref * 100:.0f} %"
    tramos = CALIDAD_TRAMOS[clave]
    if sector in sec.SECTORES_APALANCADOS and clave in CALIDAD_TRAMOS_APALANCADOS:
        tramos = CALIDAD_TRAMOS_APALANCADOS[clave]
        return puntuar_tramos(valor, tramos), "tramos sector apalancado"
    return puntuar_tramos(valor, tramos), None


def calcular(fund: dict, estados: dict | None) -> dict:
    sector = fund.get("sector")
    valores, motivos = metricas(fund, estados)
    bloques = {}
    for nombre, pesos in CALIDAD_BLOQUES.items():
        detalle = {}
        componentes = {}
        for clave, peso in pesos.items():
            puntos, referencia = _puntuar(clave, valores.get(clave), sector)
            if puntos is None and clave not in motivos:
                motivos[clave] = ("sin referencia sectorial" if clave in CALIDAD_METRICAS_RELATIVAS and es_dato(valores.get(clave))
                                  else "sin dato")
            detalle[clave] = {"etiqueta": ETIQUETAS[clave], "valor": valores.get(clave), "puntos": puntos,
                              "peso": peso, "referencia": referencia, "motivo": motivos.get(clave) if puntos is None else None}
            componentes[clave] = (peso, puntos)
        p = ponderar(componentes, motivos=motivos)
        bloques[nombre] = {"nota": p.valor, "cobertura": p.cobertura, "peso": sum(pesos.values()),
                           "metricas": detalle}

    total = ponderar({n: (b["peso"], b["nota"]) for n, b in bloques.items()}, cobertura_minima=CALIDAD_COBERTURA_MINIMA)
    # cobertura real sobre las 16 métricas, no sobre los 3 bloques
    peso_ok = sum(d["peso"] for b in bloques.values() for d in b["metricas"].values() if d["puntos"] is not None)
    return {
        "nota": total.valor,
        "cobertura": peso_ok / 100,
        "perfil": perfil(fund),
        "bloques": bloques,
        "excluidas": {k: v for k, v in motivos.items()},
        "version": MOTOR_VERSION,
    }
