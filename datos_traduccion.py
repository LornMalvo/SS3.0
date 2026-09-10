"""Traducción de la descripción de la empresa con deep-translator. Cacheada
por ticker con TTL largo (el texto apenas cambia). Si falla, devuelve None y
la vista muestra el original: nunca se bloquea el análisis por una traducción."""

from __future__ import annotations

import streamlit as st

from config_settings import TTL_TRADUCCION

_MAX_CARACTERES = 4800   # límite práctico del traductor gratuito por petición


@st.cache_data(ttl=TTL_TRADUCCION, show_spinner=False)
def traducir(ticker: str, texto: str, destino: str = "es") -> str | None:
    if not texto:
        return None
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target=destino).translate(texto[:_MAX_CARACTERES])
    except Exception:
        return None
