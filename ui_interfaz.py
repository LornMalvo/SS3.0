"""Estructura general: cabecera, navbar de 5 secciones y despacho de vistas.

Sigue el wireframe: logo centrado, navbar horizontal de píldoras debajo y el
contenido de la sección activa. Cada píldora es un st.button real; el
aspecto lo da la clase `.st-key-navbar_pildoras` que Streamlit asigna al
contenedor (ver ui_estilos.py).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

import ui_estilos
import ui_vistas_analisis
import ui_vistas_cartera
import ui_vistas_favoritos
import ui_vistas_paper
import ui_vistas_rastreador
from config_settings import APP_CLAIM, APP_NOMBRE, ICONOS_SECCION, SECCIONES

RUTA_LOGO = Path(__file__).resolve().parent / "logo.png"

VISTAS = {
    "Análisis Individual": ui_vistas_analisis.render,
    "Rastreador": ui_vistas_rastreador.render,
    "Gestión de Cartera": ui_vistas_cartera.render,
    "Paper Trading": ui_vistas_paper.render,
    "Favoritos": ui_vistas_favoritos.render,
}


@lru_cache(maxsize=1)
def _logo_base64() -> str | None:
    """Incrustado como <img> propio: st.image alinea a la izquierda de su
    columna y no permite centrarlo con precisión."""
    if not RUTA_LOGO.exists():
        return None
    return base64.b64encode(RUTA_LOGO.read_bytes()).decode("ascii")


def cabecera() -> None:
    logo = _logo_base64()
    if logo:
        st.markdown(
            f'<img class="ss-logo" src="data:image/png;base64,{logo}" alt="{APP_NOMBRE}">',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="text-align:center"><h2>{APP_NOMBRE}</h2><small>{APP_CLAIM}</small></div>',
            unsafe_allow_html=True,
        )


def ir_a(seccion: str) -> None:
    """Cambio de sección desde otra vista (p. ej. 'Analizar' en Favoritos)."""
    st.session_state["seccion"] = seccion


def navbar() -> str:
    if "seccion" not in st.session_state:
        st.session_state["seccion"] = SECCIONES[0]

    with st.container(key="navbar_pildoras"):
        columnas = st.columns(len(SECCIONES))
        for columna, seccion in zip(columnas, SECCIONES):
            activa = st.session_state["seccion"] == seccion
            with columna:
                if st.button(
                    seccion,
                    key=f"nav_{seccion}",
                    icon=f":material/{ICONOS_SECCION[seccion]}:",
                    width="stretch",
                    type="primary" if activa else "secondary",
                ):
                    st.session_state["seccion"] = seccion
                    st.rerun()
    st.write("")
    return st.session_state["seccion"]


def render() -> None:
    ui_estilos.aplicar()
    cabecera()
    seccion = navbar()
    VISTAS[seccion]()
