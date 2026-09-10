"""Análisis Individual. Distribución según el wireframe:

  [ campo ticker ][ Analizar ]
  etiqueta TICKER · Nombre -> Sector      Precio actual      [☆ Favorito]
  ┌ Contexto (1) ┐ ┌ Gráfico + datos técnicos (2) ─────────┐
  └──────────────┘ └ Anotaciones manuales ─────────────────┘
  ┌ Calidad / FV ┐ ┌ Timing y señal ┐ ┌ Plan DCA y veredicto ┐

El resultado caro (histórico, info, indicadores) vive en
`st.session_state["analisis"]` y solo se recalcula al pulsar Analizar. Los
cambios baratos (rango del gráfico, toggle del plan, estrella, anotación)
provocan reruns que NO repiten peticiones: todo lo que leen está cacheado o
ya en session_state.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import core_indicadores
import db_supabase
import ui_componentes as ui
import ui_graficos
from config_settings import (
    C_AZUL,
    DIAS_RANGO,
    RANGO_GRAFICO_DEFECTO,
    RANGOS_GRAFICO,
    TEXTO_ND,
)
from core_ponderar import es_dato
from datos_cache import cubo_mercado
from datos_yfinance import obtener_historico, obtener_info, obtener_intradia, obtener_precio_actual

CLAVE_ANALISIS = "analisis"
CLAVE_TICKER_PENDIENTE = "ticker_pendiente"   # lo rellena Favoritos/Rastreador


# ----------------------------------------------------------------- análisis --
def analizar(ticker: str) -> dict | None:
    """Ejecuta el análisis completo y lo devuelve como dict serializable en
    session_state. Los motores (sesiones 2-3) añadirán sus claves aquí."""
    ticker = ticker.strip().upper()
    if not ticker:
        return None
    cubo = cubo_mercado()
    historico = obtener_historico(ticker, cubo)
    if not historico.ok:
        return None
    info = obtener_info(ticker)
    precio = obtener_precio_actual(ticker)
    df = historico.valor
    return {
        "ticker": ticker,
        "cubo": cubo,
        "historico": historico,
        "info": info,
        "precio": precio,
        "indicadores": core_indicadores.resumen(df),
        "calidad": None,       # sesión 2
        "fair_value": None,    # sesión 2
        "timing": None,        # sesión 3
        "plan": None,          # sesión 3
    }


def _formulario() -> None:
    pendiente = st.session_state.pop(CLAVE_TICKER_PENDIENTE, None)
    col_txt, col_btn = st.columns([5, 1])
    with col_txt:
        ticker = st.text_input("Ticker", value=pendiente or st.session_state.get("ticker_input", ""),
                               placeholder="Introduce el ticker (p. ej. AAPL, MELI, SAN.MC)",
                               label_visibility="collapsed", key="ticker_input")
    with col_btn:
        pulsado = st.button("Analizar", type="primary", width="stretch", icon=":material/query_stats:")

    if pulsado or pendiente:
        objetivo = pendiente or ticker
        with st.spinner(f"Analizando {objetivo.upper()}…"):
            resultado = analizar(objetivo)
        if resultado is None:
            st.error(f"No se ha podido obtener histórico para «{objetivo.upper()}». Revisa el ticker.")
            return
        st.session_state[CLAVE_ANALISIS] = resultado
        st.session_state.pop("rango_grafico", None)
        if pendiente:
            st.rerun()


# ----------------------------------------------------------------- cabecera --
def _cabecera(a: dict) -> None:
    info = a["info"].valor or {}
    precio = a["precio"].valor or {}
    ticker = a["ticker"]
    divisa = precio.get("divisa") or info.get("currency") or ""
    nombre = info.get("longName") or info.get("shortName") or TEXTO_ND
    sector = info.get("sector") or TEXTO_ND
    industria = info.get("industry")

    c_izq, c_precio, c_fav = st.columns([3, 2, 1.2])
    with c_izq:
        st.markdown('<div class="ss-etiqueta">Ticker analizado</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ss-ticker">{ticker}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ss-empresa">{ui.escapar(nombre)}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="ss-sector">{sector}' + (f" · {industria}" if industria else "") + "</div>",
            unsafe_allow_html=True,
        )
    with c_precio:
        st.markdown('<div class="ss-etiqueta">Precio actual de cotización</div>', unsafe_allow_html=True)
        p = precio.get("precio") if precio else a["indicadores"].get("precio")
        var = precio.get("variacion_pct") if precio else None
        if es_dato(var):
            clase = "ss-var-pos" if var >= 0 else "ss-var-neg"
            var_html = f'<span class="ss-var {clase}">{ui.fmt_pct(var)}</span>'
        else:
            var_html = ""
        st.markdown(f'<div class="ss-precio">{ui.escapar(ui.fmt_precio(p, divisa))}{var_html}</div>',
                    unsafe_allow_html=True)
        ui.frescura(a["precio"].obtenido_en if a["precio"].ok else None, a["precio"].fuente, "precio")
    with c_fav:
        es_fav = db_supabase.es_favorito(ticker)
        clave = "btn_favorito_on" if es_fav else "btn_favorito_off"
        if st.button("★" if es_fav else "☆", key=clave,
                     help="Quitar de Favoritos" if es_fav else "Añadir a Favoritos"):
            db_supabase.alternar_favorito(ticker)
            st.rerun()
        if not db_supabase.disponible():
            st.caption("Sin Supabase: favoritos solo en esta sesión")


# ----------------------------------------------------------------- bloques --
def _bloque_contexto(a: dict) -> None:
    info = a["info"].valor or {}
    with ui.tarjeta("Descripción, noticias y últimos resultados"):
        resumen = info.get("longBusinessSummary")
        if resumen:
            st.markdown(f'<div style="font-size:.85rem;line-height:1.5">{ui.escapar(resumen)}</div>',
                        unsafe_allow_html=True)
        else:
            ui.nd("Descripción no disponible")
        st.markdown("")
        for etiqueta, clave, fmt in (
            ("Capitalización", "marketCap", ui.fmt_grande),
            ("Empleados", "fullTimeEmployees", lambda v: ui.fmt_num(v, 0)),
            ("País", "country", lambda v: v or TEXTO_ND),
        ):
            ui.metrica(etiqueta, fmt(info.get(clave)))
        ui.pendiente("Noticias (5 últimas), earnings vs. consenso con racha de sorpresas y fecha del "
                     "próximo earnings: se conectan con Finnhub en la sesión 2. La descripción se "
                     "traducirá con deep-translator.")
        ui.frescura(a["info"].obtenido_en if a["info"].ok else None, a["info"].fuente, "info")


def _serie_para_rango(a: dict, rango: str):
    """1M/1A/MAX recortan el histórico base ya en memoria; 1D/1S piden
    intradía (cacheado por cubo)."""
    df = a["historico"].valor
    spec = RANGOS_GRAFICO.get(rango)
    if spec is not None:
        intra = obtener_intradia(a["ticker"], spec[0], spec[1], a["cubo"])
        return intra.valor if intra.ok else df.tail(5)
    if rango in DIAS_RANGO:
        return df.loc[df.index[-1] - pd.Timedelta(days=DIAS_RANGO[rango]):]
    return df


def _bloque_grafico(a: dict) -> None:
    ind = a["indicadores"]
    info = a["info"].valor or {}
    divisa = (a["precio"].valor or {}).get("divisa") or info.get("currency") or ""
    with ui.tarjeta("Gráfico de cotización · MACD · datos técnicos"):
        c_rango, c_toggle = st.columns([3, 1])
        with c_rango:
            rango = st.segmented_control("Rango", options=list(RANGOS_GRAFICO), key="rango_grafico",
                                         default=RANGO_GRAFICO_DEFECTO, label_visibility="collapsed")
        with c_toggle:
            mostrar_plan = st.toggle("Plan DCA", value=False, key="toggle_plan",
                                     disabled=a.get("plan") is None,
                                     help="Superpone entradas, salidas y stop del plan (disponible en la sesión 3)")
        df = _serie_para_rango(a, rango or RANGO_GRAFICO_DEFECTO)
        st.plotly_chart(ui_graficos.grafico_precio_macd(df, a.get("plan"), mostrar_plan, divisa),
                        width="stretch", config={"displayModeBar": False})

        c1, c2, c3 = st.columns(3)
        with c1:
            ui.metrica("MM50", ui.fmt_num(ind.get("mm50")), ui.fmt_pct(ind.get("dist_mm50")))
            ui.metrica("MM100", ui.fmt_num(ind.get("mm100")), ui.fmt_pct(ind.get("dist_mm100")))
            ui.metrica("MM200", ui.fmt_num(ind.get("mm200")), ui.fmt_pct(ind.get("dist_mm200")))
        with c2:
            ui.metrica("ATR (14)", ui.fmt_num(ind.get("atr")), ui.fmt_pct(ind.get("atr_pct"), signo=False))
            ui.metrica("OBV", ui.fmt_grande(ind.get("obv")))
            ui.metrica("ADX (14)", ui.fmt_num(ind.get("adx"), 1))
        with c3:
            ui.metrica("Short interest", ui.fmt_pct(
                info.get("shortPercentOfFloat") * 100 if es_dato(info.get("shortPercentOfFloat")) else None,
                signo=False))
            ui.metrica("Short ratio", ui.fmt_num(info.get("shortRatio"), 1))
            ui.metrica("Beta", ui.fmt_num(info.get("beta")))
        ui.frescura(a["historico"].obtenido_en, a["historico"].fuente, "historico")


def _bloque_anotaciones(a: dict) -> None:
    ticker = a["ticker"]
    with ui.tarjeta("Anotaciones manuales"):
        clave_texto = f"anotacion_{ticker}"
        if clave_texto not in st.session_state:
            st.session_state[clave_texto] = db_supabase.leer_anotacion(ticker)
        texto = st.text_area("Notas", key=clave_texto, height=110, label_visibility="collapsed",
                             placeholder="Ideas, tesis, dudas sobre este valor…")
        c_btn, c_msg = st.columns([1, 3])
        with c_btn:
            if st.button("Guardar nota", key=f"guardar_nota_{ticker}", width="stretch"):
                if db_supabase.guardar_anotacion(ticker, texto):
                    st.session_state[f"nota_guardada_{ticker}"] = True
                else:
                    st.session_state[f"nota_guardada_{ticker}"] = False
        with c_msg:
            estado = st.session_state.pop(f"nota_guardada_{ticker}", None)
            if estado is True:
                st.caption("Nota guardada" + ("" if db_supabase.disponible() else " (solo en esta sesión)"))
            elif estado is False:
                st.caption("No se pudo guardar la nota")


def _bloque_pendiente(titulo: str, detalle: str) -> None:
    with ui.tarjeta(titulo):
        ui.pendiente(detalle)


# ------------------------------------------------------------------- render --
def render() -> None:
    _formulario()
    a = st.session_state.get(CLAVE_ANALISIS)
    if not a:
        return

    _cabecera(a)
    st.markdown("")

    col_ctx, col_graf = st.columns([1, 2])
    with col_ctx:
        _bloque_contexto(a)
    with col_graf:
        _bloque_grafico(a)
        _bloque_anotaciones(a)

    c4, c5, c6 = st.columns(3)
    with c4:
        _bloque_pendiente("Salud / Calidad Fundamental y Valor Objetivo",
                          "Motor de Calidad 0-100 (3 bloques) y Fair Value por múltiplos con "
                          "sensibilidad y bandas de alerta. Sesión 2.")
    with c5:
        _bloque_pendiente("Valoración del Timing y Señal de Entrada",
                          "Puntuación 0-100 en 5 familias y señal ENTRAR / ACUMULAR / VIGILAR / "
                          "ESPERAR / EVITAR. Sesión 3.")
    with c6:
        _bloque_pendiente("Plan de inversión DCA y Valoración Final",
                          "Motor de confluencia (3 entradas, 3 salidas, stop sobre coste medio), "
                          "veredicto, narrativa, invalidación y botón «Guardar en Paper Trading». Sesión 3.")
