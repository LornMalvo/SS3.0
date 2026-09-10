"""Análisis Individual. Distribución según el wireframe:

  [ campo ticker ][ Analizar ]
  etiqueta TICKER · Nombre -> Sector      Precio actual      [☆ Favorito]
  ┌ Contexto (1) ┐ ┌ Gráfico + MACD + fundamentales y técnicos (2) ┐
  └──────────────┘ └ Anotaciones manuales ─────────────────────────┘
  ┌ Calidad / FV ┐ ┌ Timing y señal ┐ ┌ Plan DCA y veredicto ┐

El resultado caro vive en `st.session_state["analisis"]` y solo se recalcula
al pulsar Analizar. Los cambios baratos (rango, toggle, estrella, nota)
provocan reruns que NO repiten peticiones: todo está cacheado o en
session_state.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import core_calidad
import core_fair_value
import core_fundamentales
import core_indicadores
import datos_finnhub
import datos_traduccion
import db_supabase
import ui_bloque_calidad_fv
import ui_componentes as ui
import ui_graficos
import ui_metricas
from config_settings import (
    DIAS_RANGO,
    EARNINGS_TRIMESTRES,
    MOTOR_VERSION,
    RANGO_GRAFICO_DEFECTO,
    RANGOS_GRAFICO,
    TEXTO_ND,
)
from core_ponderar import es_dato
from datos_cache import cubo_mercado
from datos_yfinance import (
    obtener_estados_financieros,
    obtener_historico,
    obtener_info,
    obtener_intradia,
    obtener_precio_actual,
)

CLAVE_ANALISIS = "analisis"
CLAVE_TICKER_PENDIENTE = "ticker_pendiente"   # lo rellena Favoritos/Rastreador


# ----------------------------------------------------------------- análisis --
def analizar(ticker: str) -> dict | None:
    """Ejecuta el análisis completo. Los motores (sesiones 2-3) añadirán sus
    claves aquí a partir de `fundamentales`, `estados` e `indicadores`."""
    ticker = ticker.strip().upper()
    if not ticker:
        return None
    cubo = cubo_mercado()
    historico = obtener_historico(ticker, cubo)
    if not historico.ok:
        return None
    info = obtener_info(ticker)
    estados = obtener_estados_financieros(ticker)
    precio = obtener_precio_actual(ticker)
    fund = core_fundamentales.extraer(info.valor, estados.valor)
    fund["divisa_cotizacion"] = (precio.valor or {}).get("divisa") or (info.valor or {}).get("currency")
    indicadores = core_indicadores.resumen(historico.valor)
    precio_ref = (precio.valor or {}).get("precio") or indicadores.get("precio")
    calidad = core_calidad.calcular(fund, estados.valor)
    fair_value = core_fair_value.calcular(fund, estados.valor, historico.valor, precio_ref, calidad["perfil"])
    a = {
        "ticker": ticker,
        "cubo": cubo,
        "historico": historico,
        "info": info,
        "estados": estados,
        "precio": precio,
        "noticias": datos_finnhub.obtener_noticias(ticker),
        "earnings": datos_finnhub.obtener_earnings(ticker),
        "fundamentales": fund,
        "indicadores": indicadores,
        "calidad": calidad,
        "fair_value": fair_value,
        "timing": None,        # sesión 3
        "plan": None,          # sesión 3
    }
    db_supabase.guardar_analisis(_fila_historico(a))
    return a


def _fila_historico(a: dict) -> dict:
    """Fila para `analisis_historico` (deduplicada por ticker/fecha/versión).
    `entradas` guarda los fundamentales crudos: con ellos y la versión del
    motor la nota es reconstruible."""
    from datetime import date
    fv, cal = a["fair_value"], a["calidad"]
    return {
        "ticker": a["ticker"],
        "fecha_analisis": date.today().isoformat(),
        "motor_version": MOTOR_VERSION,
        "precio": fv.get("precio"),
        "divisa": a["fundamentales"].get("divisa_cotizacion"),
        "calidad": cal.get("nota"),
        "fair_value": fv.get("fair_value"),
        "upside_pct": fv.get("upside_pct"),
        "perfil": cal.get("perfil"),
        "cobertura": {"calidad": cal.get("cobertura"), "fair_value": fv.get("cobertura")},
        "entradas": {k: v for k, v in a["fundamentales"].items() if isinstance(v, (int, float, str)) or v is None},
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
def _divisa(a: dict) -> str:
    return (a["precio"].valor or {}).get("divisa") or (a["info"].valor or {}).get("currency") or ""


def _cabecera(a: dict) -> None:
    info = a["info"].valor or {}
    precio = a["precio"].valor or {}
    ticker = a["ticker"]
    nombre = info.get("longName") or info.get("shortName") or TEXTO_ND
    sector = info.get("sector") or TEXTO_ND
    industria = info.get("industry")

    c_izq, c_precio, c_fav = st.columns([3, 2, 1.2])
    with c_izq:
        st.markdown('<div class="ss-etiqueta">Ticker analizado</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ss-ticker">{ticker}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ss-empresa">{ui.escapar(nombre)}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ss-sector">{sector}' + (f" · {industria}" if industria else "") + "</div>",
                    unsafe_allow_html=True)
    with c_precio:
        st.markdown('<div class="ss-etiqueta">Precio actual de cotización</div>', unsafe_allow_html=True)
        p = precio.get("precio") if precio else a["indicadores"].get("precio")
        var = precio.get("variacion_pct") if precio else None
        var_html = ""
        if es_dato(var):
            clase = "ss-var-pos" if var >= 0 else "ss-var-neg"
            var_html = f'<span class="ss-var {clase}">{ui.fmt_pct(var)}</span>'
        st.markdown(f'<div class="ss-precio">{ui.escapar(ui.fmt_precio(p, _divisa(a)))}{var_html}</div>',
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


# --------------------------------------------------------- bloque 2: contexto --
def _descripcion(a: dict) -> None:
    info = a["info"].valor or {}
    original = info.get("longBusinessSummary")
    if not original:
        ui.nd("Descripción no disponible")
        return
    traducida = datos_traduccion.traducir(a["ticker"], original)
    texto = traducida or original
    st.markdown(f'<div style="font-size:.84rem;line-height:1.5">{ui.escapar(texto)}</div>',
                unsafe_allow_html=True)
    if traducida is None:
        st.markdown('<div class="ss-anotacion">Traducción no disponible; se muestra el texto original.</div>',
                    unsafe_allow_html=True)


def _noticias(a: dict) -> None:
    st.markdown('<div class="ss-racha-tit">Últimas noticias</div>', unsafe_allow_html=True)
    noticias = a["noticias"].valor
    if not noticias:
        ui.nd("Sin noticias disponibles (Finnhub cubre principalmente valores de EE. UU.)")
        return
    for n in noticias:
        st.markdown(
            f'<div class="ss-noticia"><a href="{n["url"]}" target="_blank">{ui.escapar(n["titular"])}</a>'
            f'<br><small>{n["fecha"]:%d/%m/%Y} · {ui.escapar(n["fuente"])}</small></div>',
            unsafe_allow_html=True,
        )


def _earnings(a: dict) -> None:
    st.markdown('<div class="ss-racha-tit" style="margin-top:.6rem">Últimos resultados</div>',
                unsafe_allow_html=True)
    e = a["earnings"].valor
    divisa = a["fundamentales"].get("divisa")
    if not e or not e.get("pasados"):
        ui.nd("Resultados vs. consenso no disponibles")
    else:
        ultimo = e["pasados"][0]
        ui.metrica(f"BPA {ultimo['fecha']:%m/%Y}",
                   f"{ui.fmt_num(ultimo['eps_real'])} vs {ui.fmt_num(ultimo['eps_est'])}",
                   ui.fmt_pct(ultimo["eps_sorpresa_pct"]))
        ui.metrica("Ingresos",
                   f"{ui.fmt_importe(ultimo['rev_real'], divisa)} vs {ui.fmt_grande(ultimo['rev_est'])}",
                   ui.fmt_pct(ultimo["rev_sorpresa_pct"]))
        _racha(e["pasados"][:EARNINGS_TRIMESTRES])
    proximo = (e or {}).get("proximo")
    if proximo:
        eti = f"{proximo['fecha']:%d/%m/%Y}" + (f" ({proximo['hora']})" if proximo.get("hora") else "")
        ui.metrica("Próximo earnings", eti, f"BPA est. {ui.fmt_num(proximo.get('eps_est'))}")
    else:
        ui.metrica("Próximo earnings", TEXTO_ND)


def _racha(pasados: list[dict]) -> None:
    """Racha de sorpresas de BPA: verde si batió, rojo si falló."""
    filas = ['<div class="ss-racha"><div class="ss-racha-fila ss-racha-cab">'
             '<span>Trim.</span><span>Real</span><span>Est.</span><span>Sorpresa</span></div>']
    for p in pasados:
        s = p["eps_sorpresa_pct"]
        color = "#10b981" if es_dato(s) and s >= 0 else ("#dc2626" if es_dato(s) else "#64748b")
        filas.append(
            f'<div class="ss-racha-fila"><span>{p["fecha"]:%m/%Y}</span>'
            f'<span>{ui.fmt_num(p["eps_real"])}</span><span>{ui.fmt_num(p["eps_est"])}</span>'
            f'<span style="color:{color};font-weight:600">{ui.fmt_pct(s)}</span></div>'
        )
    filas.append("</div>")
    st.markdown("".join(filas), unsafe_allow_html=True)


def _bloque_contexto(a: dict) -> None:
    with ui.tarjeta("Descripción, noticias y últimos resultados"):
        _descripcion(a)
        st.markdown("")
        _noticias(a)
        _earnings(a)
        ui.frescura(a["noticias"].obtenido_en, "yfinance + finnhub", "noticias")


# ---------------------------------------------------------- bloque 3: gráfico --
def _serie_para_rango(a: dict, rango: str) -> tuple[pd.DataFrame, pd.Timestamp | None, bool]:
    """(serie completa, inicio del recorte, con_medias). 1M/1A/MAX recortan
    el histórico base ya en memoria; 1D/1S piden intradía (cacheado por cubo)
    y no llevan medias diarias."""
    df = a["historico"].valor
    spec = RANGOS_GRAFICO.get(rango)
    if spec is not None:
        intra = obtener_intradia(a["ticker"], spec[0], spec[1], a["cubo"])
        return (intra.valor, None, False) if intra.ok else (df, df.index[-1] - pd.Timedelta(days=7), True)
    if rango in DIAS_RANGO:
        return df, df.index[-1] - pd.Timedelta(days=DIAS_RANGO[rango]), True
    return df, None, True


def _bloque_grafico(a: dict) -> None:
    with ui.tarjeta("Gráfico de cotización · MACD · fundamentales y análisis técnico"):
        c_rango, c_toggle = st.columns([3, 1])
        with c_rango:
            rango = st.segmented_control("Rango", options=list(RANGOS_GRAFICO), key="rango_grafico",
                                         default=RANGO_GRAFICO_DEFECTO, label_visibility="collapsed")
        with c_toggle:
            mostrar_plan = st.toggle("Plan DCA", value=False, key="toggle_plan",
                                     disabled=a.get("plan") is None,
                                     help="Superpone entradas, salidas y stop del plan (sesión 3)")
        df, inicio, con_medias = _serie_para_rango(a, rango or RANGO_GRAFICO_DEFECTO)
        fig = ui_graficos.grafico_precio_macd(df, inicio, con_medias, a.get("plan"), mostrar_plan, _divisa(a))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.markdown('<div class="ss-anotacion">Pulsa en la leyenda para mostrar u ocultar velas, línea '
                    'y medias móviles.</div>', unsafe_allow_html=True)

        ui_metricas.render(a["fundamentales"], a["indicadores"])
        ui.frescura(a["info"].obtenido_en if a["info"].ok else None,
                    "yfinance (fundamentales: info + estados financieros)", "info")


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
                st.session_state[f"nota_guardada_{ticker}"] = db_supabase.guardar_anotacion(ticker, texto)
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
        ui_bloque_calidad_fv.render(a)
    with c5:
        _bloque_pendiente("Valoración del Timing y Señal de Entrada",
                          "Puntuación 0-100 en 5 familias y señal ENTRAR / ACUMULAR / VIGILAR / "
                          "ESPERAR / EVITAR.")
    with c6:
        _bloque_pendiente("Plan de inversión DCA y Valoración Final",
                          "Motor de confluencia (3 entradas, 3 salidas, stop sobre coste medio), "
                          "veredicto, narrativa, invalidación y botón «Guardar en Paper Trading».")
