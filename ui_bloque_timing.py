"""Tarjeta "Valoración del Timing y Señal de Entrada" (Bloque 5): nota
0-100 con barra, señal en cinco niveles, aviso de gate de calidad, las
cinco familias con su nota y, dentro de cada una, cada componente con
puntos, peso y motivo de exclusión si falta."""

from __future__ import annotations

import streamlit as st

import ui_componentes as ui
from config_settings import C_AMBAR, C_ROJO, C_TEXTO_TENUE, C_VERDE, CALIDAD_MINIMA_TIMING, TEXTO_ND
from core_ponderar import es_dato


def _color_nota(nota: float | None) -> str:
    if not es_dato(nota):
        return C_TEXTO_TENUE
    return C_VERDE if nota >= 65 else C_AMBAR if nota >= 45 else C_ROJO


def _barra(nota: float | None, color: str) -> str:
    ancho = max(0.0, min(100.0, nota)) if es_dato(nota) else 0.0
    return f'<div class="ss-barra"><div style="width:{ancho:.0f}%;background:{color}"></div></div>'


def _familia(nombre: str, f: dict) -> None:
    nota = f["nota"]
    color = _color_nota(nota)
    txt = ui.fmt_num(nota, 0) if es_dato(nota) else TEXTO_ND
    st.markdown(
        f'<div class="ss-metrica"><span>{nombre} <span class="ss-media-sector">peso {f["peso"]} %</span></span>'
        f'<span style="color:{color}">{txt}</span></div>{_barra(nota, color)}',
        unsafe_allow_html=True,
    )
    for d in f["componentes"].values():
        pts = d["puntos"]
        if pts is None:
            valor = f'<span class="ss-nd">{d["motivo"] or "sin dato"}</span>'
        else:
            valor = f'<span style="color:{_color_nota(pts)};font-weight:600">{pts:.0f}</span>'
        st.markdown(
            f'<div class="ss-metrica" style="font-size:.78rem;padding:.14rem 0 .14rem .8rem;border-bottom:0">'
            f'<span>{d["etiqueta"]} <span class="ss-media-sector">{d["peso"]} %</span></span><span>{valor}</span></div>',
            unsafe_allow_html=True,
        )


def render(a: dict) -> None:
    t = a.get("timing")
    with ui.tarjeta("Valoración del Timing y Señal de Entrada"):
        if not t or not es_dato(t.get("nota")):
            ui.nd("Timing no calculable: faltan indicadores o histórico suficiente.")
            return
        nota, senal = t["nota"], t["senal"]
        color = senal[1] if senal else _color_nota(nota)
        c_nota, c_senal = st.columns([1, 1.4])
        with c_nota:
            st.markdown('<div class="ss-etiqueta">Timing</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="ss-nota" style="color:{color}">{nota:.0f}<span style="font-size:1rem;color:{C_TEXTO_TENUE}"> / 100</span></div>',
                        unsafe_allow_html=True)
        with c_senal:
            st.markdown('<div class="ss-etiqueta">Señal de entrada</div>', unsafe_allow_html=True)
            if senal:
                ui.alerta(senal[0], senal[1])
        st.markdown(_barra(nota, color), unsafe_allow_html=True)
        if t.get("gate"):
            st.markdown(f'<div class="ss-anotacion">Nota bruta {t["nota_bruta"]:.0f}, topada en {nota:.0f}: '
                        f'la calidad no alcanza {CALIDAD_MINIMA_TIMING}. Buen timing en mala empresa es trading, '
                        f'no lo que busca esta app.</div>', unsafe_allow_html=True)
        cobertura = t.get("cobertura")
        if es_dato(cobertura) and cobertura < 1:
            st.markdown(f'<div class="ss-anotacion">Cobertura {cobertura * 100:.0f} %: el peso de los componentes '
                        f'sin dato se ha redistribuido.</div>', unsafe_allow_html=True)
        st.markdown("")
        for nombre, f in t["familias"].items():
            _familia(nombre, f)
