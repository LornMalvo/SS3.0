"""Bloque 4 — Salud / Calidad Fundamental y Valor Objetivo.

Arriba: nota de Calidad con barra, cobertura y un desplegable por bloque con
cada métrica (puntos y peso primero en la etiqueta, que Streamlit trunca por
ancho). Abajo: alerta de valoración, fair value con upside, sensibilidad en
tres escenarios y tabla de métodos con su estado (usado / recortado /
excluido y por qué).
"""

from __future__ import annotations

import streamlit as st

import ui_componentes as ui
from config_settings import (
    C_AMBAR,
    C_NARANJA,
    C_ROJO,
    C_TEXTO_TENUE,
    C_VERDE,
    C_VERDE_OSCURO,
    CALIDAD_MINIMA_TIMING,
)
from core_ponderar import es_dato

_PCT = {"cagr_ingresos_3a", "cagr_bpa_3a", "consistencia_ingresos", "crecimiento_fcf", "roic", "margen_bruto",
        "margen_operativo", "margen_fcf", "roe", "dilucion", "fcf_positivo"}


def _color_nota(nota: float) -> str:
    if nota >= 75:
        return C_VERDE_OSCURO
    if nota >= CALIDAD_MINIMA_TIMING:
        return C_VERDE
    if nota >= 40:
        return C_AMBAR
    return C_ROJO


def _fmt_valor(clave: str, valor) -> str:
    if not es_dato(valor):
        return ui.TEXTO_ND
    if clave in _PCT:
        return ui.fmt_pct(valor * 100, signo=clave.startswith(("cagr", "crecimiento", "dilucion")))
    return ui.fmt_num(valor, 2)


def _barra(nota: float | None, color: str) -> None:
    ancho = 0 if not es_dato(nota) else max(0, min(100, nota))
    st.markdown(f'<div class="ss-barra"><div style="width:{ancho}%;background:{color}"></div></div>',
                unsafe_allow_html=True)


def _calidad(cal: dict) -> None:
    nota = cal.get("nota")
    color = _color_nota(nota) if es_dato(nota) else C_TEXTO_TENUE
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown('<div class="ss-etiqueta">Calidad fundamental</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ss-nota" style="color:{color}">{ui.fmt_num(nota, 0) if es_dato(nota) else "—"}'
                    f'<span style="font-size:.9rem;color:#64748b"> / 100</span></div>', unsafe_allow_html=True)
    with c2:
        st.markdown("<div style='height:.9rem'></div>", unsafe_allow_html=True)
        _barra(nota, color)
        st.markdown(f'<div class="ss-anotacion">Cobertura del modelo: {cal["cobertura"] * 100:.0f} % del peso · '
                    f'perfil {cal["perfil"].replace("_", "-")}</div>', unsafe_allow_html=True)
    if not es_dato(nota):
        ui.nd("Cobertura insuficiente para puntuar (menos de la mitad de las métricas con dato)")

    for nombre, b in cal["bloques"].items():
        etiqueta = (f"{ui.fmt_num(b['nota'], 0) if es_dato(b['nota']) else '—'} · {nombre} "
                    f"(peso {b['peso']}, cobertura {b['cobertura'] * 100:.0f} %)")
        with st.expander(etiqueta):
            for clave, m in b["metricas"].items():
                if m["puntos"] is None:
                    ui.metrica(f"{m['etiqueta']} · peso {m['peso']}", f"— · {m['motivo'] or 'sin dato'}")
                else:
                    ref = m["referencia"] or ""
                    ui.metrica(f"{m['etiqueta']} · peso {m['peso']}",
                               f"{ui.fmt_num(m['puntos'], 0)} pts · {_fmt_valor(clave, m['valor'])}", ref)


def _fair_value(fv: dict, divisa: str | None) -> None:
    st.markdown("<hr style='margin:.8rem 0;border:0;border-top:1px dashed #e2e8f0'>", unsafe_allow_html=True)
    st.markdown('<div class="ss-etiqueta">Valor objetivo (fair value)</div>', unsafe_allow_html=True)
    banda = fv.get("banda")
    if banda:
        ui.alerta(banda[0], banda[1] if not fv["anomalia"] else C_NARANJA)
    else:
        ui.nd("Valor objetivo no calculable con los datos disponibles")
    for aviso in fv.get("avisos", []):
        st.markdown(f'<div class="ss-anotacion" style="color:{C_NARANJA}">⚠ {aviso}</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        ui.metrica("Fair value", ui.fmt_precio(fv.get("fair_value"), divisa))
    with c2:
        ui.metrica("Upside vs precio", ui.fmt_pct(fv.get("upside_pct")))
    st.markdown(f'<div class="ss-anotacion">Cobertura de métodos: {fv["cobertura"] * 100:.0f} % del peso</div>',
                unsafe_allow_html=True)

    st.markdown('<div class="ss-racha-tit" style="margin-top:.5rem">Sensibilidad</div>', unsafe_allow_html=True)
    cols = st.columns(3)
    for col, (nombre, r) in zip(cols, fv["sensibilidad"].items()):
        with col:
            st.markdown(f'<div class="ss-mini-sub">{nombre.capitalize()}</div>'
                        f'<div class="ss-mini-dest" style="font-size:1.05rem">{ui.escapar(ui.fmt_precio(r["fair_value"], divisa, 2).split(" (")[0])}</div>'
                        f'<div class="ss-mini-sub">{ui.fmt_pct(r["upside_pct"])}</div>', unsafe_allow_html=True)

    with st.expander("Métodos y banda de cordura"):
        for k, m in fv["metodos"].items():
            estado = m["estado"]
            if estado == "excluido" or m["usado"] is None:
                ui.metrica(f"{m['etiqueta']} · peso {m['peso'] * 100:.0f} %", f"— · {m['motivo'] or 'sin dato'}")
                continue
            texto = ui.fmt_precio(m["usado"], divisa, 2).split(" (")[0]
            if estado == "recortado":
                texto += f" (recortado desde {ui.fmt_num(m['bruto'], 2)})"
            pe = f"efectivo {m['peso_efectivo'] * 100:.0f} %" if es_dato(m["peso_efectivo"]) else ""
            ui.metrica(f"{m['etiqueta']} · peso {m['peso'] * 100:.0f} %", texto, pe)


def render(a: dict) -> None:
    with ui.tarjeta("Salud / Calidad Fundamental y Valor Objetivo"):
        _calidad(a["calidad"])
        _fair_value(a["fair_value"], a["fundamentales"].get("divisa_cotizacion"))
        ui.frescura(a["estados"].obtenido_en if a["estados"].ok else None,
                    "yfinance (estados financieros) · referencias sectoriales semilla", "fundamentales")
