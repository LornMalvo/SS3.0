"""Favoritos: lista con precios cargados en UNA descarga por lote y botón
Analizar que salta directamente al Análisis Individual ya calculado."""

from __future__ import annotations

import streamlit as st

import db_supabase
import ui_componentes as ui
import ui_interfaz
from datos_cache import cubo_mercado
from datos_yfinance import obtener_precios_lote


def render() -> None:
    favoritos = db_supabase.listar_favoritos()
    if not favoritos:
        with ui.tarjeta("Favoritos"):
            ui.pendiente("Todavía no hay favoritos. Marca la estrella en un análisis para añadirlo.")
        return

    lote = obtener_precios_lote(tuple(favoritos), cubo_mercado())
    precios = lote.valor or {}
    columnas = st.columns(3)
    for i, ticker in enumerate(favoritos):
        with columnas[i % 3]:
            with ui.tarjeta():
                p = precios.get(ticker, {})
                var = p.get("variacion_pct")
                clase = "ss-var-pos" if (var or 0) >= 0 else "ss-var-neg"
                st.markdown(
                    f'<div class="ss-mini-cab"><span class="ss-mini-tk">{ticker}</span>'
                    f'<span class="ss-var {clase}">{ui.fmt_pct(var)}</span></div>'
                    f'<div class="ss-mini-dest">{ui.escapar(ui.fmt_num(p.get("precio")))}</div>',
                    unsafe_allow_html=True,
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Analizar", key=f"fav_analizar_{ticker}", type="primary", width="stretch"):
                        st.session_state["ticker_pendiente"] = ticker
                        ui_interfaz.ir_a("Análisis Individual")
                        st.rerun()
                with c2:
                    if st.button("", key=f"fav_borrar_{ticker}", icon=":material/delete:", width="stretch",
                                 help="Quitar de Favoritos"):
                        db_supabase.alternar_favorito(ticker)
                        st.rerun()
    ui.frescura(lote.obtenido_en, lote.fuente, "precio")
