"""Tarjeta "Plan de inversión DCA y Valoración Final" (Bloque 6): veredicto
con vetos, tres entradas, tres salidas, stop sobre coste medio, riesgo /
beneficio, narrativa, condiciones de invalidación y botón para guardar el
plan en Paper Trading (estado inicial: vigilancia)."""

from __future__ import annotations

from datetime import date

import streamlit as st

import db_supabase
import ui_componentes as ui
from config_settings import (
    C_TEXTO_TENUE,
    MOTOR_VERSION,
    PLAN_COLOR_STOP,
    PLAN_COLORES_ENTRADA,
    PLAN_COLORES_SALIDA,
)
from core_ponderar import es_dato


def _nivel(n: dict, color: str, divisa: str) -> None:
    precio = ui.escapar(ui.fmt_precio(n["precio"], divisa))
    fuerza = "" if n.get("sintetico") else f' · fuerza {n["fuerza"]:.1f}' + (" (fuerte)" if n.get("fuerte") else "")
    st.markdown(
        f'<div class="ss-nivel" style="border-left:4px solid {color}"><span><b>{n["nivel"]}</b> · {n["peso"] * 100:.0f} %</span>'
        f'<span><b>{precio}</b> <span class="ss-media-sector">{ui.fmt_pct(n["dist_pct"])}</span></span></div>'
        f'<div class="ss-motivos">{", ".join(n["motivos"][:3])}{fuerza}</div>',
        unsafe_allow_html=True,
    )


def _fila_plan(a: dict) -> dict:
    """Fila para `paper_planes` (ver sql_migracion_001.sql)."""
    p, v = a["plan"], a["veredicto"]
    return {
        "ticker": a["ticker"],
        "motor_version": MOTOR_VERSION,
        "precio_ref": p["precio"],
        "divisa": a["fundamentales"].get("divisa_cotizacion"),
        "entradas": [{k: e[k] for k in ("nivel", "precio", "peso", "motivos", "sintetico")} for e in p["entradas"]],
        "salidas": [{k: s[k] for k in ("nivel", "precio", "peso", "motivos", "sintetico")} for s in p["salidas"]],
        "stop": p["stop"],
        "veredicto": v["etiqueta"],
        "narrativa": a.get("narrativa"),
        "invalidacion": a.get("invalidacion"),
    }


def render(a: dict) -> None:
    p, v = a.get("plan"), a.get("veredicto")
    divisa = a["fundamentales"].get("divisa_cotizacion") or ""
    with ui.tarjeta("Plan de inversión DCA y Valoración Final"):
        if v:
            st.markdown('<div class="ss-etiqueta">Veredicto</div>', unsafe_allow_html=True)
            ui.alerta(v["etiqueta"], v["color"])
            st.markdown(f'<div class="ss-anotacion">{ui.escapar(v["motivo"])}</div>', unsafe_allow_html=True)
        if not p:
            ui.nd("Plan no calculable: sin precio o sin histórico suficiente para las zonas de confluencia.")
            return

        st.markdown('<div class="ss-racha-tit" style="margin-top:.5rem">Entradas (DCA)</div>', unsafe_allow_html=True)
        for n, color in zip(p["entradas"], PLAN_COLORES_ENTRADA):
            _nivel(n, color, divisa)
        st.markdown('<div class="ss-racha-tit" style="margin-top:.4rem">Salidas</div>', unsafe_allow_html=True)
        for n, color in zip(p["salidas"], PLAN_COLORES_SALIDA):
            _nivel(n, color, divisa)

        st.markdown('<div class="ss-racha-tit" style="margin-top:.4rem">Stop y relación riesgo / beneficio</div>',
                    unsafe_allow_html=True)
        ui.metrica("Stop (sobre coste medio)", ui.fmt_precio(p["stop"], divisa),
                   f"riesgo {p['riesgo_pct']:.0f} %", semaforo=None)
        st.markdown(f'<div class="ss-motivos" style="color:{PLAN_COLOR_STOP}">{p["motivo_stop"]}</div>',
                    unsafe_allow_html=True)
        ui.metrica("Coste medio del plan", ui.fmt_precio(p["coste_medio"], divisa))
        ui.metrica("Salida media ponderada", ui.fmt_precio(p["salida_media"], divisa), f"+{p['beneficio_pct']:.0f} %")
        rb = p.get("ratio_br")
        ui.metrica("Beneficio / riesgo", f"{rb:.1f} : 1" if es_dato(rb) else ui.TEXTO_ND,
                   semaforo="bien" if es_dato(rb) and rb >= 2 else "mal" if es_dato(rb) and rb < 1 else None)

        if a.get("narrativa"):
            st.markdown('<div class="ss-racha-tit" style="margin-top:.5rem">Lectura</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="font-size:.82rem;line-height:1.5">{ui.escapar(a["narrativa"])}</div>',
                        unsafe_allow_html=True)

        if a.get("invalidacion"):
            if st.toggle("Condiciones de invalidación de la tesis", key=f"toggle_inval_{a['ticker']}"):
                for cond in a["invalidacion"]:
                    st.markdown(f'<div class="ss-metrica" style="font-size:.8rem"><span>{ui.escapar(cond["texto"])}</span></div>',
                                unsafe_allow_html=True)

        st.markdown("")
        _boton_guardar(a)


def _boton_guardar(a: dict) -> None:
    ticker = a["ticker"]
    clave_estado = f"plan_guardado_{ticker}"
    existente = db_supabase.plan_activo_para(ticker)
    if existente:
        st.caption(f"Ya hay un plan activo de {ticker} en Paper Trading (estado: {existente.get('estado')}). "
                   f"Guardar de nuevo crea otro plan.")
    if st.button("Guardar en Paper Trading", key=f"guardar_paper_{ticker}", type="primary", width="stretch",
                 icon=":material/science:"):
        plan_id = db_supabase.guardar_plan_paper(_fila_plan(a))
        st.session_state[clave_estado] = plan_id if plan_id is not None else False
        if plan_id is not None:
            db_supabase.registrar_decision(ticker, "guardar_plan", a["veredicto"]["motivo"] if a.get("veredicto") else "",
                                           plan_id if plan_id > 0 else None)
    estado = st.session_state.pop(clave_estado, None)
    if estado is None:
        return
    if estado is False:
        st.caption("No se pudo guardar el plan")
    else:
        st.caption("Plan guardado en Paper Trading (vigilancia)"
                   + ("" if db_supabase.disponible() else " — sin Supabase: solo en esta sesión"))
