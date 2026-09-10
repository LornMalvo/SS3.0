"""Convierte el `info` de yfinance y los estados financieros en un dict de
métricas con nombre propio y valor numérico o None. Es el ÚNICO sitio que
conoce las claves de yfinance: el panel del Bloque 3 y el motor de Calidad
consumen este dict, no el `info` crudo.

Convenciones: ratios y márgenes en tanto por uno; importes en la divisa de
los estados financieros (`divisa`); acciones en unidades.
"""

from __future__ import annotations

import pandas as pd

from core_ponderar import acotar, es_dato

_TIPO_IMPOSITIVO_DEFECTO = 0.21


def _num(valor) -> float | None:
    return float(valor) if es_dato(valor) else None


def _fila(df: pd.DataFrame | None, *nombres: str, columna: int = 0) -> float | None:
    """Primer valor no nulo de las filas candidatas en la columna (ejercicio)
    indicada. Los estados de yfinance vienen con las fechas como columnas,
    la más reciente primero."""
    if df is None or df.empty or df.shape[1] <= columna:
        return None
    for nombre in nombres:
        if nombre in df.index:
            v = df.loc[nombre].iloc[columna]
            if es_dato(v):
                return float(v)
    return None


def roic(estados: dict | None) -> float | None:
    """EBIT x (1 - tipo impositivo) / (deuda + patrimonio - caja). None si no
    hay EBIT o el capital invertido no es positivo."""
    if not estados:
        return None
    res, bal = estados.get("resultados"), estados.get("balance")
    ebit = _fila(res, "EBIT", "Operating Income")
    if ebit is None:
        return None
    pretax = _fila(res, "Pretax Income")
    impuestos = _fila(res, "Tax Provision")
    tipo = _TIPO_IMPOSITIVO_DEFECTO
    if pretax and impuestos is not None and pretax > 0:
        t = impuestos / pretax
        tipo = t if 0 <= t <= 0.45 else _TIPO_IMPOSITIVO_DEFECTO
    deuda = _fila(bal, "Total Debt")
    patrimonio = _fila(bal, "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
    caja = _fila(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments") or 0.0
    if deuda is None or patrimonio is None:
        return None
    invertido = deuda + patrimonio - caja
    if invertido <= 0:
        return None
    return acotar(ebit * (1 - tipo) / invertido, -1.0, 2.0)


def ingresos_ultimo_trimestre(estados: dict | None) -> tuple[float | None, str | None]:
    """(ingresos, etiqueta del trimestre) del último trimestre publicado."""
    if not estados:
        return None, None
    df = estados.get("resultados_trim")
    v = _fila(df, "Total Revenue", "Operating Revenue")
    if v is None:
        return None, None
    fecha = df.columns[0]
    etiqueta = fecha.strftime("%m/%Y") if hasattr(fecha, "strftime") else str(fecha)
    return v, etiqueta


def extraer(info: dict | None, estados: dict | None = None) -> dict:
    info = info or {}
    d2e = _num(info.get("debtToEquity"))
    return {
        "divisa": info.get("financialCurrency") or info.get("currency"),
        "sector": info.get("sector"),
        "industria": info.get("industry"),
        # tamaño
        "capitalizacion": _num(info.get("marketCap")),
        "acciones": _num(info.get("sharesOutstanding")),
        # valoración
        "per_trailing": _num(info.get("trailingPE")),
        "per_forward": _num(info.get("forwardPE")),
        "peg": _num(info.get("trailingPegRatio")) if es_dato(info.get("trailingPegRatio")) else _num(info.get("pegRatio")),
        "precio_ventas": _num(info.get("priceToSalesTrailing12Months")),
        "precio_valor_contable": _num(info.get("priceToBook")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "ev_ventas": _num(info.get("enterpriseToRevenue")),
        "valor_empresa": _num(info.get("enterpriseValue")),
        # rentabilidad
        "margen_neto": _num(info.get("profitMargins")),
        "margen_operativo": _num(info.get("operatingMargins")),
        "margen_ebitda": _num(info.get("ebitdaMargins")),
        "margen_bruto": _num(info.get("grossMargins")),
        "roe": _num(info.get("returnOnEquity")),
        "roa": _num(info.get("returnOnAssets")),
        "roic": roic(estados),
        # balance y caja
        "caja_total": _num(info.get("totalCash")),
        "deuda_total": _num(info.get("totalDebt")),
        "deuda_patrimonio": d2e / 100 if d2e is not None else None,   # yfinance lo da en %
        "current_ratio": _num(info.get("currentRatio")),
        "flujo_caja_operativo": _num(info.get("operatingCashflow")),
        "flujo_caja_libre": _num(info.get("freeCashflow")),
        "ebitda": _num(info.get("ebitda")),
        "ingresos_ttm": _num(info.get("totalRevenue")),
        # beneficio por acción
        "bpa_ttm": _num(info.get("trailingEps")),
        "bpa_forward": _num(info.get("forwardEps")),
        # mercado
        "volumen_medio_3m": _num(info.get("averageVolume")),
        "short_interest": _num(info.get("shortPercentOfFloat")),
        "short_ratio": _num(info.get("shortRatio")),
        "beta": _num(info.get("beta")),
        # analistas
        "n_analistas": _num(info.get("numberOfAnalystOpinions")),
        "objetivo_medio": _num(info.get("targetMeanPrice")),
        "objetivo_bajo": _num(info.get("targetLowPrice")),
        "objetivo_alto": _num(info.get("targetHighPrice")),
        "recomendacion": info.get("recommendationKey"),
    }
