"""Acceso a Finnhub (REST directo, sin SDK) con respaldo en Yahoo. Devuelve
`Dato` como la capa de yfinance: valor None y el MOTIVO en `fuente` cuando
no hay dato ("sin FINNHUB_KEY", "HTTP 403"...), para que la interfaz diga
qué ha fallado en vez de un genérico "no disponible".

Eficiencia: el calendario de resultados se pide UNA vez con una ventana que
cubre ~4 trimestres pasados y el próximo, así que EPS y revenue vs consenso,
racha de sorpresas y fecha del siguiente earnings salen de la misma llamada.

Los fallos no se cachean: la función cacheada lanza excepción cuando no
consigue datos y Streamlit nunca guarda un resultado que ha lanzado. Así una
key añadida después o un corte puntual no dejan el bloque vacío durante
horas. La hora de obtención viaja con el resultado cacheado para que el
indicador de frescura sea el real y no el del último rerun.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import requests
import streamlit as st

import config_secretos
from config_settings import (
    EARNINGS_DIAS_ADELANTE,
    EARNINGS_DIAS_ATRAS,
    NOTICIAS_DIAS,
    NOTICIAS_N,
    TTL_EARNINGS,
    TTL_NOTICIAS,
)
from datos_yfinance import Dato, obtener_earnings_yf, obtener_noticias_yf

_BASE = "https://finnhub.io/api/v1"
# Nombres alternativos con los que es fácil haber guardado la key en los
# Secrets de Streamlit; el canónico (FINNHUB_KEY) lo resuelve config_secretos.
_NOMBRES_KEY = ("FINNHUB_API_KEY", "FINNHUB_TOKEN", "finnhub_key", "finnhub_api_key", "finnhub_token")
_SECCIONES_KEY = ("finnhub", "FINNHUB")


class _SinDatos(Exception):
    """Motivo legible; se lanza dentro de la caché para no cachear el fallo."""


def _key() -> str | None:
    k = config_secretos.finnhub()
    if k:
        return k
    try:
        for nombre in _NOMBRES_KEY:
            if nombre in st.secrets:
                return str(st.secrets[nombre])
        for seccion in _SECCIONES_KEY:
            if seccion in st.secrets:
                sub = st.secrets[seccion]
                for nombre in ("key", "api_key", "token", "KEY", "API_KEY", "TOKEN"):
                    if nombre in sub:
                        return str(sub[nombre])
    except Exception:
        pass
    return None


def _get(ruta: str, **params) -> tuple[dict | list | None, str | None]:
    """(json, motivo de error). Motivo None si la petición fue bien."""
    key = _key()
    if not key:
        return None, "sin FINNHUB_KEY en los Secrets"
    try:
        r = requests.get(f"{_BASE}/{ruta}", params={**params, "token": key}, timeout=15)
        if r.status_code == 429:
            return None, "Finnhub: límite de peticiones (HTTP 429)"
        if r.status_code in (401, 403):
            return None, f"Finnhub: acceso denegado (HTTP {r.status_code}, key o plan)"
        if r.status_code != 200:
            return None, f"Finnhub: HTTP {r.status_code}"
        return r.json(), None
    except (requests.RequestException, ValueError) as e:
        return None, f"Finnhub: {type(e).__name__}"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ noticias --
@st.cache_data(ttl=TTL_NOTICIAS, show_spinner=False)
def _noticias(ticker: str) -> tuple[list[dict], str, datetime]:
    hoy = date.today()
    datos, error = _get("company-news", symbol=ticker,
                        **{"from": (hoy - timedelta(days=NOTICIAS_DIAS)).isoformat(), "to": hoy.isoformat()})
    if isinstance(datos, list) and datos:
        noticias, vistos = [], set()
        for n in sorted(datos, key=lambda x: x.get("datetime", 0), reverse=True):
            titular = (n.get("headline") or "").strip()
            if not titular or titular in vistos or not n.get("url"):
                continue
            vistos.add(titular)
            noticias.append({
                "fecha": datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc).date(),
                "titular": titular, "fuente": n.get("source") or "", "url": n["url"],
            })
            if len(noticias) >= NOTICIAS_N:
                break
        if noticias:
            return noticias, "finnhub", _ahora()
    respaldo = obtener_noticias_yf(ticker)
    if respaldo.ok:
        return respaldo.valor, "yfinance" + (f" (respaldo: {error})" if error else " (respaldo: Finnhub sin cobertura)"), _ahora()
    raise _SinDatos(error or "sin noticias en Finnhub ni en Yahoo")


def obtener_noticias(ticker: str) -> Dato:
    """Últimas N noticias: [{fecha, titular, fuente, url}], más reciente primero."""
    try:
        valor, fuente, cuando = _noticias(ticker)
        return Dato(valor, fuente, cuando)
    except Exception as e:
        return Dato(None, str(e) or "sin noticias", _ahora())


# ------------------------------------------------------------------ earnings --
def _pct(real, est):
    if real is None or est is None or est == 0:
        return None
    return (real - est) / abs(est) * 100


@st.cache_data(ttl=TTL_EARNINGS, show_spinner=False)
def _earnings(ticker: str) -> tuple[dict, str, datetime]:
    hoy = date.today()
    datos, error = _get("calendar/earnings", symbol=ticker,
                        **{"from": (hoy - timedelta(days=EARNINGS_DIAS_ATRAS)).isoformat(),
                           "to": (hoy + timedelta(days=EARNINGS_DIAS_ADELANTE)).isoformat()})
    filas = datos.get("earningsCalendar") if isinstance(datos, dict) else None
    if filas:
        pasados, proximo = [], None
        for f in sorted(filas, key=lambda x: x.get("date", ""), reverse=True):
            try:
                fecha = date.fromisoformat(f["date"])
            except (KeyError, ValueError):
                continue
            real = f.get("epsActual")
            if fecha >= hoy and real is None:
                proximo = {"fecha": fecha, "eps_est": f.get("epsEstimate"), "rev_est": f.get("revenueEstimate"),
                           "hora": f.get("hour")}
                continue
            if real is None:
                continue
            pasados.append({
                "fecha": fecha, "eps_real": real, "eps_est": f.get("epsEstimate"),
                "eps_sorpresa_pct": _pct(real, f.get("epsEstimate")),
                "rev_real": f.get("revenueActual"), "rev_est": f.get("revenueEstimate"),
                "rev_sorpresa_pct": _pct(f.get("revenueActual"), f.get("revenueEstimate")),
            })
        if pasados or proximo:
            return {"pasados": pasados[:4], "proximo": proximo}, "finnhub", _ahora()
    respaldo = obtener_earnings_yf(ticker)
    if respaldo.ok:
        return respaldo.valor, "yfinance" + (f" (respaldo: {error})" if error else " (respaldo: Finnhub sin cobertura)"), _ahora()
    raise _SinDatos(error or "sin calendario de resultados en Finnhub ni en Yahoo")


def obtener_earnings(ticker: str) -> Dato:
    """Calendario de resultados: {pasados: [...], proximo: {...}|None}.

    Cada elemento pasado: fecha, eps_real, eps_est, eps_sorpresa_pct,
    rev_real, rev_est, rev_sorpresa_pct. Ordenados del más reciente al más
    antiguo, limitados a EARNINGS_TRIMESTRES."""
    try:
        valor, fuente, cuando = _earnings(ticker)
        return Dato(valor, fuente, cuando)
    except Exception as e:
        return Dato(None, str(e) or "sin calendario de resultados", _ahora())
