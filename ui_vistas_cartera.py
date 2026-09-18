"""Gestión de Cartera (sesión 4). Libro de operaciones reales con coste
medio ponderado en la ficha y FIFO en el realizado, comisiones, divisa base
EUR, rendimiento frente al benchmark y riesgo (concentración, sectores,
correlación).

Datos de mercado: UNA descarga por lote (`obtener_cierres_eur_lote`) trae
cierres de un año de todos los tickers, del benchmark y de los pares FX, ya
en EUR; de ahí salen el precio actual, la curva y la correlación. La divisa
de cada ticker se resuelve por sufijo (sin petición). El sector solo se pide
(cacheado) cuando se abre el bloque de riesgo.

Cada ficha lleva la RECOMENDACIÓN del motor sobre la posición (AMPLIAR,
MANTENER, ESPERAR, VENTA PARCIAL, REDUCIR, VENDER: core_cartera.recomendar,
matriz latente x momentum con el último veredicto guardado como veto) y la
variación de la sesión en % y en EUR.

Distribución:
  [ Resumen: valor · coste · latente · realizado · retorno ]
  [ toggle Registrar operación ]  -> formulario
  [ fichas de posiciones abiertas, 3 columnas, con Analizar y papelera ]
  [ toggle Rendimiento vs SPY ] [ toggle Riesgo ] [ toggle Libro ] [ cerradas ]
  (rendimiento y riesgo abiertos por defecto)
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import core_cartera
import db_supabase
import ui_componentes as ui
import ui_graficos
import ui_interfaz
from config_settings import (
    BENCHMARK,
    C_NARANJA,
    C_TEXTO_TENUE,
    CARTERA_COMISION_DEFECTO,
    CARTERA_CORRELACION_ALTA,
    CARTERA_DIVISAS_CONVERTIBLES,
    CARTERA_HISTORICO_DIAS,
    CARTERA_PESO_ALERTA,
    CARTERA_SECTOR_ALERTA,
    TEXTO_ND,
)
from core_ponderar import es_dato
from datos_cache import cubo_mercado
from datos_yfinance import fx_en_fecha, obtener_cierres_eur_lote, obtener_divisa, obtener_info

ORIGEN = "real"


# ------------------------------------------------------------------ helpers --
def _eur(v, decimales: int = 2) -> str:
    return ui.fmt_precio(v, "EUR", decimales)


def _sem(v) -> str | None:
    return "bien" if es_dato(v) and v > 0 else "mal" if es_dato(v) and v < 0 else None


def _acc(v) -> str:
    """Acciones sin ceros de relleno (12 en vez de 12,0000; 0,5 se queda)."""
    return ui.fmt_num(v, 4).rstrip("0").rstrip(",") if es_dato(v) else TEXTO_ND


def _mercado(tickers: list[str], operaciones: list[dict]):
    """Precios en EUR, cierres y benchmark para la cartera en una descarga.
    La ventana arranca en la operación más antigua (o hace un año si todas
    son más recientes): así la curva y la cartera sombra parten de las
    compras reales, no de un punto arbitrario."""
    if not tickers:
        return None
    divisas = tuple(obtener_divisa(t) for t in tickers)
    primera = min(pd.Timestamp(o["fecha"]).date() for o in operaciones) if operaciones else date.today()
    desde = min(primera, date.today() - timedelta(days=CARTERA_HISTORICO_DIAS)) - timedelta(days=7)
    return obtener_cierres_eur_lote(tuple(tickers), divisas, desde.isoformat(), cubo_mercado())


def _cifra(col, etiqueta: str, valor: str, semaforo: str | None = None, nota: str | None = None) -> None:
    color = ui.COLOR_SEMAFORO.get(semaforo or "", "inherit")
    with col:
        st.markdown(
            f'<div class="ss-etiqueta">{etiqueta}</div>'
            f'<div class="ss-mini-dest" style="color:{color}">{ui.escapar(valor)}</div>'
            + (f'<div class="ss-mini-sub">{ui.escapar(nota)}</div>' if nota else ""),
            unsafe_allow_html=True,
        )


# ------------------------------------------------------------------ resumen --
def _resumen(r: dict, mercado) -> None:
    with ui.tarjeta("Resumen de la cartera"):
        c1, c2, c3, c4, c5 = st.columns(5)
        _cifra(c1, "Valor actual", _eur(r["valor_eur"]) if es_dato(r["valor_eur"]) else TEXTO_ND,
               nota=f'{r["n_abiertas"]} posiciones abiertas'
                    + (f' · {r["n_sin_precio"]} sin precio' if r["n_sin_precio"] else ""))
        _cifra(c2, "Coste (ponderado)", _eur(r["coste_eur"]), nota=f'comisiones {_eur(r["comisiones_eur"])}')
        _cifra(c3, "Latente", _eur(r["latente_eur"]) if es_dato(r["latente_eur"]) else TEXTO_ND,
               _sem(r["latente_eur"]), ui.fmt_pct(r["latente_pct"]))
        _cifra(c4, "Realizado (FIFO)", _eur(r["realizado_eur"]), _sem(r["realizado_eur"]),
               f'{r["n_cerradas"]} posiciones cerradas')
        _cifra(c5, "Retorno total", ui.fmt_pct(r["retorno_total_pct"]), _sem(r["retorno_total_pct"]),
               f'sobre {_eur(r["invertido_eur"], 0)} invertidos')
        if mercado is not None:
            ui.frescura(mercado.obtenido_en, mercado.fuente, "precio")


# --------------------------------------------------------------- formulario --
def _formulario(operaciones: list[dict]) -> None:
    with ui.tarjeta("Registrar operación"):
        with st.form("form_operacion", clear_on_submit=False, border=False):
            c1, c2, c3, c4 = st.columns([1.4, 1, 1, 1])
            ticker = c1.text_input("Ticker", placeholder="AAPL, SAN.MC…").strip().upper()
            tipo = c2.selectbox("Tipo", ["compra", "venta"], format_func=str.capitalize)
            fecha = c3.date_input("Fecha", value=date.today(), max_value=date.today(), format="DD/MM/YYYY")
            acciones = c4.number_input("Acciones", min_value=0.0, step=1.0, format="%.4f")
            c5, c6, c7, c8 = st.columns([1, 1, 1, 1.4])
            precio = c5.number_input("Precio por acción", min_value=0.0, step=0.01, format="%.4f")
            divisa = c6.selectbox("Divisa del precio", list(CARTERA_DIVISAS_CONVERTIBLES),
                                  help="Trade Republic liquida en EUR: si copias el precio del bróker, deja EUR.")
            comision = c7.number_input("Comisión (€)", min_value=0.0, value=CARTERA_COMISION_DEFECTO, step=0.5)
            nota = c8.text_input("Nota", placeholder="opcional")
            enviado = st.form_submit_button("Registrar", type="primary", icon=":material/add:")

        if not enviado:
            return
        if not ticker or acciones <= 0 or precio <= 0:
            st.error("Ticker, acciones y precio son obligatorios (y mayores que cero).")
            return
        if tipo == "venta":
            disponibles = core_cartera.disponibles(operaciones, ticker)
            if acciones > disponibles + 1e-9:
                st.error(f"No puedes vender {_acc(acciones)} acciones de {ticker}: tienes {_acc(disponibles)}.")
                return
        # Precio en otra divisa: se convierte con el tipo del DÍA de la
        # operación (lo que de verdad se pagó en EUR), no con el de hoy.
        fx, origen_fx = fx_en_fecha(divisa, fecha, cubo_mercado())
        if not es_dato(fx):
            st.error(f"No hay tipo de cambio {divisa}/EUR: inténtalo de nuevo en unos minutos.")
            return
        precio_eur = float(precio) * fx
        op_id = db_supabase.insertar_operacion({
            "ticker": ticker, "tipo": tipo, "fecha": fecha.isoformat(), "acciones": float(acciones),
            "precio_eur": float(precio_eur), "comision_eur": float(comision), "origen": ORIGEN,
            "nota": nota or None, "divisa": divisa, "precio_origen": float(precio), "fx_aplicado": fx,
        })
        if op_id is None:
            st.error("No se pudo registrar la operación.")
            return
        if divisa != "EUR" and origen_fx == "actual":
            st.session_state["cart_aviso"] = (f"Sin histórico del par {divisa}/EUR para esa fecha: se ha aplicado "
                                              f"el tipo actual ({ui.fmt_num(fx, 4)}).")
        st.rerun()


# ---------------------------------------------------------------- fichas ----
def _ficha(p: dict) -> None:
    t = p["ticker"]
    peso = p.get("peso_pct")
    badge = ui.badge(f"{peso:.0f} % cartera", C_NARANJA if p.get("peso_alto") else C_TEXTO_TENUE) if es_dato(peso) else ""
    color_lat = ui.COLOR_SEMAFORO.get(_sem(p.get("latente_eur")) or "", "inherit")
    valor = _eur(p["valor_eur"]) if es_dato(p.get("valor_eur")) else TEXTO_ND
    reco, mom = p.get("recomendacion"), p.get("momentum")
    if reco:
        reco_html = (f'<div class="ss-reco" style="background:{reco["color"]}">{reco["etiqueta"]}</div>'
                     f'<div class="ss-reco-motivo">{ui.escapar(reco["motivo"])}'
                     + (f' · momentum {mom["nota"]:.0f}/100' if mom else "") + "</div>")
    else:
        reco_html = '<div class="ss-reco-motivo">Sin recomendación: falta precio o histórico para el momentum.</div>'
    # Variación de la sesión: % del valor en su divisa y EUR ganados/perdidos hoy.
    vd_pct, vd_eur = p.get("var_dia_pct"), p.get("var_dia_eur")
    color_dia = ui.COLOR_SEMAFORO.get(_sem(vd_pct) or "", "inherit")
    hoy = (f'<span style="color:{color_dia};font-weight:700">{ui.fmt_pct(vd_pct)}'
           + (f' · {ui.escapar(_eur(vd_eur))}' if es_dato(vd_eur) else "") + "</span>") if es_dato(vd_pct) else TEXTO_ND
    with ui.tarjeta():
        st.markdown(
            f'<div class="ss-mini-cab"><span class="ss-mini-tk">{t}</span>{badge}</div>'
            + reco_html +
            f'<div class="ss-mini-dest">{ui.escapar(valor)}</div>'
            f'<div class="ss-mini-sub" style="color:{color_lat};font-weight:600">'
            f'{ui.escapar(_eur(p.get("latente_eur")))} · {ui.fmt_pct(p.get("latente_pct"))} latente</div>'
            f'<div class="ss-mini">'
            f'<div class="ss-metrica"><span>Hoy</span><span>{hoy}</span></div>'
            f'<div class="ss-metrica"><span>Acciones</span><span>{_acc(p["acciones"])}</span></div>'
            f'<div class="ss-metrica"><span>Coste medio</span><span>{ui.escapar(_eur(p["coste_medio_eur"]))}</span></div>'
            f'<div class="ss-metrica"><span>Precio actual</span><span>{ui.escapar(_eur(p.get("precio_eur")))}</span></div>'
            f'<div class="ss-metrica"><span>Realizado (FIFO)</span><span>{ui.escapar(_eur(p["realizado_fifo_eur"]))}</span></div>'
            f'</div>'
            f'<div class="ss-mini-pie">Desde {p["primera_fecha"]:%d/%m/%Y} · {p["n_compras"]} compras · {p["n_ventas"]} ventas</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns([3, 1])
        with c1:
            if st.button("Analizar", key=f"cart_analizar_{t}", type="primary", width="stretch"):
                st.session_state["ticker_pendiente"] = t
                ui_interfaz.ir_a("Análisis Individual")
                st.rerun()
        with c2:
            if st.button("", key=f"cart_borrar_{t}", icon=":material/delete:", width="stretch",
                         help="Eliminar la posición (borra todas sus operaciones del libro)"):
                db_supabase.eliminar_posicion(t, ORIGEN)
                st.rerun()


# --------------------------------------------------------------- bloques ----
def _rendimiento(operaciones: list[dict], mercado) -> None:
    with ui.tarjeta(f"Rendimiento frente a {BENCHMARK}"):
        if mercado is None or not mercado.ok:
            ui.nd("Sin cierres de mercado para dibujar la curva.")
            return
        df = core_cartera.curva_vs_benchmark(operaciones, mercado.valor["cierres"], mercado.valor["benchmark"])
        if df is None:
            ui.nd("Curva no calculable: sin cierres para las posiciones o sin benchmark.")
            return
        r = core_cartera.retorno_curva(df)
        c1, c2, c3 = st.columns(3)
        _cifra(c1, "Cartera", ui.fmt_pct(r["cartera_pct"]), _sem(r["cartera_pct"]), "sobre el coste vivo")
        _cifra(c2, f"{BENCHMARK} con el mismo dinero", ui.fmt_pct(r["benchmark_pct"]), _sem(r["benchmark_pct"]),
               "mismas fechas, mismos importes, en EUR")
        _cifra(c3, "Diferencia", ui.fmt_pct(r["diferencia_pp"]).replace("%", "pp"), _sem(r["diferencia_pp"]))
        st.plotly_chart(ui_graficos.grafico_rendimiento(df, BENCHMARK), width="stretch",
                        config={"displayModeBar": False})
        st.markdown(f'<div class="ss-anotacion">Desde {df.index[0]:%d/%m/%Y} (primera operación) hasta '
                    f'{df.index[-1]:%d/%m/%Y}. Cada compra de X € compra X € de {BENCHMARK} ese mismo día; cada '
                    f'venta vende la misma fracción de su sombra.</div>', unsafe_allow_html=True)


def _riesgo(posiciones: dict[str, dict], mercado, ultimos: dict[str, dict]) -> None:
    abiertas = [p for p in posiciones.values() if not p["cerrada"]]
    with ui.tarjeta("Riesgo: concentración, sectores y correlación"):
        altas = [p for p in abiertas if p.get("peso_alto")]
        if altas:
            ui.alerta("Concentración: " + ", ".join(f'{p["ticker"]} {p["peso_pct"]:.0f} %' for p in altas)
                      + f" (más del {CARTERA_PESO_ALERTA * 100:.0f} % de la cartera)", C_NARANJA)
        else:
            st.markdown(f'<div class="ss-anotacion">Ninguna posición supera el {CARTERA_PESO_ALERTA * 100:.0f} % '
                        f'de la cartera.</div>', unsafe_allow_html=True)

        c_sec, c_cor = st.columns(2)
        with c_sec:
            st.markdown('<div class="ss-racha-tit">Exposición por sector</div>', unsafe_allow_html=True)
            # Sector: primero del último análisis guardado (ya consultado
            # para la recomendación: cero peticiones); `info` (cacheado 1 h)
            # solo para lo nunca analizado, y solo con este bloque abierto.
            sectores = {t: a["sector"] for t, a in ultimos.items() if a.get("sector")}
            for p in abiertas:
                if p["ticker"] not in sectores:
                    sectores[p["ticker"]] = (obtener_info(p["ticker"]).valor or {}).get("sector")
            exposicion = core_cartera.exposicion_sector(posiciones, sectores)
            if exposicion:
                st.plotly_chart(ui_graficos.grafico_sectores(exposicion), width="stretch",
                                config={"displayModeBar": False})
                for e in exposicion:
                    if e["alerta"]:
                        st.markdown(f'<div class="ss-anotacion" style="color:{C_NARANJA}">{e["sector"]} concentra '
                                    f'el {e["peso_pct"]:.0f} % (umbral {CARTERA_SECTOR_ALERTA * 100:.0f} %): '
                                    f'{", ".join(e["tickers"])}.</div>', unsafe_allow_html=True)
            else:
                ui.nd("Sin posiciones con precio para repartir por sector.")
        with c_cor:
            st.markdown('<div class="ss-racha-tit">Correlación de rendimientos diarios (1 año)</div>',
                        unsafe_allow_html=True)
            cierres = mercado.valor["cierres"] if mercado is not None and mercado.ok else None
            if cierres is not None and not cierres.empty:       # la descarga puede ser más larga: aquí, último año
                cierres = cierres.loc[cierres.index >= cierres.index[-1] - pd.Timedelta(days=CARTERA_HISTORICO_DIAS)]
            matriz, pares = core_cartera.correlacion(cierres)
            if matriz is None:
                ui.nd("Hacen falta al menos dos posiciones con histórico suficiente.")
            else:
                st.plotly_chart(ui_graficos.grafico_correlacion(matriz), width="stretch",
                                config={"displayModeBar": False})
                if pares:
                    st.markdown(f'<div class="ss-anotacion" style="color:{C_NARANJA}">Pares que se mueven casi igual '
                                f'(≥ {CARTERA_CORRELACION_ALTA:.2f}): '
                                + "; ".join(f'{x["a"]}–{x["b"]} {x["corr"]:.2f}' for x in pares)
                                + ". Diversifican menos de lo que parece.</div>", unsafe_allow_html=True)


def _libro(operaciones: list[dict]) -> None:
    with ui.tarjeta("Libro de operaciones"):
        filas = [{
            "Fecha": pd.Timestamp(o["fecha"]).strftime("%d/%m/%Y"), "Ticker": o["ticker"],
            "Tipo": str(o["tipo"]).capitalize(), "Acciones": float(o["acciones"]),
            "Precio (€)": float(o["precio_eur"]), "Comisión (€)": float(o.get("comision_eur") or 0),
            "Importe (€)": float(o["acciones"]) * float(o["precio_eur"]),
            "Origen": (f'{ui.fmt_num(o["precio_origen"], 4)} {o["divisa"]}'
                       if o.get("divisa") and o.get("divisa") != "EUR" and es_dato(o.get("precio_origen")) else ""),
            "Nota": o.get("nota") or "",
        } for o in reversed(operaciones)]
        st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True,
                     column_config={"Acciones": st.column_config.NumberColumn(format="%.4f"),
                                    "Precio (€)": st.column_config.NumberColumn(format="%.2f"),
                                    "Comisión (€)": st.column_config.NumberColumn(format="%.2f"),
                                    "Importe (€)": st.column_config.NumberColumn(format="%.2f")})
        opciones = {f'{pd.Timestamp(o["fecha"]):%d/%m/%Y} · {o["ticker"]} · {o["tipo"]} · '
                    f'{_acc(o["acciones"])} × {ui.fmt_num(o["precio_eur"])} €': o["id"]
                    for o in reversed(operaciones)}
        c1, c2 = st.columns([4, 1])
        with c1:
            elegida = st.selectbox("Eliminar una operación concreta", list(opciones), index=None,
                                   placeholder="Elige una operación para borrarla", label_visibility="collapsed")
        with c2:
            if st.button("Eliminar", key="cart_borrar_op", icon=":material/delete:", width="stretch",
                         disabled=elegida is None):
                db_supabase.eliminar_operacion(opciones[elegida])
                st.rerun()


def _cerradas(posiciones: dict[str, dict]) -> None:
    cerradas = [p for p in posiciones.values() if p["cerrada"]]
    if not cerradas:
        return
    with ui.tarjeta("Posiciones cerradas"):
        for p in sorted(cerradas, key=lambda x: x["ultima_fecha"], reverse=True):
            ui.metrica(f'{p["ticker"]} · {p["primera_fecha"]:%d/%m/%Y} → {p["ultima_fecha"]:%d/%m/%Y}',
                       _eur(p["realizado_fifo_eur"]),
                       f'invertidos {_eur(p["invertido_eur"], 0)} · {p["n_compras"]}c/{p["n_ventas"]}v',
                       semaforo=_sem(p["realizado_fifo_eur"]))


# ------------------------------------------------------------------- render --
def render() -> None:
    operaciones = db_supabase.listar_operaciones(ORIGEN)
    if not db_supabase.disponible():
        st.caption("Sin Supabase: las operaciones solo viven en esta sesión")

    posiciones = core_cartera.libro(operaciones)
    abiertas = [t for t, p in posiciones.items() if not p["cerrada"]]
    mercado = _mercado(abiertas, operaciones)
    aviso = st.session_state.pop("cart_aviso", None)
    if aviso:
        st.caption(aviso)
    lote = (mercado.valor or {}) if mercado is not None and mercado.ok else {}
    core_cartera.valorar(posiciones, lote.get("precios", {}))
    core_cartera.variacion_diaria(posiciones, lote.get("cierres_nativos"), lote.get("cierres"))
    # Recomendación por posición: momentum sobre los cierres nativos del
    # mismo lote (cero peticiones extra) y último veredicto guardado como veto.
    ultimos = db_supabase.ultimos_analisis(tuple(abiertas)) if abiertas else {}
    for t in abiertas:
        p = posiciones[t]
        p["momentum"] = core_cartera.momentum((lote.get("cierres_nativos") or {}).get(t))
        p["recomendacion"] = core_cartera.recomendar(p.get("latente_pct"), p["momentum"], ultimos.get(t))

    if operaciones:
        _resumen(core_cartera.resumen(posiciones), mercado)

    if st.toggle("Registrar operación", value=not operaciones, key="toggle_op",
                 help="Compra o venta real. Las ventas no pueden superar las acciones en cartera."):
        _formulario(operaciones)

    if not operaciones:
        with ui.tarjeta("Gestión de Cartera"):
            ui.pendiente("Todavía no hay operaciones. Registra tu primera compra arriba: el coste medio, el "
                         "realizado FIFO, el rendimiento frente al índice y el riesgo se derivan del libro.")
        return

    if abiertas:
        ui.rejilla(sorted(abiertas, key=lambda x: -(posiciones[x].get("valor_eur") or 0)),
                   lambda t: _ficha(posiciones[t]))

    # Rendimiento y riesgo se muestran por defecto (decisión de Samuel,
    # sesión 5); el libro sigue plegado porque es largo.
    c1, c2, c3 = st.columns(3)
    ver_rend = c1.toggle(f"Rendimiento vs {BENCHMARK}", value=True, key="toggle_rend", disabled=not abiertas)
    ver_riesgo = c2.toggle("Riesgo y sectores", value=True, key="toggle_riesgo", disabled=not abiertas)
    ver_libro = c3.toggle("Libro de operaciones", key="toggle_libro")
    if ver_rend and abiertas:
        _rendimiento(operaciones, mercado)
    if ver_riesgo and abiertas:
        _riesgo(posiciones, mercado, ultimos)
    if ver_libro:
        _libro(operaciones)
    _cerradas(posiciones)
