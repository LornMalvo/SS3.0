"""Bloque 7 — Comparables (peer to peer), a todo el ancho bajo Calidad /
Fair Value, Timing y Plan DCA (sesión 6).

Híbrido: Finnhub (/stock/peers) SUGIERE comparables la primera vez que se
ve un ticker; el usuario tiene la última palabra (añade, valida, quita) y
la lista queda en Supabase (`comparables`). Un comparable validado es
SIMÉTRICO: al marcar AMD como competencia de NVDA, NVDA queda como
competencia de AMD (db_supabase.anadir_comparable).

Los múltiplos de cada comparable se guardan en `multiplos` y de ahí salen
las medianas que usan Fair Value (B, D, E, F, G) y Calidad (métricas
relativas) en vez de la tabla semilla: el bloque no es solo visual, es la
pieza que corrige la debilidad conocida del motor de valoración.

Coste: un `info` por comparable (cacheado 1 h) y SOLO cuando su fila de
múltiplos falta o tiene más de MULTIPLOS_MAX_DIAS días; con la tabla al día
el bloque no pide nada. El ROIC de un comparable solo aparece si ese
ticker se ha analizado alguna vez (necesita los estados financieros).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import core_fundamentales
import core_referencias
import datos_analisis
import db_supabase
import ui_componentes as ui
import ui_interfaz
from config_settings import C_AMBAR, C_TEAL, C_VERDE, MULTIPLOS_MAX_DIAS, PEERS_MAX
from core_ponderar import es_dato
from datos_yfinance import convertir_a_eur, obtener_info

_ORIGEN = {"manual": ("validado", C_VERDE), "finnhub": ("sugerido por Finnhub", C_AMBAR)}
_COLUMNAS = [   # (título, clave en `valores`, formato)
    ("PER fwd", "per_forward", "%.1f"), ("PEG", "peg", "%.2f"), ("EV/EBITDA", "ev_ebitda", "%.1f"),
    ("EV/Ventas", "ev_ventas", "%.2f"), ("P/B", "precio_valor_contable", "%.2f"),
    ("Mg. bruto %", "margen_bruto", "%.1f"), ("Mg. oper. %", "margen_operativo", "%.1f"),
    ("ROE %", "roe", "%.1f"), ("ROIC %", "roic", "%.1f"), ("Deuda n./EBITDA", "deuda_neta_ebitda", "%.1f"),
]
_EN_PCT = {"margen_bruto", "margen_operativo", "roe", "roic"}


def _viejo(fila: dict | None) -> bool:
    if not fila or not fila.get("actualizado_en"):
        return True
    try:
        cuando = pd.Timestamp(fila["actualizado_en"]).to_pydatetime()
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return datetime.now(timezone.utc) - cuando > timedelta(days=MULTIPLOS_MAX_DIAS)


def _refrescar(peers: list[str], guardados: dict[str, dict], forzar: bool) -> dict[str, dict]:
    """Pide `info` de los comparables sin múltiplos o con múltiplos viejos y
    los guarda. Devuelve la tabla actualizada."""
    pendientes = [p for p in peers if forzar or _viejo(guardados.get(p))]
    if not pendientes:
        return guardados
    barra = st.progress(0.0, text="Actualizando múltiplos de comparables…")
    for i, p in enumerate(pendientes, start=1):
        barra.progress(i / len(pendientes), text=f"Múltiplos de {p} ({i}/{len(pendientes)})")
        info = obtener_info(p)
        if not info.ok:
            continue
        fund = core_fundamentales.extraer(info.valor, None)
        fund["divisa_cotizacion"] = info.valor.get("currency")
        fila = datos_analisis.fila_multiplos(p, info.valor, fund)
        if guardados.get(p) and es_dato((guardados[p].get("valores") or {}).get("roic")):
            fila["valores"]["roic"] = guardados[p]["valores"]["roic"]   # el ROIC solo sale del análisis completo
        db_supabase.guardar_multiplos(fila)
        guardados[p] = {**fila, "actualizado_en": datetime.now(timezone.utc).isoformat()}
    barra.empty()
    return guardados


def _edicion(ticker: str, comps: list[dict]) -> None:
    """Añadir (manual, simétrico), validar una sugerencia (pasa a manual,
    simétrico) y quitar (manual: ambas direcciones; sugerido: rechazado)."""
    sugeridos = [c["peer"] for c in comps if c["origen"] == "finnhub"]
    c1, c2, c3, c4 = st.columns([1.6, 1, 1.4, 1.4])
    nuevo = c1.text_input("Añadir comparable", placeholder="Ticker (p. ej. AMD)", key=f"peer_nuevo_{ticker}",
                          label_visibility="collapsed")
    if c2.button("Añadir", key=f"peer_add_{ticker}", width="stretch", icon=":material/add:", disabled=not nuevo.strip()):
        if db_supabase.anadir_comparable(ticker, nuevo):
            st.session_state[f"peer_aviso_{ticker}"] = f"{nuevo.strip().upper()} y {ticker} quedan marcados como competencia mutua."
            st.rerun()
    validar = c3.selectbox("Validar sugerencia", sugeridos, index=None, key=f"peer_validar_{ticker}",
                           placeholder="Validar sugerencia…", label_visibility="collapsed", disabled=not sugeridos)
    if validar and c3.button("Validar (simétrico)", key=f"peer_validar_btn_{ticker}", width="stretch", icon=":material/check:"):
        db_supabase.anadir_comparable(ticker, validar)
        st.rerun()
    quitar = c4.selectbox("Quitar comparable", [c["peer"] for c in comps], index=None, key=f"peer_quitar_{ticker}",
                          placeholder="Quitar comparable…", label_visibility="collapsed", disabled=not comps)
    if quitar and c4.button("Quitar", key=f"peer_quitar_btn_{ticker}", width="stretch", icon=":material/delete:"):
        origen = next((c["origen"] for c in comps if c["peer"] == quitar), "manual")
        db_supabase.quitar_comparable(ticker, quitar, origen)
        st.rerun()


def _tabla(a: dict, comps: list[dict], multiplos: dict[str, dict]) -> None:
    ticker = a["ticker"]
    propio = datos_analisis.fila_multiplos(ticker, a["info"].valor, a["fundamentales"])
    filas = [("propio", ticker, propio)] + [(c["origen"], c["peer"], multiplos.get(c["peer"])) for c in comps]
    valores_peers = [f.get("valores") or {} for _, _, f in filas[1:] if f]
    med = core_referencias.medianas(valores_peers)
    registros = []
    for origen, t, f in filas:
        v = (f or {}).get("valores") or {}
        cap_eur, _ = convertir_a_eur(v.get("capitalizacion"), (f or {}).get("divisa")) if f else (None, None)
        reg = {"Ticker": t, "Nombre": (f or {}).get("nombre") or "", "Origen": _ORIGEN.get(origen, (origen, ""))[0],
               "Cap. (M€)": round(cap_eur / 1e6) if es_dato(cap_eur) else None}
        for titulo, clave, _ in _COLUMNAS:
            x = v.get(clave)
            reg[titulo] = (x * 100 if clave in _EN_PCT else x) if es_dato(x) else None
        reg["Actualizado"] = str((f or {}).get("actualizado_en") or "")[:10] or ("sin datos" if f is None else "")
        registros.append(reg)
    if valores_peers:
        reg = {"Ticker": "MEDIANA", "Nombre": "comparables con dato", "Origen": "", "Cap. (M€)": None}
        for titulo, clave, _ in _COLUMNAS:
            m = med.get(clave)
            reg[titulo] = (m["mediana"] * 100 if clave in _EN_PCT else m["mediana"]) if m else None
        reg["Actualizado"] = ""
        registros.append(reg)
    df = pd.DataFrame(registros)
    cfg = {titulo: st.column_config.NumberColumn(format=fmt) for titulo, _, fmt in _COLUMNAS}
    cfg["Cap. (M€)"] = st.column_config.NumberColumn(format="%d")
    st.dataframe(df, width="stretch", hide_index=True, column_config=cfg)


def render(a: dict) -> None:
    ticker = a["ticker"]
    with ui.tarjeta("Comparables (peer to peer)"):
        aviso = st.session_state.pop(f"peer_aviso_{ticker}", None)
        if aviso:
            st.caption(aviso)
        comps = datos_analisis.comparables_validos(ticker)[:PEERS_MAX]
        _edicion(ticker, comps)
        if not comps:
            ui.nd("Sin comparables: Finnhub no ha sugerido ninguno para este ticker. Añade los que conozcas.")
            return
        peers = [c["peer"] for c in comps]
        forzar = st.session_state.pop(f"peer_forzar_{ticker}", False)
        multiplos = _refrescar(peers, db_supabase.leer_multiplos(tuple(peers)), forzar)
        _tabla(a, comps, multiplos)

        refs = a.get("referencias") or {}
        n_dato = len([p for p in peers if multiplos.get(p)])
        dominante = refs.get("dominante", core_referencias.FUENTE_SEMILLA)
        color = {core_referencias.FUENTE_PEERS: C_VERDE, core_referencias.FUENTE_SECTOR_REAL: C_TEAL}.get(dominante, C_AMBAR)
        st.markdown(
            f'<div class="ss-anotacion">Este análisis ha usado como referencia {ui.badge(dominante, color)} '
            f'({len(refs.get("peers_con_dato") or [])} comparables con múltiplos guardados al analizar; ahora hay {n_dato}). '
            f'Las medianas de la fila MEDIANA alimentan el PER forward, EV/EBITDA, EV/Ventas, P/B y P/FFO del Fair Value y las '
            f'métricas relativas de Calidad cuando hay al menos {core_referencias.REFERENCIA_PEERS_MIN} comparables con dato; '
            f'los cambios se aplican al volver a pulsar Analizar. Sugeridos = Finnhub (mismo país e industria: punto de partida, '
            f'no verdad); validados = confirmados por ti, simétricos. El ROIC de un comparable aparece cuando se ha analizado '
            f'alguna vez.</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1.2, 2, 1])
        if c1.button("Actualizar múltiplos", key=f"peer_refrescar_{ticker}", width="stretch", icon=":material/refresh:",
                     help=f"Vuelve a pedir los múltiplos de todos los comparables (si no, solo los de más de {MULTIPLOS_MAX_DIAS} días)"):
            st.session_state[f"peer_forzar_{ticker}"] = True
            st.rerun()
        abrir = c2.selectbox("Analizar comparable", peers, index=None, key=f"peer_abrir_{ticker}",
                             placeholder="Abrir un comparable en Análisis Individual…", label_visibility="collapsed")
        if c3.button("Analizar", key=f"peer_abrir_btn_{ticker}", width="stretch", disabled=abrir is None):
            st.session_state["ticker_pendiente"] = abrir
            ui_interfaz.ir_a("Análisis Individual")
            st.rerun()
        ui.frescura(None, "Finnhub (sugerencias) · yfinance (múltiplos) · Supabase (lista y múltiplos guardados)", "info")
