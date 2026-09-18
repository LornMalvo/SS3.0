"""Constituyentes de índices (sesión 6) para el rastreo nocturno.

Fuente: tablas de Wikipedia (config_settings.INDICES, varias páginas
candidatas por índice) leídas con pandas.read_html. Se elige la primera
tabla con al menos INDICES_MIN_CONSTITUYENTES filas y una columna de
ticker (Symbol / Ticker / Símbolo). El ticker se normaliza a Yahoo:
"BRK.B" -> "BRK-B", "(NYSE: MMM)" -> "MMM", y se añade el sufijo del índice
si el ticker no trae ninguno (IBEX -> .MC).

Se pide como mucho una vez cada INDICES_REFRESCO_DIAS (el cron guarda la
lista en `rastreador_indices` con fecha); la app nunca llama aquí.
"""

from __future__ import annotations

import io
import re

import pandas as pd
import requests

from config_settings import INDICES, INDICES_MIN_CONSTITUYENTES

_CABECERAS = {"User-Agent": "Mozilla/5.0 (StockScanner; rastreo nocturno)"}
_COLUMNAS_TICKER = ("symbol", "ticker", "símbolo", "simbolo", "kürzel")
_RE_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,9}")


def normalizar(bruto: str, sufijo: str) -> str | None:
    """"(NYSE: MMM)" -> "MMM"; "BRK.B" -> "BRK-B"; "ACS" + ".MC" -> "ACS.MC"."""
    txt = str(bruto or "").upper().strip()
    if ":" in txt:                       # "(NASDAQ: AAPL)"
        txt = txt.split(":")[-1]
    txt = txt.strip(" ()[]")
    m = _RE_TICKER.search(txt)
    if not m:
        return None
    t = m.group(0)
    if "." in t and not any(t.endswith(s) for s in (".MC", ".DE", ".PA", ".AS", ".MI", ".BR", ".HE", ".L", ".SW", ".F", ".IR", ".LS", ".VI")):
        t = t.replace(".", "-")          # clase de acción (BRK.B) en notación Yahoo
    if sufijo and "." not in t:
        t += sufijo
    return t


def _tabla_constituyentes(html: str) -> pd.DataFrame | None:
    try:
        tablas = pd.read_html(io.StringIO(html))
    except ValueError:
        return None
    for t in tablas:
        if len(t) < INDICES_MIN_CONSTITUYENTES:
            continue
        for c in t.columns:
            if any(k in str(c).lower() for k in _COLUMNAS_TICKER):
                return t.rename(columns={c: "ticker"})[["ticker"]]
    return None


def obtener_constituyentes(nombre: str) -> tuple[list[str], str | None]:
    """(tickers ordenados, motivo si falla). Recorre las páginas candidatas."""
    if nombre not in INDICES:
        return [], f"índice desconocido: {nombre}"
    urls, sufijo = INDICES[nombre]
    ultimo_error = None
    for url in urls:
        try:
            r = requests.get(url, headers=_CABECERAS, timeout=30)
        except requests.RequestException as e:
            ultimo_error = f"{type(e).__name__} en {url}"
            continue
        if r.status_code != 200:
            ultimo_error = f"HTTP {r.status_code} en {url}"
            continue
        tabla = _tabla_constituyentes(r.text)
        if tabla is None:
            ultimo_error = f"sin tabla de constituyentes en {url}"
            continue
        tickers = sorted({t for t in (normalizar(x, sufijo) for x in tabla["ticker"].tolist()) if t})
        if len(tickers) >= INDICES_MIN_CONSTITUYENTES:
            return tickers, None
        ultimo_error = f"solo {len(tickers)} tickers válidos en {url}"
    return [], ultimo_error
