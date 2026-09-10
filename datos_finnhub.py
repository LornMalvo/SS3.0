"""Acceso a Finnhub (REST directo, sin SDK). Devuelve `Dato` como la capa de
yfinance. Sin API key o fuera de cobertura (Finnhub gratuito cubre sobre
todo valores de EE. UU.) el valor es None y la interfaz muestra "no
disponible", nunca un dato inventado.

Eficiencia: el calendario de resultados se pide UNA vez con una ventana que
cubre ~4 trimestres pasados y el próximo, así que EPS y revenue vs consenso,
racha de sorpresas y fecha del siguiente earnings salen de la misma llamada.
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
from datos_yfinance import Dato

_BASE = "https://finnhub.io/api/v1"


def _get(ruta: str, **params) -> dict | list | None:
    key = config_secretos.finnhub()
    if not key:
        return None
    try:
        r = requests.get(f"{_BASE}/{ruta}", params={**params, "token": key}, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@st.cache_data(ttl=TTL_NOTICIAS, show_spinner=False)
def obtener_noticias(ticker: str) -> Dato:
    """Últimas N noticias: [{fecha, titular, fuente, url}], más reciente primero."""
    hoy = date.today()
    datos = _get("company-news", symbol=ticker, **{"from": (hoy - timedelta(days=NOTICIAS_DIAS)).isoformat(),
                                                   "to": hoy.isoformat()})
    if not isinstance(datos, list):
        return Dato(None, "finnhub", _ahora())
    noticias = []
    vistos: set[str] = set()
    for n in sorted(datos, key=lambda x: x.get("datetime", 0), reverse=True):
        titular = (n.get("headline") or "").strip()
        if not titular or titular in vistos or not n.get("url"):
            continue
        vistos.add(titular)
        noticias.append({
            "fecha": datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc).date(),
            "titular": titular,
            "fuente": n.get("source") or "",
            "url": n["url"],
        })
        if len(noticias) >= NOTICIAS_N:
            break
    return Dato(noticias, "finnhub", _ahora())


@st.cache_data(ttl=TTL_EARNINGS, show_spinner=False)
def obtener_earnings(ticker: str) -> Dato:
    """Calendario de resultados: {pasados: [...], proximo: {...}|None}.

    Cada elemento pasado: fecha, eps_real, eps_est, eps_sorpresa_pct,
    rev_real, rev_est, rev_sorpresa_pct. Ordenados del más reciente al más
    antiguo, limitados a EARNINGS_TRIMESTRES."""
    hoy = date.today()
    datos = _get("calendar/earnings", symbol=ticker,
                 **{"from": (hoy - timedelta(days=EARNINGS_DIAS_ATRAS)).isoformat(),
                    "to": (hoy + timedelta(days=EARNINGS_DIAS_ADELANTE)).isoformat()})
    filas = (datos or {}).get("earningsCalendar") if isinstance(datos, dict) else None
    if not filas:
        return Dato(None, "finnhub", _ahora())

    def pct(real, est):
        if real is None or est is None or est == 0:
            return None
        return (real - est) / abs(est) * 100

    pasados, proximo = [], None
    for f in sorted(filas, key=lambda x: x.get("date", ""), reverse=True):
        try:
            fecha = date.fromisoformat(f["date"])
        except (KeyError, ValueError):
            continue
        real = f.get("epsActual")
        if fecha >= hoy and real is None:
            # el más cercano en el futuro es el próximo earnings
            proximo = {"fecha": fecha, "eps_est": f.get("epsEstimate"), "rev_est": f.get("revenueEstimate"),
                       "hora": f.get("hour")}
            continue
        if real is None:
            continue
        pasados.append({
            "fecha": fecha,
            "eps_real": real, "eps_est": f.get("epsEstimate"),
            "eps_sorpresa_pct": pct(real, f.get("epsEstimate")),
            "rev_real": f.get("revenueActual"), "rev_est": f.get("revenueEstimate"),
            "rev_sorpresa_pct": pct(f.get("revenueActual"), f.get("revenueEstimate")),
        })
    return Dato({"pasados": pasados[:4], "proximo": proximo}, "finnhub", _ahora())
