"""Indicadores técnicos. Funciones puras sobre un DataFrame OHLCV con índice de
fechas (columnas Open, High, Low, Close, Volume). Sin estado ni caché: eso
vive en las capas de datos. Al ser puras, el backtesting puede llamarlas
sobre un histórico recortado a cualquier fecha.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config_settings import INDICADOR_VENTANAS, MACD_PARAMS, TIMING_VOLUMEN_SESIONES
from core_ponderar import es_dato

COLUMNAS = ("Open", "High", "Low", "Close", "Volume")


def _ultimo(serie: pd.Series) -> float | None:
    if serie is None or serie.empty:
        return None
    v = serie.dropna()
    if v.empty:
        return None
    return float(v.iloc[-1])


def media_movil(df: pd.DataFrame, ventana: int) -> pd.Series:
    return df["Close"].rolling(ventana, min_periods=ventana).mean()


def atr(df: pd.DataFrame, ventana: int = 14) -> pd.Series:
    """ATR clásico de Wilder (media exponencial con alpha = 1/n)."""
    h, l, c = df["High"], df["Low"], df["Close"]
    c_prev = c.shift(1)
    tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ventana, min_periods=ventana, adjust=False).mean()


def rsi(df: pd.DataFrame, ventana: int = 14) -> pd.Series:
    delta = df["Close"].diff()
    ganancia = delta.clip(lower=0).ewm(alpha=1 / ventana, min_periods=ventana, adjust=False).mean()
    perdida = (-delta.clip(upper=0)).ewm(alpha=1 / ventana, min_periods=ventana, adjust=False).mean()
    rs = ganancia / perdida.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(df: pd.DataFrame, rapida: int = MACD_PARAMS[0], lenta: int = MACD_PARAMS[1],
         senal: int = MACD_PARAMS[2]) -> pd.DataFrame:
    c = df["Close"]
    linea = c.ewm(span=rapida, adjust=False).mean() - c.ewm(span=lenta, adjust=False).mean()
    linea_senal = linea.ewm(span=senal, adjust=False).mean()
    return pd.DataFrame({"macd": linea, "senal": linea_senal, "hist": linea - linea_senal})


def obv(df: pd.DataFrame) -> pd.Series:
    signo = np.sign(df["Close"].diff()).fillna(0)
    return (signo * df["Volume"]).cumsum()


def adx(df: pd.DataFrame, ventana: int = 14) -> pd.DataFrame:
    """ADX con +DI/-DI (Wilder). Devuelve columnas adx, di_pos, di_neg."""
    h, l, c = df["High"], df["Low"], df["Close"]
    up = h.diff()
    down = -l.diff()
    dm_pos = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    dm_neg = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    alpha = 1 / ventana
    tr_s = tr.ewm(alpha=alpha, min_periods=ventana, adjust=False).mean()
    di_pos = 100 * dm_pos.ewm(alpha=alpha, min_periods=ventana, adjust=False).mean() / tr_s
    di_neg = 100 * dm_neg.ewm(alpha=alpha, min_periods=ventana, adjust=False).mean() / tr_s
    dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    return pd.DataFrame({
        "adx": dx.ewm(alpha=alpha, min_periods=ventana, adjust=False).mean(),
        "di_pos": di_pos,
        "di_neg": di_neg,
    })


def distancia_pct(precio: float | None, referencia: float | None) -> float | None:
    """% del precio respecto a la referencia (positivo = por encima)."""
    if not es_dato(precio) or not es_dato(referencia) or referencia == 0:
        return None
    return (float(precio) / float(referencia) - 1) * 100


def variacion_1a(df: pd.DataFrame) -> float | None:
    if df.empty:
        return None
    fecha = df.index[-1] - pd.Timedelta(days=365)
    previo = df.loc[:fecha]
    if previo.empty:
        return None
    return distancia_pct(df["Close"].iloc[-1], previo["Close"].iloc[-1])


def ath_atl(df: pd.DataFrame) -> tuple[float | None, float | None]:
    if df.empty:
        return None, None
    return float(df["High"].max()), float(df["Low"].min())


def extremos_52s(df: pd.DataFrame) -> tuple[float | None, float | None]:
    if df.empty:
        return None, None
    ultimo_anio = df.loc[df.index[-1] - pd.Timedelta(days=365):]
    return float(ultimo_anio["High"].max()), float(ultimo_anio["Low"].min())


def volumen_relativo(df: pd.DataFrame, sesiones: int = TIMING_VOLUMEN_SESIONES) -> float | None:
    """Volumen medio reciente / volumen medio de 3 meses (63 sesiones)."""
    if len(df) < 63:
        return None
    reciente = df["Volume"].iloc[-sesiones:].mean()
    base = df["Volume"].iloc[-63:].mean()
    if not es_dato(base) or base == 0:
        return None
    return float(reciente / base)


def pivotes(df: pd.DataFrame, ventana: int) -> tuple[pd.Series, pd.Series]:
    """Máximos/mínimos locales con `ventana` velas a cada lado (fractales).
    Devuelve (soportes, resistencias) como Series precio indexadas por fecha."""
    if len(df) < 2 * ventana + 1:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    h, l = df["High"], df["Low"]
    max_loc = h[(h == h.rolling(2 * ventana + 1, center=True).max())]
    min_loc = l[(l == l.rolling(2 * ventana + 1, center=True).min())]
    return min_loc.dropna(), max_loc.dropna()


def resumen(df: pd.DataFrame) -> dict[str, float | None]:
    """Panel de métricas del Bloque 3 y entradas crudas para Timing/Confluencia.
    Todo lo que no se pueda calcular sale como None (nunca 0)."""
    if df is None or df.empty:
        return {}
    v = INDICADOR_VENTANAS
    precio = _ultimo(df["Close"])
    m = macd(df)
    a = adx(df, v["adx"])
    mm50 = _ultimo(media_movil(df, v["mm50"]))
    mm100 = _ultimo(media_movil(df, v["mm100"]))
    mm200 = _ultimo(media_movil(df, v["mm200"]))
    atr14 = _ultimo(atr(df, v["atr"]))
    ath, atl = ath_atl(df)
    max52, min52 = extremos_52s(df)
    return {
        "precio": precio,
        "mm50": mm50, "mm100": mm100, "mm200": mm200,
        "dist_mm50": distancia_pct(precio, mm50),
        "dist_mm100": distancia_pct(precio, mm100),
        "dist_mm200": distancia_pct(precio, mm200),
        "atr": atr14,
        "atr_pct": (atr14 / precio * 100) if es_dato(atr14) and es_dato(precio) and precio else None,
        "rsi": _ultimo(rsi(df, v["rsi"])),
        "macd": _ultimo(m["macd"]), "macd_senal": _ultimo(m["senal"]), "macd_hist": _ultimo(m["hist"]),
        "obv": _ultimo(obv(df)),
        "adx": _ultimo(a["adx"]), "di_pos": _ultimo(a["di_pos"]), "di_neg": _ultimo(a["di_neg"]),
        "ath": ath, "atl": atl,
        "dist_ath": distancia_pct(precio, ath), "dist_atl": distancia_pct(precio, atl),
        "max_52s": max52, "min_52s": min52,
        "variacion_1a": variacion_1a(df),
        "volumen_relativo": volumen_relativo(df),
    }
