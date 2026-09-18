"""Acceso a Finnhub (REST directo, sin SDK) con respaldo en Yahoo. Devuelve
`Dato` como la capa de yfinance: valor None y el MOTIVO en `fuente` cuando
no hay dato ("sin FINNHUB_KEY", "HTTP 403"...), para que la interfaz diga
qué ha fallado en vez de un genérico "no disponible".

Resultados (sesión 6): el histórico de sorpresas sale de `/stock/earnings`
(gratuito; BPA real, estimado y sorpresa calculados por Finnhub, que es lo
que usa su propio widget) y el próximo earnings de `/calendar/earnings`; el
calendario, además, aporta los ingresos reales/estimados de los trimestres
que coincidan. El respaldo de Yahoo es POR CAMPO, no por bloque: si
Finnhub da el próximo earnings pero no el histórico, cada mitad se coge de
donde esté y se etiqueta su fuente. Antes la función retornaba con fuente
"finnhub" en cuanto el calendario traía una fila (aunque fuera solo la del
próximo, sin `epsActual`) y nunca probaba Yahoo: ese era el motivo del
"Resultados vs. consenso no disponibles (finnhub)".

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
    EARNINGS_TRIMESTRES,
    NOTICIAS_DIAS,
    NOTICIAS_N,
    TTL_EARNINGS,
    TTL_NOTICIAS,
    TTL_PEERS,
    TTL_RECOMENDACIONES,
)
from datos_yfinance import Dato, obtener_earnings_yf, obtener_noticias_yf, obtener_recomendaciones_yf

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


def _pasados_finnhub(ticker: str) -> tuple[list[dict], str | None]:
    """Trimestres pasados desde /stock/earnings: BPA real vs estimado con la
    sorpresa % ya calculada por Finnhub. Sin ingresos (el endpoint no los
    da). `fecha` es el CIERRE del trimestre fiscal (`period`), que es como
    se etiqueta el trimestre en pantalla; `anio`/`trimestre` sirven para
    casar los ingresos del calendario."""
    datos, error = _get("stock/earnings", symbol=ticker, limit=EARNINGS_TRIMESTRES + 2)
    if not isinstance(datos, list):
        return [], error
    pasados = []
    for f in datos:
        real = f.get("actual")
        try:
            fecha = date.fromisoformat(str(f.get("period"))[:10])
        except ValueError:
            continue
        if real is None:
            continue
        est = f.get("estimate")
        sorpresa = f.get("surprisePercent")
        pasados.append({
            "fecha": fecha, "eps_real": float(real), "eps_est": float(est) if est is not None else None,
            "eps_sorpresa_pct": float(sorpresa) if sorpresa is not None else _pct(real, est),
            "rev_real": None, "rev_est": None, "rev_sorpresa_pct": None,
            "anio": f.get("year"), "trimestre": f.get("quarter"),
        })
    pasados.sort(key=lambda x: x["fecha"], reverse=True)
    return pasados, error


def _calendario_finnhub(ticker: str) -> tuple[dict | None, list[dict], str | None]:
    """(próximo earnings, [ingresos reales/estimados de trimestres pasados
    con fecha de publicación y año/trimestre fiscal], error). Una sola
    llamada con ventana hacia atrás y adelante."""
    hoy = date.today()
    datos, error = _get("calendar/earnings", symbol=ticker,
                        **{"from": (hoy - timedelta(days=EARNINGS_DIAS_ATRAS)).isoformat(),
                           "to": (hoy + timedelta(days=EARNINGS_DIAS_ADELANTE)).isoformat()})
    filas = datos.get("earningsCalendar") if isinstance(datos, dict) else None
    proximo, ingresos = None, []
    for f in sorted(filas or [], key=lambda x: x.get("date", "")):
        try:
            fecha = date.fromisoformat(f["date"])
        except (KeyError, ValueError):
            continue
        if fecha >= hoy and f.get("epsActual") is None:
            if proximo is None:      # el más cercano
                proximo = {"fecha": fecha, "eps_est": f.get("epsEstimate"), "rev_est": f.get("revenueEstimate"),
                           "hora": f.get("hour"), "estimada": False}
        elif f.get("revenueActual") is not None or f.get("revenueEstimate") is not None:
            ingresos.append({"fecha": fecha, "rev_real": f.get("revenueActual"), "rev_est": f.get("revenueEstimate"),
                             "anio": f.get("year"), "trimestre": f.get("quarter")})
    return proximo, ingresos, error


@st.cache_data(ttl=TTL_EARNINGS, show_spinner=False)
def _earnings(ticker: str) -> tuple[dict, str, datetime]:
    pasados, err_p = _pasados_finnhub(ticker)
    proximo, ingresos, err_c = _calendario_finnhub(ticker)
    fuentes = {"pasados": "finnhub" if pasados else None, "proximo": "finnhub" if proximo else None}
    # Ingresos vs consenso: del calendario, casados por (año, trimestre)
    # fiscal y, si falta, por fecha (publicación entre 0 y 75 días después
    # del cierre del trimestre).
    for p in pasados:
        ing = next((i for i in ingresos if i["anio"] and (i["anio"], i["trimestre"]) == (p["anio"], p["trimestre"])), None) \
            or next((i for i in ingresos if 0 <= (i["fecha"] - p["fecha"]).days <= 75), None)
        if ing:
            p["rev_real"], p["rev_est"] = ing["rev_real"], ing["rev_est"]
            p["rev_sorpresa_pct"] = _pct(ing["rev_real"], ing["rev_est"])
    if not pasados or proximo is None:
        respaldo = obtener_earnings_yf(ticker)
        yf = respaldo.valor or {}
        if not pasados and yf.get("pasados"):
            pasados = yf["pasados"]
            fuentes["pasados"] = "yfinance"
        if proximo is None and yf.get("proximo"):
            proximo = yf["proximo"]
            fuentes["proximo"] = "yfinance"
    if not pasados and proximo is None:
        raise _SinDatos(err_p or err_c or "sin resultados en Finnhub ni en Yahoo")
    etiqueta = " · ".join(f"{k}: {v}" for k, v in fuentes.items() if v)
    return {"pasados": pasados[:EARNINGS_TRIMESTRES], "proximo": proximo, "fuentes": fuentes,
            "errores": {"finnhub": err_p or err_c}}, etiqueta, _ahora()


def obtener_earnings(ticker: str) -> Dato:
    """Resultados: {pasados: [...], proximo: {...}|None, fuentes: {pasados,
    proximo}}. Cada elemento pasado: fecha, eps_real, eps_est,
    eps_sorpresa_pct, rev_real, rev_est, rev_sorpresa_pct (más reciente
    primero, EARNINGS_TRIMESTRES). `proximo.estimada` marca una fecha aún no
    confirmada por la empresa (rango de Yahoo)."""
    try:
        valor, fuente, cuando = _earnings(ticker)
        return Dato(valor, fuente, cuando)
    except Exception as e:
        return Dato(None, str(e) or "sin calendario de resultados", _ahora())


# ------------------------------------------------------- recomendaciones --
@st.cache_data(ttl=TTL_RECOMENDACIONES, show_spinner=False)
def _recomendaciones(ticker: str) -> tuple[list[dict], str, datetime]:
    """Serie mensual de /stock/recommendation (gratuito): [{periodo,
    strongBuy, buy, hold, sell, strongSell}], más reciente primero."""
    datos, error = _get("stock/recommendation", symbol=ticker)
    serie = []
    if isinstance(datos, list):
        for f in datos:
            periodo = str(f.get("period") or "")[:10]
            if not periodo:
                continue
            serie.append({"periodo": periodo, **{k: int(f.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}})
    serie = [x for x in serie if sum(x[k] for k in ("strongBuy", "buy", "hold", "sell", "strongSell")) > 0]
    serie.sort(key=lambda x: x["periodo"], reverse=True)
    if serie:
        return serie, "finnhub", _ahora()
    respaldo = obtener_recomendaciones_yf(ticker)
    if respaldo.ok:
        return respaldo.valor, "yfinance" + (f" (respaldo: {error})" if error else " (respaldo: Finnhub sin cobertura)"), _ahora()
    raise _SinDatos(error or "sin recomendaciones en Finnhub ni en Yahoo")


def obtener_recomendaciones(ticker: str) -> Dato:
    """Distribución mensual de recomendaciones de analistas (ver core_analistas)."""
    try:
        valor, fuente, cuando = _recomendaciones(ticker)
        return Dato(valor, fuente, cuando)
    except Exception as e:
        return Dato(None, str(e) or "sin recomendaciones", _ahora())


# ------------------------------------------------------------------- peers --
@st.cache_data(ttl=TTL_PEERS, show_spinner=False)
def _peers(ticker: str) -> tuple[list[str], str, datetime]:
    """/stock/peers (gratuito): tickers del mismo país e industria, sin el
    propio. Sugerencia, no verdad (ver ui_bloque_peers)."""
    datos, error = _get("stock/peers", symbol=ticker)
    if isinstance(datos, list):
        peers = [str(p).upper() for p in datos if p and str(p).upper() != ticker.upper()]
        if peers:
            return peers, "finnhub", _ahora()
    raise _SinDatos(error or "Finnhub sin comparables para este ticker")


def obtener_peers(ticker: str) -> Dato:
    try:
        valor, fuente, cuando = _peers(ticker)
        return Dato(valor, fuente, cuando)
    except Exception as e:
        return Dato(None, str(e) or "sin comparables", _ahora())
