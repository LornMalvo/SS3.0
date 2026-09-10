"""Acceso a yfinance. Cada función devuelve un `Dato` con valor, fuente y hora
de obtención (la caché conserva ese sello, así que la interfaz puede
enseñar la frescura real). Un fallo devuelve valor None: nunca un cero ni
una excepción hacia arriba.

Reglas de eficiencia que se cumplen aquí:
- `st.cache_data` deduplica dentro de un ciclo de renderizado y entre reruns.
- El histórico diario se cachea por `cubo` de mercado (congelado en cierre).
- Rastreador y Favoritos usan `obtener_precios_lote` (una sola descarga).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st
import yfinance as yf

from config_settings import (
    CARTERA_DIVISA_BASE,
    CARTERA_DIVISAS_CONVERTIBLES,
    NOTICIAS_N,
    TTL_EARNINGS,
    TTL_ESTADOS_FINANCIEROS,
    TTL_FX,
    TTL_HISTORICO_RESPALDO,
    TTL_INFO,
    TTL_INTRADIA,
    TTL_LOTE,
    TTL_NOTICIAS,
    TTL_PRECIO,
)
from core_ponderar import es_dato


@dataclass(frozen=True)
class Dato:
    valor: Any
    fuente: str
    obtenido_en: datetime

    @property
    def ok(self) -> bool:
        return self.valor is not None


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _fast(fi, *claves):
    """Lee `fast_info` tolerando ambas convenciones de nombre (`lastPrice` en
    versiones recientes, `last_price` en anteriores). None si nada responde."""
    for clave in claves:
        try:
            v = fi[clave]
            if v is not None:
                return v
        except Exception:
            continue
    return None


def _normalizar(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    df = df.copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    columnas = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df[columnas].dropna(subset=["Close"])
    return df if not df.empty else None


@st.cache_data(ttl=TTL_HISTORICO_RESPALDO, show_spinner=False)
def obtener_historico(ticker: str, cubo: str) -> Dato:
    """Histórico diario completo ("max"). `cubo` no se usa dentro: está para
    que la clave de caché cambie con el calendario de mercado."""
    try:
        df = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=False)
        return Dato(_normalizar(df), "yfinance", _ahora())
    except Exception:
        return Dato(None, "yfinance", _ahora())


@st.cache_data(ttl=TTL_INTRADIA, show_spinner=False)
def obtener_intradia(ticker: str, periodo: str, intervalo: str, cubo: str) -> Dato:
    try:
        df = yf.Ticker(ticker).history(period=periodo, interval=intervalo, auto_adjust=False)
        return Dato(_normalizar(df), "yfinance", _ahora())
    except Exception:
        return Dato(None, "yfinance", _ahora())


@st.cache_data(ttl=TTL_INFO, show_spinner=False)
def obtener_info(ticker: str) -> Dato:
    """Fundamentales y perfil (`Ticker.info`). Es la petición más frágil
    frente al límite por IP de Yahoo; en la sesión 2 se respalda en Supabase
    (L2) para sobrevivir a los reinicios del contenedor."""
    try:
        info = yf.Ticker(ticker).info or {}
        if not info.get("regularMarketPrice") and not info.get("currentPrice") and not info.get("shortName"):
            return Dato(None, "yfinance", _ahora())
        return Dato(dict(info), "yfinance", _ahora())
    except Exception:
        return Dato(None, "yfinance", _ahora())


@st.cache_data(ttl=TTL_PRECIO, show_spinner=False)
def obtener_precio_actual(ticker: str) -> Dato:
    """Precio en vivo ligero (fast_info). Única pieza con frescura de minutos."""
    try:
        fi = yf.Ticker(ticker).fast_info
        precio = _fast(fi, "lastPrice", "last_price")
        previo = _fast(fi, "regularMarketPreviousClose", "previousClose", "previous_close")
        divisa = _fast(fi, "currency")
        if not es_dato(precio):
            return Dato(None, "yfinance", _ahora())
        variacion = (precio / previo - 1) * 100 if es_dato(previo) and previo else None
        return Dato({"precio": float(precio), "cierre_previo": previo, "variacion_pct": variacion,
                     "divisa": divisa}, "yfinance", _ahora())
    except Exception:
        return Dato(None, "yfinance", _ahora())


@st.cache_data(ttl=TTL_FX, show_spinner=False)
def obtener_fx(divisa: str) -> Dato:
    """Tipo de cambio `divisa` -> EUR."""
    if divisa == CARTERA_DIVISA_BASE:
        return Dato(1.0, "fijo", _ahora())
    try:
        par = f"{divisa}{CARTERA_DIVISA_BASE}=X"
        fi = yf.Ticker(par).fast_info
        v = _fast(fi, "lastPrice", "last_price")
        return Dato(float(v) if es_dato(v) else None, "yfinance", _ahora())
    except Exception:
        return Dato(None, "yfinance", _ahora())


def convertir_a_eur(importe: float | None, divisa: str | None) -> tuple[float | None, float | None]:
    """(importe en EUR, tipo aplicado). None si la divisa no es convertible:
    regla de oro, nunca mezclar divisas sin convertir."""
    if not es_dato(importe) or not divisa or divisa not in CARTERA_DIVISAS_CONVERTIBLES:
        return None, None
    fx = obtener_fx(divisa)
    if not fx.ok:
        return None, None
    return float(importe) * fx.valor, fx.valor


@st.cache_data(ttl=TTL_LOTE, show_spinner=False)
def obtener_precios_lote(tickers: tuple[str, ...], cubo: str) -> Dato:
    """Una sola descarga para N tickers (Rastreador, Favoritos). Devuelve
    dict ticker -> {precio, cierre_previo, variacion_pct}."""
    if not tickers:
        return Dato({}, "yfinance", _ahora())
    try:
        df = yf.download(list(tickers), period="5d", interval="1d", group_by="ticker",
                         auto_adjust=False, progress=False, threads=True)
        resultado: dict[str, dict] = {}
        for t in tickers:
            try:
                serie = (df[t]["Close"] if len(tickers) > 1 else df["Close"]).dropna()
            except Exception:
                continue
            if serie.empty:
                continue
            precio = float(serie.iloc[-1])
            previo = float(serie.iloc[-2]) if len(serie) > 1 else None
            resultado[t] = {
                "precio": precio,
                "cierre_previo": previo,
                "variacion_pct": (precio / previo - 1) * 100 if previo else None,
            }
        return Dato(resultado, "yfinance", _ahora())
    except Exception:
        return Dato({}, "yfinance", _ahora())


@st.cache_data(ttl=TTL_ESTADOS_FINANCIEROS, show_spinner=False)
def obtener_estados_financieros(ticker: str) -> Dato:
    """Cuenta de resultados, balance y flujo de caja anuales + cuenta
    trimestral. Solo cambian 4 veces al año: TTL de 48 h. Los usa el panel de
    fundamentales (ROIC, ingresos del último trimestre) y, después, el motor
    de Calidad, sin volver a pedirlos."""
    try:
        t = yf.Ticker(ticker)
        estados = {
            "resultados": t.income_stmt,
            "balance": t.balance_sheet,
            "flujo_caja": t.cashflow,
            "resultados_trim": t.quarterly_income_stmt,
        }
        if all(df is None or df.empty for df in estados.values()):
            return Dato(None, "yfinance", _ahora())
        return Dato(estados, "yfinance", _ahora())
    except Exception:
        return Dato(None, "yfinance", _ahora())


# --------------------------------------------- respaldo de Finnhub (Bloque 2) --
# Yahoo sirve noticias y calendario de resultados para cualquier mercado, no
# solo EE. UU.; Finnhub sigue siendo la fuente principal porque aporta los
# ingresos frente a consenso, que Yahoo no da para trimestres pasados.
@st.cache_data(ttl=TTL_NOTICIAS, show_spinner=False)
def obtener_noticias_yf(ticker: str) -> Dato:
    """Últimas N noticias en el mismo formato que datos_finnhub:
    [{fecha, titular, fuente, url}], más reciente primero."""
    try:
        crudas = yf.Ticker(ticker).news or []
    except Exception:
        return Dato(None, "yfinance", _ahora())
    noticias, vistos = [], set()
    for n in crudas:
        c = n.get("content") or n          # yfinance >= 0.2.50 anida en "content"
        titular = (c.get("title") or "").strip()
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or n.get("link"))
        if not titular or titular in vistos or not url:
            continue
        fecha_txt = c.get("pubDate") or c.get("displayTime")
        try:
            fecha = pd.Timestamp(fecha_txt).date() if fecha_txt else datetime.fromtimestamp(
                n.get("providerPublishTime", 0), tz=timezone.utc).date()
        except Exception:
            continue
        vistos.add(titular)
        noticias.append({"fecha": fecha, "titular": titular,
                         "fuente": (c.get("provider") or {}).get("displayName") or n.get("publisher") or "",
                         "url": url})
    noticias.sort(key=lambda x: x["fecha"], reverse=True)
    return Dato(noticias[:NOTICIAS_N] or None, "yfinance", _ahora())


@st.cache_data(ttl=TTL_EARNINGS, show_spinner=False)
def obtener_earnings_yf(ticker: str) -> Dato:
    """Calendario de resultados desde `earnings_dates` + `calendar`, en el
    formato de datos_finnhub. Sin ingresos reales por trimestre (Yahoo no los
    publica aquí): esas claves salen None y la vista las omite."""
    try:
        t = yf.Ticker(ticker)
        ed = t.get_earnings_dates(limit=12)
        cal = t.calendar or {}
    except Exception:
        return Dato(None, "yfinance", _ahora())
    if ed is None or ed.empty:
        return Dato(None, "yfinance", _ahora())
    hoy = pd.Timestamp.now(tz="UTC").date()
    pasados, futuros = [], []
    for fecha_ts, fila in ed.iterrows():
        fecha = fecha_ts.date()
        real, est = fila.get("Reported EPS"), fila.get("EPS Estimate")
        if es_dato(real):
            pasados.append({
                "fecha": fecha, "eps_real": float(real), "eps_est": float(est) if es_dato(est) else None,
                "eps_sorpresa_pct": (float(real) - float(est)) / abs(float(est)) * 100 if es_dato(est) and est else None,
                "rev_real": None, "rev_est": None, "rev_sorpresa_pct": None,
            })
        elif fecha >= hoy:
            futuros.append((fecha, float(est) if es_dato(est) else None))
    pasados.sort(key=lambda x: x["fecha"], reverse=True)
    proximo = None
    if futuros:
        fecha, est = min(futuros)
        rev = cal.get("Revenue Average")
        proximo = {"fecha": fecha, "eps_est": est, "rev_est": float(rev) if es_dato(rev) else None, "hora": None}
    if not pasados and proximo is None:
        return Dato(None, "yfinance", _ahora())
    return Dato({"pasados": pasados[:4], "proximo": proximo}, "yfinance", _ahora())
