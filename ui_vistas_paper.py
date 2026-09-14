"""Paper Trading (sesión 4). Cada plan guardado desde Análisis Individual es
una ficha con su estado (derivado de las ejecuciones, ver core_paper), sus
niveles con marca de ejecutado y distancia al precio actual, el rendimiento
simulado y las acciones posibles: ejecutar el siguiente nivel (con precio y
fecha editables), descartar (solo en vigilancia), analizar y eliminar.

Precios: UNA descarga por lote para todos los tickers de los planes
visibles. Las ejecuciones se registran en la divisa del plan y, además, como
operación con origen 'paper' en el libro (en EUR, con el tipo del día) para
que el motor de cartera sea el mismo.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

import core_paper
import db_supabase
import ui_componentes as ui
import ui_interfaz
from config_settings import (
    C_TEXTO_TENUE,
    PAPER_CAPITAL_DEFECTO,
    PAPER_ESTADOS,
    PAPER_ESTADOS_ACTIVOS,
    PAPER_ESTADOS_CERRADOS,
    PAPER_ESTADOS_DESCARTADOS,
    PAPER_NIVEL_STOP,
    PAPER_NIVELES_ENTRADA,
    PLAN_COLOR_STOP,
    PLAN_COLORES_ENTRADA,
    PLAN_COLORES_SALIDA,
    TEXTO_ND,
)
from core_ponderar import es_dato
from datos_cache import cubo_mercado
from datos_yfinance import convertir_a_eur, fx_en_fecha, obtener_precios_lote

FILTROS = {
    "Activos": PAPER_ESTADOS_ACTIVOS,
    "Cerrados": PAPER_ESTADOS_CERRADOS,
    "Descartados": PAPER_ESTADOS_DESCARTADOS,
    "Todos": tuple(PAPER_ESTADOS),
}


def _sem(v) -> str | None:
    return "bien" if es_dato(v) and v > 0 else "mal" if es_dato(v) and v < 0 else None


def _dist(precio, nivel) -> float | None:
    if not es_dato(precio) or not es_dato(nivel) or not nivel:
        return None
    return (precio / nivel - 1) * 100


# ----------------------------------------------------------------- niveles --
def _nivel_html(nivel: dict, color: str, divisa: str, precio_actual, ejecucion: dict | None) -> str:
    """Una fila de nivel: precio, y a la derecha o bien la ejecución (✓ fecha
    a precio) o bien la distancia del precio actual al nivel."""
    precio = ui.escapar(ui.fmt_precio(nivel["precio"], divisa))
    if ejecucion:
        derecha = (f'<span style="color:{color};font-weight:700">✓ {str(ejecucion["fecha"])[8:10]}/{str(ejecucion["fecha"])[5:7]}'
                   f' · {ui.escapar(ui.fmt_num(ejecucion["precio"]))}</span>')
    else:
        d = _dist(precio_actual, nivel["precio"])
        derecha = f'<span class="ss-media-sector">{ui.fmt_pct(d)}</span>' if es_dato(d) else ""
    peso = f' · {nivel["peso"] * 100:.0f} %' if es_dato(nivel.get("peso")) and nivel["nivel"] != PAPER_NIVEL_STOP else ""
    return (f'<div class="ss-nivel" style="border-left:4px solid {color};padding:.2rem .5rem;margin-bottom:.18rem;font-size:.8rem">'
            f'<span><b>{nivel["nivel"]}</b>{peso}</span><span><b>{precio}</b> {derecha}</span></div>')


def _niveles(p: dict, ejec: list[dict], precio_actual) -> None:
    divisa = p.get("divisa") or ""
    por_nivel = {e["nivel"]: e for e in ejec}
    html = []
    for n, color in zip(p.get("entradas") or [], PLAN_COLORES_ENTRADA):
        html.append(_nivel_html(n, color, divisa, precio_actual, por_nivel.get(n["nivel"])))
    for n, color in zip(p.get("salidas") or [], PLAN_COLORES_SALIDA):
        html.append(_nivel_html(n, color, divisa, precio_actual, por_nivel.get(n["nivel"])))
    if es_dato(p.get("stop")):
        html.append(_nivel_html({"nivel": PAPER_NIVEL_STOP, "precio": p["stop"]}, PLAN_COLOR_STOP, divisa,
                                precio_actual, por_nivel.get(PAPER_NIVEL_STOP)))
    st.markdown("".join(html), unsafe_allow_html=True)


# ------------------------------------------------------------- rendimiento --
def _rendimiento(p: dict, ejec: list[dict], precio_actual) -> None:
    r = core_paper.rendimiento(p, ejec, precio_actual)
    if r is None:
        return
    divisa = p.get("divisa") or ""
    st.markdown(
        f'<div class="ss-mini">'
        f'<div class="ss-metrica"><span>Acciones · coste medio</span><span>{ui.fmt_num(r["acciones"], 4).rstrip("0").rstrip(",")}'
        f' · {ui.escapar(ui.fmt_num(r["coste_medio"]))}</span></div>'
        f'<div class="ss-metrica"><span>Invertido</span><span>{ui.escapar(ui.fmt_precio(r["invertido"], divisa))}</span></div>'
        f'</div>', unsafe_allow_html=True)
    if not r["cerrada"]:
        ui.metrica("Latente", ui.fmt_precio(r["latente"], divisa) if es_dato(r["latente"]) else TEXTO_ND,
                   ui.fmt_pct(r["latente_pct"]), semaforo=_sem(r["latente"]))
    ui.metrica("Realizado (FIFO)", ui.fmt_precio(r["realizado"], divisa), semaforo=_sem(r["realizado"]))
    ui.metrica("Resultado total", ui.fmt_pct(r["total_pct"]),
               f'{ui.fmt_precio(r["total"], divisa)}' if es_dato(r["total"]) else None, semaforo=_sem(r["total_pct"]))


# ---------------------------------------------------------------- ejecutar --
def _ejecutar(p: dict, ejec: list[dict], precio_actual) -> None:
    pendientes = core_paper.niveles_pendientes(p, ejec)
    if not pendientes:
        return
    pid = p["id"]
    if not st.toggle("Ejecutar un nivel", key=f"paper_tog_{pid}"):
        return
    # Por defecto se propone el nivel más cercano al precio actual: es el que
    # acaba de tocarse o el que está a punto.
    if es_dato(precio_actual):
        defecto = min(pendientes, key=lambda n: abs(_dist(precio_actual, core_paper.precio_nivel(p, n)) or 1e9))
    else:
        defecto = pendientes[0]
    c1, c2, c3 = st.columns([1, 1.3, 1.3])
    nivel = c1.selectbox("Nivel", pendientes, index=pendientes.index(defecto), key=f"paper_nivel_{pid}")
    precio_def = core_paper.precio_nivel(p, nivel) or precio_actual or 0.0
    precio = c2.number_input(f"Precio ({p['divisa']})" if p.get("divisa") else "Precio", min_value=0.0, value=float(precio_def),
                             step=0.01, format="%.4f", key=f"paper_precio_{pid}_{nivel}")
    fecha = c3.date_input("Fecha", value=date.today(), max_value=date.today(), format="DD/MM/YYYY",
                          key=f"paper_fecha_{pid}")
    primera_entrada = not (core_paper.ejecutadas(ejec) & set(PAPER_NIVELES_ENTRADA))
    capital = float(p.get("capital_eur") or PAPER_CAPITAL_DEFECTO)
    if primera_entrada:
        capital = st.number_input("Capital del plan (€)", min_value=1.0, value=capital, step=100.0,
                                  key=f"paper_capital_{pid}",
                                  help="Importe nominal que reparten E1/E2/E3 con sus pesos. Se fija con la primera entrada.")
    # El capital es EUR y el precio está en la divisa del plan: el tamaño se
    # calcula pasando el capital a esa divisa con el tipo del día elegido.
    fx, _ = fx_en_fecha(p.get("divisa"), fecha, cubo_mercado())
    acciones = core_paper.acciones_para({**p, "capital_eur": capital}, nivel, precio, ejec, fx)
    st.markdown(f'<div class="ss-anotacion">{nivel}: {ui.fmt_num(acciones, 4) if es_dato(acciones) else TEXTO_ND} '
                f'acciones a {ui.escapar(ui.fmt_precio(precio, p.get("divisa")))}'
                + ("" if es_dato(fx) or p.get("divisa") == "EUR" else " (divisa no convertible: capital tomado como nominal en esa divisa)")
                + '</div>', unsafe_allow_html=True)
    if st.button("Ejecutar", key=f"paper_ejec_{pid}", type="primary", width="stretch", icon=":material/play_arrow:",
                 disabled=not es_dato(acciones) or acciones <= 0 or precio <= 0):
        _registrar_ejecucion(p, ejec, nivel, float(precio), fecha, acciones, capital if primera_entrada else None)
        st.rerun()


def _registrar_ejecucion(p: dict, ejec: list[dict], nivel: str, precio: float, fecha: date, acciones: float,
                         capital: float | None) -> None:
    """Ejecución -> operación 'paper' en el libro (en EUR, si la divisa es
    convertible) -> fila en paper_ejecuciones -> estado derivado -> diario."""
    pid = p["id"]
    if capital is not None:
        db_supabase.actualizar_plan_paper(pid, {"capital_eur": capital})
        p["capital_eur"] = capital
    fx, _ = fx_en_fecha(p.get("divisa"), fecha, cubo_mercado())     # tipo del día de la ejecución
    precio_eur = precio * fx if es_dato(fx) else None
    op_id = None
    if es_dato(precio_eur):
        op_id = db_supabase.insertar_operacion({
            "ticker": p["ticker"], "tipo": "compra" if nivel in PAPER_NIVELES_ENTRADA else "venta",
            "fecha": fecha.isoformat(), "acciones": acciones, "precio_eur": float(precio_eur), "comision_eur": 0.0,
            "origen": "paper", "plan_id": pid if pid > 0 else None, "nota": f"Paper {nivel}",
            "divisa": p.get("divisa"), "precio_origen": precio, "fx_aplicado": fx,
        })
    fila = core_paper.fila_ejecucion(pid, nivel, fecha, precio, acciones, op_id if op_id and op_id > 0 else None)
    if db_supabase.registrar_ejecucion_paper(fila) is None:
        st.error("No se pudo registrar la ejecución.")
        return
    nuevo = core_paper.estado(p, ejec + [fila])
    if nuevo != p.get("estado"):
        db_supabase.actualizar_plan_paper(pid, {"estado": nuevo})
    db_supabase.registrar_decision(p["ticker"], "ejecutar_nivel", f"{nivel} a {precio:g} {p.get('divisa') or ''}",
                                   pid if pid > 0 else None)


# ------------------------------------------------------------------- ficha --
def _ficha(p: dict, ejec: list[dict], precio_actual) -> None:
    estado = core_paper.estado(p, ejec)
    etiqueta, color = PAPER_ESTADOS.get(estado, (estado, C_TEXTO_TENUE))
    divisa = p.get("divisa") or ""
    pid = p["id"]
    with ui.tarjeta():
        st.markdown(
            f'<div class="ss-mini-cab"><span class="ss-mini-tk">{p.get("ticker")}</span>{ui.badge(etiqueta, color)}</div>'
            f'<div class="ss-mini-sub">Ahora {ui.escapar(ui.fmt_precio(precio_actual, divisa))} · '
            f'ref. {ui.escapar(ui.fmt_precio(p.get("precio_ref"), divisa))} · {ui.escapar(p.get("veredicto") or "")}'
            f' · {str(p.get("creado_en") or "")[:10]}'
            + (f' · capital {ui.escapar(ui.fmt_precio(p.get("capital_eur"), "EUR", 0))}' if es_dato(p.get("capital_eur")) else "")
            + "</div>",
            unsafe_allow_html=True,
        )
        _niveles(p, ejec, precio_actual)
        _rendimiento(p, ejec, precio_actual)
        if estado in PAPER_ESTADOS_ACTIVOS:
            _ejecutar(p, ejec, precio_actual)

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            if st.button("Analizar", key=f"paper_analizar_{pid}", width="stretch"):
                st.session_state["ticker_pendiente"] = p.get("ticker")
                ui_interfaz.ir_a("Análisis Individual")
                st.rerun()
        with c2:
            if core_paper.puede_descartar(p, ejec):
                if st.button("Descartar", key=f"paper_desc_{pid}", width="stretch",
                             help="El plan deja de vigilarse; se conserva en Descartados"):
                    db_supabase.actualizar_plan_paper(pid, {"estado": "descartada"})
                    db_supabase.registrar_decision(p["ticker"], "descartar", "descartado desde Paper Trading",
                                                   pid if pid > 0 else None)
                    st.rerun()
        with c3:
            if st.button("", key=f"paper_borrar_{pid}", icon=":material/delete:", width="stretch",
                         help="Eliminar el plan y sus ejecuciones simuladas"):
                db_supabase.eliminar_plan_paper(pid)
                st.rerun()


# ----------------------------------------------------------------- resumen --
def _resumen(planes: list[dict], ejec_por_plan: dict, precios: dict) -> None:
    """Recuento por estado y suma en EUR (tipo de hoy) del latente y del
    realizado simulados. Un plan sin precio o con divisa no convertible no
    suma: se dice cuántos quedan fuera en vez de sumar un cero."""
    conteo: dict[str, int] = {}
    latente_eur = realizado_eur = None
    sin_dato = 0
    for p in planes:
        e = ejec_por_plan.get(p["id"], [])
        est = core_paper.estado(p, e)
        conteo[est] = conteo.get(est, 0) + 1
        r = core_paper.rendimiento(p, e, (precios.get(p["ticker"]) or {}).get("precio"))
        if not r:
            continue
        lat, _ = convertir_a_eur(r["latente"], p.get("divisa"))
        rea, _ = convertir_a_eur(r["realizado"], p.get("divisa"))
        if es_dato(lat):
            latente_eur = (latente_eur or 0.0) + lat
        else:
            sin_dato += 1
        if es_dato(rea):
            realizado_eur = (realizado_eur or 0.0) + rea
    badges = " ".join(ui.badge(f"{PAPER_ESTADOS[k][0]} {n}", PAPER_ESTADOS[k][1]) for k, n in conteo.items() if k in PAPER_ESTADOS)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f'<div class="ss-etiqueta">Planes</div><div style="margin:.2rem 0 .6rem">{badges}</div>',
                    unsafe_allow_html=True)
    with c2:
        if es_dato(latente_eur) or es_dato(realizado_eur):
            ui.metrica("Latente simulado (EUR)", ui.fmt_precio(latente_eur, "EUR") if es_dato(latente_eur) else TEXTO_ND,
                       f"{sin_dato} sin precio" if sin_dato else None, semaforo=_sem(latente_eur))
            ui.metrica("Realizado simulado (EUR)", ui.fmt_precio(realizado_eur, "EUR") if es_dato(realizado_eur) else TEXTO_ND,
                       semaforo=_sem(realizado_eur))


# ------------------------------------------------------------------ render --
def render() -> None:
    todos = db_supabase.listar_planes_paper()
    if not todos:
        with ui.tarjeta("Paper Trading"):
            ui.pendiente("Todavía no hay planes guardados. Analiza un valor y pulsa «Guardar en Paper Trading» "
                         "para seguirlo aquí: podrás ejecutar cada nivel del plan y ver su rendimiento simulado.")
        return
    if not db_supabase.disponible():
        st.caption("Sin Supabase: los planes solo viven en esta sesión")

    ejecuciones = db_supabase.listar_ejecuciones_paper(tuple(p["id"] for p in todos))
    ejec_por_plan: dict[int, list[dict]] = {}
    for e in ejecuciones:
        ejec_por_plan.setdefault(e["plan_id"], []).append(e)

    filtro = st.segmented_control("Filtro", list(FILTROS), default="Activos", key="paper_filtro",
                                  label_visibility="collapsed") or "Activos"
    planes = [p for p in todos if core_paper.estado(p, ejec_por_plan.get(p["id"], [])) in FILTROS[filtro]]

    tickers = tuple(sorted({p["ticker"] for p in planes}))
    lote = obtener_precios_lote(tickers, cubo_mercado()) if tickers else None
    precios = (lote.valor or {}) if lote is not None else {}

    _resumen(planes, ejec_por_plan, precios)
    if not planes:
        ui.nd(f"Sin planes en «{filtro}».")
        return
    columnas = st.columns(3)
    for i, p in enumerate(planes):
        with columnas[i % 3]:
            _ficha(p, ejec_por_plan.get(p["id"], []), (precios.get(p["ticker"]) or {}).get("precio"))
    if lote is not None:
        ui.frescura(lote.obtenido_en, lote.fuente, "precio")
