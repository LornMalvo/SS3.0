"""Traducción de la descripción de la empresa. Cacheada por ticker con TTL
largo (el texto apenas cambia). Si falla, devuelve None y la vista muestra
el original: nunca se bloquea el análisis por una traducción.

Por qué se trocea: deep-translator llama al endpoint móvil de Google con
una petición GET, y con descripciones largas (2.000-4.000 caracteres) la
URL supera el límite del servidor, que responde un HTML de "Error 500" que
la librería devolvía como si fuera la traducción. Se traduce por frases
agrupadas en bloques cortos y se valida cada respuesta; si un bloque falla
se prueba un segundo endpoint público (`translate_a/single`) que admite
POST. Los fallos NO se cachean: un error transitorio no debe congelar el
texto original durante dos días.
"""

from __future__ import annotations

import re

import requests
import streamlit as st

from config_settings import TTL_TRADUCCION

_BLOQUE_MAX = 1200                      # caracteres por petición al endpoint móvil
_MARCAS_ERROR = ("Error 500", "That’s an error", "That's an error", "Server Error")
_URL_RESPALDO = "https://translate.googleapis.com/translate_a/single"


class _FalloTraduccion(Exception):
    """Se lanza dentro de la función cacheada para que Streamlit NO cachee
    el resultado (las excepciones nunca se guardan en cache_data)."""


def _bloques(texto: str, maximo: int = _BLOQUE_MAX) -> list[str]:
    """Agrupa frases sin partir ninguna, hasta `maximo` caracteres."""
    frases = re.split(r"(?<=[.!?])\s+", texto.strip())
    bloques, actual = [], ""
    for f in frases:
        if actual and len(actual) + len(f) + 1 > maximo:
            bloques.append(actual)
            actual = f
        else:
            actual = f"{actual} {f}".strip()
    if actual:
        bloques.append(actual)
    return bloques


def _valida(original: str, traducido: str | None) -> bool:
    if not traducido or not isinstance(traducido, str):
        return False
    if any(m in traducido for m in _MARCAS_ERROR):
        return False
    # Una traducción real tiene una longitud del mismo orden que el original.
    return 0.3 * len(original) <= len(traducido) <= 3.0 * len(original)


def _traducir_deep(texto: str, destino: str) -> str | None:
    try:
        from deep_translator import GoogleTranslator
        r = GoogleTranslator(source="auto", target=destino).translate(texto)
        return r if _valida(texto, r) else None
    except Exception:
        return None


def _traducir_respaldo(texto: str, destino: str) -> str | None:
    """Endpoint público `translate_a/single` (cliente gtx) vía POST: sin
    límite práctico de longitud. Devuelve la unión de los segmentos."""
    try:
        r = requests.post(_URL_RESPALDO, params={"client": "gtx", "sl": "auto", "tl": destino, "dt": "t"},
                          data={"q": texto}, timeout=15)
        if r.status_code != 200:
            return None
        partes = r.json()[0]
        out = "".join(p[0] for p in partes if p and p[0])
        return out if _valida(texto, out) else None
    except Exception:
        return None


@st.cache_data(ttl=TTL_TRADUCCION, show_spinner=False)
def _traducir_cacheado(ticker: str, texto: str, destino: str) -> str:
    salida = []
    for bloque in _bloques(texto):
        t = _traducir_deep(bloque, destino) or _traducir_respaldo(bloque, destino)
        if t is None:
            raise _FalloTraduccion(bloque[:40])
        salida.append(t.strip())
    return " ".join(salida)


def traducir(ticker: str, texto: str, destino: str = "es") -> str | None:
    if not texto:
        return None
    try:
        return _traducir_cacheado(ticker, texto, destino)
    except Exception:
        return None
