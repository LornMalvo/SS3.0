"""Rastreador (sesión 5). Análisis en bloque de un universo de tickers con
los tres motores, ranking, filtros y comparación lado a lado; y evaluación
de las señales emitidas (backtest sobre el histórico propio de análisis).

Universo = unión de las fuentes marcadas: Favoritos, posiciones de Cartera,
planes activos de Paper Trading y el universo propio (tickers que se añaden
a mano y se persisten en `rastreador_universo`).

Coste: cada ticker cuesta lo mismo que un análisis individual (histórico,
info, estados, precio y earnings, todo cacheado); solo se omiten noticias y
traducción. Por eso hay tope (RASTREADOR_MAX_TICKERS) y el rastreo se lanza
a mano, nunca al abrir la vista. El resultado vive en session_state:
cambiar filtros u orden no vuelve a pedir nada.

Dos modos (sesión 6):
- EN VIVO: el de siempre (universo pequeño, bajo demanda, con tope).
- SCREENER: índices enteros rastreados de noche por el cron
  (tarea_rastreo.py) y persistidos en `analisis_historico` con origen
  'cron'. La vista solo CONSULTA: filtros sobre calidad, upside, banda,
  timing, señal, veredicto y sector; coste en API cero y respuesta
  instantánea. Los índices se activan desde aquí (`rastreador_indices`).
  Para comparar lado a lado se relanzan en vivo hasta 3 seleccionados.

Distribución:
  [ Modo: En vivo | Screener ]
  [ Universo: fuentes · añadir/quitar · botón Rastrear ]      (en vivo)
  [ Rastreo nocturno: índices activos · último pase ]         (screener)
  [ Resultados: filtros · orden · tabla con selección de filas ]
  [ Comparación lado a lado de las filas seleccionadas (2-3) ]
  [ toggle Evaluación de señales: retornos por veredicto y por señal ]
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

import core_rastreador
import datos_analisis
import db_supabase
import ui_componentes as ui
import ui_interfaz
from config_settings import (
    BANDAS_VALORACION,
    BENCHMARK,
    C_NARANJA,
    C_TEXTO_TENUE,
    INDICES,
    PAPER_ESTADOS_ACTIVOS,
    RASTREADOR_HORIZONTES,
    RASTREADOR_MAX_TICKERS,
    SCREENER_MAX_DIAS,
    SENIALES_TIMING,
    TEXTO_ND,
    VEREDICTO_ORDEN,
)
from core_ponderar import es_dato
from datos_cache import cubo_mercado
from datos_yfinance import obtener_cierres_lote

CLAVE_RASTREO = "rastreo"
CLAVE_SCREENER = "screener"
FUENTES = ("Favoritos", "Cartera", "Paper Trading", "Universo propio")
MODOS = ("En vivo", "Screener (rastreo nocturno)")


def _sem(v) -> str | None:
    return "bien" if es_dato(v) and v > 0 else "mal" if es_dato(v) and v < 0 else None


# ----------------------------------------------------------------- universo --
def _tickers_fuente(fuente: str) -> set[str]:
    if fuente == "Favoritos":
        return set(db_supabase.listar_favoritos())
    if fuente == "Cartera":
        import core_cartera
        posiciones = core_cartera.libro(db_supabase.listar_operaciones("real"))
        return {t for t, p in posiciones.items() if not p["cerrada"]}
    if fuente == "Paper Trading":
        return {p["ticker"] for p in db_supabase.listar_planes_paper(PAPER_ESTADOS_ACTIVOS)}
    return set(db_supabase.listar_universo())


def _universo() -> list[str]:
    with ui.tarjeta("Universo a rastrear"):
        fuentes = st.pills("Fuentes", list(FUENTES), selection_mode="multi", default=list(FUENTES),
                           key="rastreo_fuentes", label_visibility="collapsed") or []
        c1, c2 = st.columns([3, 1])
        nuevos = c1.text_input("Añadir al universo propio", placeholder="AAPL, MSFT, SAN.MC… (coma o espacio)",
                               key="rastreo_nuevos", label_visibility="collapsed")
        if c2.button("Añadir", key="rastreo_anadir", width="stretch", icon=":material/add:", disabled=not nuevos.strip()):
            db_supabase.anadir_universo(nuevos.replace(";", ",").replace(" ", ",").split(","))
            st.session_state["rastreo_nuevos_limpiar"] = True
            st.rerun()
        propio = db_supabase.listar_universo()
        if propio:
            c3, c4 = st.columns([3, 1])
            quitar = c3.selectbox("Quitar del universo propio", propio, index=None, key="rastreo_quitar",
                                  placeholder=f"Universo propio: {', '.join(propio)}", label_visibility="collapsed")
            if c4.button("Quitar", key="rastreo_quitar_btn", width="stretch", icon=":material/delete:",
                         disabled=quitar is None):
                db_supabase.quitar_universo(quitar)
                st.rerun()
        tickers: set[str] = set()
        for f in fuentes:
            tickers |= _tickers_fuente(f)
        tickers = sorted(t for t in tickers if t)
        if len(tickers) > RASTREADOR_MAX_TICKERS:
            ui.alerta(f"{len(tickers)} tickers: se rastrean los {RASTREADOR_MAX_TICKERS} primeros por orden alfabético "
                      f"(tope para no agotar el límite de Yahoo). Quita fuentes o tickers para elegir.", C_NARANJA)
            tickers = tickers[:RASTREADOR_MAX_TICKERS]
        st.markdown(f'<div class="ss-anotacion">{len(tickers)} tickers: {", ".join(tickers) or "ninguno"}</div>',
                    unsafe_allow_html=True)
        if st.button(f"Rastrear {len(tickers)} valores", key="rastreo_lanzar", type="primary", icon=":material/radar:",
                     disabled=not tickers, width="stretch"):
            _rastrear(tickers)
            st.rerun()
        if not db_supabase.disponible():
            st.caption("Sin Supabase: el universo propio y los análisis solo viven en esta sesión")
    return tickers


def _rastrear(tickers: list[str], clave: str = CLAVE_RASTREO) -> None:
    """Analiza en serie (Yahoo penaliza la concurrencia por IP) y guarda
    solo las filas comprimidas. Cada análisis se persiste en el histórico
    (origen 'rastreador'), así el rastreo alimenta la evaluación de señales."""
    filas, errores = [], []
    barra = st.progress(0.0, text="Rastreando…")
    for i, t in enumerate(tickers, start=1):
        barra.progress(i / len(tickers), text=f"Analizando {t} ({i}/{len(tickers)})")
        try:
            a = datos_analisis.analizar(t, ligero=True, origen="rastreador")
        except Exception:
            a = None
        if a is None:
            errores.append(t)
            continue
        filas.append(core_rastreador.fila(a))
    barra.empty()
    st.session_state[clave] = {"filas": filas, "errores": errores, "cuando": pd.Timestamp.now(), "n": len(tickers)}


# --------------------------------------------------------------- resultados --
def _tabla(filas: list[dict]) -> list[str]:
    """Tabla con selección de filas (hasta 3 para comparar). Devuelve los
    tickers seleccionados."""
    screener = any("fecha" in f for f in filas)
    df = pd.DataFrame([{
        "Ticker": f["ticker"], "Nombre": f["nombre"], "Veredicto": f["veredicto"] or TEXTO_ND,
        "Puntuación": f["puntuacion"], "Calidad": f["calidad"], "Timing": f["timing"],
        **({"Timing bruto": f.get("timing_bruto")} if screener else {}),
        "Señal": f["senal"], "Precio": f["precio"], "Fair value": f["fair_value"], "Upside %": f["upside_pct"],
        **({"Banda": (f.get("banda") or "").split(" — ")[0]} if screener else {}),
        "E1": f["e1"], "Dist. E1 %": f["dist_e1_pct"],
        **({} if screener else {"B/R": f["ratio_br"]}),
        "Sector": f["sector"] or "", "Divisa": f["divisa"] or "",
        **({"Fecha": f.get("fecha")} if screener else {}),
    } for f in filas])
    cfg = {
        "Puntuación": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        "Calidad": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        "Timing": st.column_config.ProgressColumn(format="%.0f", min_value=0, max_value=100),
        "Timing bruto": st.column_config.NumberColumn(format="%.0f", help="Nota de timing SIN el gate de calidad (modo trading)"),
        "Precio": st.column_config.NumberColumn(format="%.2f"),
        "Fair value": st.column_config.NumberColumn(format="%.2f"),
        "Upside %": st.column_config.NumberColumn(format="%+.1f"),
        "E1": st.column_config.NumberColumn(format="%.2f"),
        "Dist. E1 %": st.column_config.NumberColumn(format="%+.1f", help="Precio respecto a la primera entrada del plan"),
        "B/R": st.column_config.NumberColumn(format="%.1f", help="Beneficio / riesgo del plan DCA"),
    }
    ev = st.dataframe(df, width="stretch", hide_index=True, column_config=cfg, on_select="rerun",
                      selection_mode="multi-row", key="rastreo_tabla")
    seleccion = [df.iloc[i]["Ticker"] for i in (ev.selection.rows if ev and ev.selection else [])]
    return seleccion[:3]


def _resultados(r: dict, screener: bool = False) -> list[dict]:
    filas = r["filas"]
    with ui.tarjeta("Resultados del screener (rastreo nocturno)" if screener else "Resultados del rastreo"):
        if screener:
            st.markdown(f'<div class="ss-anotacion">{len(filas)} valores con análisis de los últimos {SCREENER_MAX_DIAS} días '
                        f'(último análisis de cada ticker rastreado por el cron; coste en API: cero).</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="ss-anotacion">{len(filas)} de {r["n"]} valores analizados el '
                        f'{r["cuando"]:%d/%m/%Y %H:%M}'
                        + (f' · sin datos: {", ".join(r["errores"])}' if r["errores"] else "") + "</div>",
                        unsafe_allow_html=True)
        k = "scr_" if screener else "rastreo_"
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.4, 1.2])
        cal_min = c1.slider("Calidad mínima", 0, 100, 0, 5, key=f"{k}cal")
        up_min = c2.slider("Upside mínimo (%)", -50, 100, -50, 5, key=f"{k}up")
        tim_min = c3.slider("Timing mínimo", 0, 100, 0, 5, key=f"{k}tim")
        vers = c4.multiselect("Veredicto", list(VEREDICTO_ORDEN), default=[], key=f"{k}ver",
                              placeholder="Todos los veredictos")
        criterio = c5.selectbox("Orden", list(core_rastreador.CRITERIOS_ORDEN), key=f"{k}orden")
        senales = sectores = bandas = None
        bruto = False
        if screener:
            c6, c7, c8, c9 = st.columns([1.2, 1.4, 1.6, 1.2])
            senales = c6.multiselect("Señal de timing", [x[1] for x in SENIALES_TIMING], default=[], key="scr_sen",
                                     placeholder="Todas las señales") or None
            bandas = c7.multiselect("Banda de valoración", [b[2].split(" — ")[0] for b in BANDAS_VALORACION], default=[],
                                    key="scr_banda", placeholder="Todas las bandas") or None
            sectores = c8.multiselect("Sector", sorted({f["sector"] for f in filas if f.get("sector")}), default=[],
                                      key="scr_sector", placeholder="Todos los sectores") or None
            # Modo trading, decisión consciente: el motor topa el timing en 59
            # si la calidad no llega a 60; aquí se puede filtrar por la nota
            # bruta, y la tabla lo enseña en su propia columna.
            bruto = c9.toggle("Timing sin gate de calidad", key="scr_bruto",
                              help="Filtra por la nota bruta de timing, sin el tope por calidad < 60 (modo trading).")
        visibles = core_rastreador.ordenar(
            core_rastreador.filtrar(filas, cal_min, up_min, tim_min, vers or None, senales=senales, sectores=sectores,
                                    bandas=bandas, timing_bruto=bruto), criterio)
        if not visibles:
            ui.nd("Ningún valor pasa los filtros.")
            return []
        seleccion = _tabla(visibles)
        st.markdown('<div class="ss-anotacion">Marca 2 o 3 filas para compararlas lado a lado'
                    + (' (se analizan en vivo al pulsar el botón)' if screener else '')
                    + '. Puntuación = calidad 40 % · timing 35 % · upside 25 %; el veredicto manda en el orden por defecto.</div>',
                    unsafe_allow_html=True)
        c6, c7 = st.columns([3, 1])
        abrir = c6.selectbox("Abrir en Análisis Individual", [f["ticker"] for f in visibles], index=None,
                             placeholder="Elige un ticker para abrir su análisis completo", key=f"{k}abrir",
                             label_visibility="collapsed")
        if c7.button("Analizar", key=f"{k}abrir_btn", width="stretch", type="primary", disabled=abrir is None):
            st.session_state["ticker_pendiente"] = abrir
            ui_interfaz.ir_a("Análisis Individual")
            st.rerun()
        seleccionadas = [f for f in visibles if f["ticker"] in seleccion]
        if screener and len(seleccionadas) >= 2:
            if st.button(f"Comparar en vivo {', '.join(f['ticker'] for f in seleccionadas)}", key="scr_comparar",
                         icon=":material/compare:", width="stretch"):
                _rastrear([f["ticker"] for f in seleccionadas], clave=CLAVE_RASTREO + "_scr")
                st.rerun()
            vivo = st.session_state.get(CLAVE_RASTREO + "_scr")
            if vivo and {f["ticker"] for f in vivo["filas"]} == {f["ticker"] for f in seleccionadas}:
                return vivo["filas"]
            return []
        return seleccionadas


# ------------------------------------------------------------- comparación --
def _nota(v, decimales: int = 0) -> str:
    return ui.fmt_num(v, decimales) if es_dato(v) else TEXTO_ND


def _columna_comparacion(f: dict) -> None:
    divisa = f.get("divisa") or ""
    with ui.tarjeta():
        st.markdown(f'<div class="ss-mini-cab"><span class="ss-mini-tk">{f["ticker"]}</span>'
                    f'<span class="ss-mini-aparte">{ui.escapar(f["nombre"])}</span></div>', unsafe_allow_html=True)
        if f.get("veredicto"):
            ui.alerta(f["veredicto"], f.get("veredicto_color") or C_TEXTO_TENUE)
            st.markdown(f'<div class="ss-anotacion">{ui.escapar(f.get("veredicto_motivo") or "")}</div>', unsafe_allow_html=True)
        pos = f.get("posicion") or {}
        if pos.get("real") or pos.get("paper"):
            st.markdown(f'<div class="ss-anotacion">Posición abierta en '
                        f'{" y ".join(n for n, ok in (("cartera", pos.get("real")), ("Paper Trading", pos.get("paper"))) if ok)}.</div>',
                        unsafe_allow_html=True)
        ui.metrica("Puntuación de rastreo", _nota(f["puntuacion"]), f'cobertura {f["puntuacion_cobertura"] * 100:.0f} %')
        st.markdown('<div class="ss-racha-tit" style="margin-top:.4rem">Calidad</div>', unsafe_allow_html=True)
        ui.metrica("Nota", _nota(f["calidad"]), f'cobertura {(f["calidad_cobertura"] or 0) * 100:.0f} %',
                   semaforo="bien" if es_dato(f["calidad"]) and f["calidad"] >= 60 else "mal" if es_dato(f["calidad"]) else None)
        for nombre, nota in (f.get("bloques") or {}).items():
            ui.metrica(nombre, _nota(nota))
        st.markdown('<div class="ss-racha-tit" style="margin-top:.4rem">Valoración</div>', unsafe_allow_html=True)
        ui.metrica("Precio", ui.fmt_precio(f["precio"], divisa))
        ui.metrica("Fair value", ui.fmt_precio(f["fair_value"], divisa), ui.fmt_pct(f["upside_pct"]),
                   semaforo=_sem(f["upside_pct"]), color_en="referencia")
        if f.get("banda"):
            st.markdown(f'<div class="ss-anotacion">{f["banda"].split(" — ")[0]}'
                        + (" · revisar manualmente" if f.get("anomalia") else "") + "</div>", unsafe_allow_html=True)
        sens = f.get("sensibilidad") or {}
        if sens:
            ui.metrica("Conservador / optimista",
                       f'{_nota(sens.get("conservador"), 2)} / {_nota(sens.get("optimista"), 2)}')
        ui.metrica("PER forward", _nota(f["per_forward"], 1))
        ui.metrica("PEG", _nota(f["peg"], 2))
        ui.metrica("EV / EBITDA", _nota(f["ev_ebitda"], 1))
        ui.metrica("ROIC", ui.fmt_pct(f["roic"] * 100, signo=False) if es_dato(f["roic"]) else TEXTO_ND)
        ui.metrica("Margen operativo", ui.fmt_pct(f["margen_operativo"] * 100, signo=False) if es_dato(f["margen_operativo"]) else TEXTO_ND)
        ui.metrica("Deuda / Equity", _nota(f["deuda_patrimonio"], 2))
        ui.metrica("Capitalización", ui.fmt_importe(f["capitalizacion"], divisa))
        st.markdown('<div class="ss-racha-tit" style="margin-top:.4rem">Timing</div>', unsafe_allow_html=True)
        ui.metrica("Nota · señal", f'{_nota(f["timing"])} · {f["senal"] or TEXTO_ND}')
        for nombre, nota in (f.get("familias") or {}).items():
            ui.metrica(nombre, _nota(nota))
        ui.metrica("RSI (14)", _nota(f["rsi"], 1))
        ui.metrica("Distancia MM50 / MM200", f'{ui.fmt_pct(f["dist_mm50"])} / {ui.fmt_pct(f["dist_mm200"])}')
        ui.metrica("Variación 1 año", ui.fmt_pct(f["variacion_1a"]), semaforo=_sem(f["variacion_1a"]))
        ui.metrica("Distancia a máximos", ui.fmt_pct(f["dist_ath"]))
        st.markdown('<div class="ss-racha-tit" style="margin-top:.4rem">Plan DCA</div>', unsafe_allow_html=True)
        if f.get("entradas"):
            ui.metrica("Entradas", " · ".join(f"{n} {ui.fmt_num(p_, 2)}" for n, p_ in f["entradas"]))
            ui.metrica("Salidas", " · ".join(f"{n} {ui.fmt_num(p_, 2)}" for n, p_ in f["salidas"]))
            ui.metrica("Stop", ui.fmt_precio(f["stop"], divisa), f'riesgo {f["riesgo_pct"]:.0f} %' if es_dato(f["riesgo_pct"]) else None)
            ui.metrica("Beneficio / riesgo", f'{ui.fmt_num(f["ratio_br"], 1)} : 1' if es_dato(f["ratio_br"]) else TEXTO_ND,
                       semaforo="bien" if es_dato(f["ratio_br"]) and f["ratio_br"] >= 2 else "mal" if es_dato(f["ratio_br"]) and f["ratio_br"] < 1 else None)
        else:
            ui.nd("Sin plan calculable.")
        if st.button("Analizar", key=f"rastreo_cmp_{f['ticker']}", width="stretch"):
            st.session_state["ticker_pendiente"] = f["ticker"]
            ui_interfaz.ir_a("Análisis Individual")
            st.rerun()


def _comparacion(filas: list[dict]) -> None:
    if len(filas) < 2:
        return
    st.markdown('<div class="ss-card-titulo" style="margin-top:.6rem">Comparación lado a lado</div>', unsafe_allow_html=True)
    columnas = st.columns(len(filas))
    for col, f in zip(columnas, filas):
        with col:
            _columna_comparacion(f)


# ---------------------------------------------------- evaluación de señales --
def _evaluacion() -> None:
    """Qué pasó después de cada análisis guardado. Una consulta a Supabase y
    una descarga por lote (cierres nativos desde el análisis más antiguo);
    el resultado se cachea en session_state por cubo de mercado."""
    with ui.tarjeta("Evaluación de señales (histórico propio)"):
        analisis = db_supabase.listar_analisis()
        if not analisis:
            ui.nd("Sin análisis guardados en Supabase: la evaluación se alimenta de cada análisis que haces o rastreas.")
            return
        cubo = cubo_mercado()
        clave = f"rastreo_eval_{cubo}_{len(analisis)}"
        if clave not in st.session_state:
            tickers = tuple(sorted({a["ticker"] for a in analisis}))
            desde = (pd.Timestamp(min(a["fecha_analisis"] for a in analisis)).date() - timedelta(days=7)).isoformat()
            lote = obtener_cierres_lote(tickers, desde, cubo)
            cierres = lote.valor or {}
            detalle, resumenes = core_rastreador.evaluar_senales(analisis, cierres, cierres.get(BENCHMARK))
            db_supabase.guardar_backtest(core_rastreador.filas_backtest(detalle))
            st.session_state[clave] = (detalle, resumenes, lote)
        detalle, resumenes, lote = st.session_state[clave]
        if not detalle:
            ui.nd("Todavía no hay análisis con la antigüedad mínima para evaluarlos (o no hay cierres).")
            return
        st.markdown(f'<div class="ss-anotacion">{len(detalle)} análisis evaluados desde {min(d["fecha"] for d in detalle):%d/%m/%Y}. '
                    f'Retorno medio desde la fecha del análisis hasta hoy y a cada horizonte cumplido; '
                    f'"vs {BENCHMARK}" es la diferencia media frente al índice en el mismo periodo (misma divisa que el análisis, '
                    f'{BENCHMARK} en USD).</div>', unsafe_allow_html=True)
        for titulo, clave_r in (("Por veredicto", "veredicto"), ("Por señal de timing", "senal")):
            st.markdown(f'<div class="ss-racha-tit" style="margin-top:.5rem">{titulo}</div>', unsafe_allow_html=True)
            df = pd.DataFrame([{
                "Grupo": r["grupo"], "N": r["n"], "Retorno hasta hoy %": r["ret_hoy"], "% positivos": r["pct_positivos"],
                f"vs {BENCHMARK} pp": r["vs_bench_hoy"],
                **{f"{h} %": r[f"ret_{h}"] for h in RASTREADOR_HORIZONTES},
                **{f"N {h}": r[f"n_{h}"] for h in RASTREADOR_HORIZONTES},
            } for r in resumenes[clave_r]])
            st.dataframe(df, width="stretch", hide_index=True,
                         column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in df.columns if "%" in c or "pp" in c})
        _evaluacion_cron()
        if st.toggle("Detalle por análisis", key="rastreo_eval_detalle"):
            df = pd.DataFrame([{
                "Fecha": d["fecha"], "Ticker": d["ticker"], "Veredicto": d["veredicto"], "Señal": d["senal"],
                "Días": d["dias"], "Precio": d["precio"], "Hasta hoy %": d["ret_hoy"], f"{BENCHMARK} %": d["bench_hoy"],
                **{f"{h} %": d.get(f"ret_{h}") for h in RASTREADOR_HORIZONTES},
            } for d in sorted(detalle, key=lambda d: d["fecha"], reverse=True)])
            st.dataframe(df, width="stretch", hide_index=True,
                         column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in df.columns if "%" in c})
        ui.frescura(lote.obtenido_en, lote.fuente, "precio")


def _evaluacion_cron() -> None:
    """Señales del rastreo nocturno evaluadas POR EL CRON (viernes) y
    persistidas en backtest_resultados: aquí solo se leen y se resumen."""
    st.markdown('<div class="ss-racha-tit" style="margin-top:.8rem">Señales del rastreo nocturno (evaluadas por el cron)</div>',
                unsafe_allow_html=True)
    filas = db_supabase.listar_backtest(origen_cron=True)
    if not filas:
        ui.nd("Todavía no hay señales del cron con un horizonte cumplido (el cron las evalúa los viernes a partir de los 3 meses).")
        return
    res = core_rastreador.resumen_backtest(filas)
    st.markdown(f'<div class="ss-anotacion">{len(filas)} señales del cron con al menos 3 meses cumplidos. Retorno medio a cada '
                f'horizonte y diferencia media frente a {BENCHMARK} (pp) en el mismo periodo.</div>', unsafe_allow_html=True)
    for titulo, clave in (("Por veredicto", "veredicto"), ("Por señal de timing", "senal")):
        st.markdown(f'<div class="ss-mini-tit">{titulo}</div>', unsafe_allow_html=True)
        df = pd.DataFrame([{
            "Grupo": r["grupo"], "N": r["n"], "% positivos 3m": r["pct_positivos_3m"],
            **{k: v for h in RASTREADOR_HORIZONTES for k, v in ((f"{h} %", r[f"ret_{h}"]), (f"vs {BENCHMARK} {h} pp", r[f"vs_bench_{h}"]),
                                                                (f"N {h}", r[f"n_{h}"]))},
        } for r in res[clave]])
        st.dataframe(df, width="stretch", hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in df.columns if "%" in c or "pp" in c})


# ---------------------------------------------------------- rastreo nocturno --
def _nocturno() -> None:
    """Qué índices rastrea el cron cada noche y cómo fue el último pase."""
    with ui.tarjeta("Rastreo nocturno de índices"):
        indices = {f["nombre"]: f for f in db_supabase.listar_indices()}
        if not db_supabase.disponible():
            ui.nd("Sin Supabase no hay rastreo nocturno: el cron escribe y esta vista lee de la base de datos.")
            return
        cols = st.columns(len(INDICES))
        for col, nombre in zip(cols, INDICES):
            fila = indices.get(nombre) or {"activo": False, "n": 0, "actualizado_en": None}
            with col:
                activo = st.toggle(nombre, value=bool(fila.get("activo")), key=f"idx_{nombre}",
                                   help=f"{fila.get('n') or 0} constituyentes"
                                        + (f" · lista del {str(fila.get('actualizado_en'))[:10]}" if fila.get("actualizado_en") else " · lista pendiente (la refresca el cron)"))
                if activo != bool(fila.get("activo")):
                    db_supabase.guardar_indice(nombre, activo=activo)
                    st.rerun()
        pases = db_supabase.ultimos_pases(3)
        if pases:
            txt = " · ".join(f'{p["indice"]}: {p["n_ok"]}/{p["n_total"]} ok, {p["estado"]} ({str(p["inicio"])[:16].replace("T", " ")} UTC)'
                             for p in pases)
            st.markdown(f'<div class="ss-anotacion">Últimos pases: {txt}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="ss-anotacion">Sin pases todavía. El cron (rastreo.yml, L-V 22:30 UTC) rastrea los índices '
                        'activos; también se puede lanzar a mano desde GitHub Actions (Run workflow).</div>', unsafe_allow_html=True)


def _cargar_screener() -> dict:
    """Último análisis del cron de cada ticker (una consulta, cacheada por
    cubo de mercado en session_state)."""
    cubo = cubo_mercado()
    clave = f"{CLAVE_SCREENER}_{cubo}"
    if clave not in st.session_state or st.session_state.pop("screener_recargar", False):
        desde = (pd.Timestamp.today() - timedelta(days=SCREENER_MAX_DIAS)).date().isoformat()
        filas = [core_rastreador.fila_desde_historico(h) for h in db_supabase.listar_screener(desde)]
        st.session_state[clave] = {"filas": filas, "errores": [], "cuando": pd.Timestamp.now(), "n": len(filas)}
    return st.session_state[clave]


# ------------------------------------------------------------------- render --
def render() -> None:
    if st.session_state.pop("rastreo_nuevos_limpiar", False):
        st.session_state["rastreo_nuevos"] = ""
    modo = st.segmented_control("Modo", list(MODOS), default=MODOS[0], key="rastreo_modo",
                                label_visibility="collapsed") or MODOS[0]
    if modo == MODOS[0]:
        _universo()
        r = st.session_state.get(CLAVE_RASTREO)
        if r:
            if r["filas"]:
                _comparacion(_resultados(r))
            else:
                with ui.tarjeta("Resultados del rastreo"):
                    ui.nd("Ningún valor devolvió datos" + (f": {', '.join(r['errores'])}" if r["errores"] else "."))
        else:
            with ui.tarjeta("Resultados del rastreo"):
                ui.pendiente("Elige las fuentes, añade tickers al universo propio si quieres y pulsa Rastrear: cada valor "
                             "pasa por los tres motores y aparece aquí con su veredicto, para filtrar, ordenar y comparar.")
    else:
        _nocturno()
        r = _cargar_screener()
        if r["filas"]:
            _comparacion(_resultados(r, screener=True))
        else:
            with ui.tarjeta("Resultados del screener (rastreo nocturno)"):
                ui.pendiente(f"Sin análisis del cron en los últimos {SCREENER_MAX_DIAS} días. Activa un índice arriba y espera al "
                             "pase nocturno (o lánzalo desde GitHub Actions).")
        if st.button("Recargar", key="scr_recargar", icon=":material/refresh:"):
            st.session_state["screener_recargar"] = True
            st.rerun()
    if st.toggle("Evaluación de señales", key="rastreo_eval_toggle",
                 help="Retorno real de cada análisis guardado (individual, rastreo o cron) frente al índice, por veredicto y por señal"):
        _evaluacion()
