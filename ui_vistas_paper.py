"""Paper Trading. Sesión 3: listado de los planes guardados desde Análisis
Individual (solo lectura). La máquina de estados vigilancia → parcial_entrada
→ abierta → parcial_salida → cerrada (+ descartada), la ejecución de niveles
delegada en Cartera y el rendimiento simulado llegan en la sesión 4."""

from __future__ import annotations

import streamlit as st

import db_supabase
import ui_componentes as ui
import ui_interfaz
from config_settings import PAPER_ESTADOS


def _ficha(p: dict) -> None:
    estado = PAPER_ESTADOS.get(p.get("estado"), (p.get("estado"), "#64748b"))
    divisa = p.get("divisa") or ""
    entradas = ", ".join(f"{e['nivel']} {ui.fmt_num(e['precio'])}" for e in (p.get("entradas") or []))
    salidas = ", ".join(f"{s['nivel']} {ui.fmt_num(s['precio'])}" for s in (p.get("salidas") or []))
    with ui.tarjeta():
        st.markdown(
            f'<div class="ss-mini-cab"><span class="ss-mini-tk">{p.get("ticker")}</span>{ui.badge(*estado)}</div>'
            f'<div class="ss-mini-sub">Ref. {ui.escapar(ui.fmt_precio(p.get("precio_ref"), divisa))} · '
            f'{ui.escapar(p.get("veredicto") or "")} · {str(p.get("creado_en") or "")[:10]}</div>'
            f'<div class="ss-mini"><div class="ss-metrica"><span>Entradas</span><span>{entradas}</span></div>'
            f'<div class="ss-metrica"><span>Salidas</span><span>{salidas}</span></div>'
            f'<div class="ss-metrica"><span>Stop</span><span>{ui.fmt_num(p.get("stop"))}</span></div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Analizar", key=f"paper_analizar_{p.get('id')}", width="stretch"):
            st.session_state["ticker_pendiente"] = p.get("ticker")
            ui_interfaz.ir_a("Análisis Individual")
            st.rerun()


def render() -> None:
    planes = db_supabase.listar_planes_paper()
    if not planes:
        with ui.tarjeta("Paper Trading"):
            ui.pendiente("Todavía no hay planes guardados. Analiza un valor y pulsa «Guardar en Paper Trading» "
                         "para seguirlo aquí. El seguimiento de ejecuciones y el rendimiento simulado llegan en "
                         "la sesión 4.")
        return
    if not db_supabase.disponible():
        st.caption("Sin Supabase: los planes solo viven en esta sesión")
    columnas = st.columns(3)
    for i, p in enumerate(planes):
        with columnas[i % 3]:
            _ficha(p)
