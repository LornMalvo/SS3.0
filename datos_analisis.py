"""Orquestación del análisis completo de un ticker: descarga (cacheada) +
motores en orden. Es la ÚNICA función que sabe en qué orden se encadenan
Calidad -> Fair Value -> Confluencia -> Plan DCA -> Timing -> veredicto, y
la usan tres consumidores: Análisis Individual (completo), el Rastreador
(modo ligero: sin noticias ni traducción, que no entran en ninguna nota) y
el cron (planes que hay que re-evaluar).

Cada análisis se persiste en `analisis_historico` deduplicado por
(ticker, fecha, versión de motor): el Rastreador alimenta así, sin coste
extra, la evaluación de señales (backtest sobre el histórico propio).
"""

from __future__ import annotations

from datetime import date

import streamlit as st

import core_analistas
import core_calidad
import core_cartera
import core_confluencia
import core_fair_value
import core_fundamentales
import core_indicadores
import core_plan_dca
import core_referencias
import core_timing
import datos_finnhub
import db_supabase
from config_settings import MOTOR_VERSION, PEERS_SUGERIDOS_MAX
from datos_cache import cubo_mercado
from datos_yfinance import (
    obtener_estados_financieros,
    obtener_historico,
    obtener_info,
    obtener_precio_actual,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _sector_real(sector: str | None) -> dict | None:
    """Medianas reales del sector (rastreo nocturno), una consulta por
    sector y hora: en un rastreo de 500 tickers se lee ~11 veces, no 500."""
    return db_supabase.leer_sector_referencias(sector)


def comparables_validos(ticker: str) -> list[dict]:
    """Comparables del ticker sin los rechazados: [{peer, origen}]."""
    return [c for c in db_supabase.listar_comparables(ticker) if c.get("origen") != "rechazado"]


def referencias_para(ticker: str, fund: dict, sembrar: bool = False) -> tuple[dict, list[dict]]:
    """(referencias de core_referencias, comparables usados). Si `sembrar` y
    el ticker no tiene comparables guardados (ni rechazados), se siembran
    las sugerencias de Finnhub, que el usuario edita en el bloque peer to
    peer. Las medianas salen de los múltiplos YA guardados de los
    comparables (`multiplos`): cero peticiones a Yahoo aquí; el bloque de
    comparables es quien los refresca cuando están viejos."""
    comps = db_supabase.listar_comparables(ticker)
    if sembrar and not comps:
        sugeridos = datos_finnhub.obtener_peers(ticker)
        if sugeridos.ok:
            db_supabase.sembrar_comparables(ticker, sugeridos.valor[:PEERS_SUGERIDOS_MAX])
            comps = db_supabase.listar_comparables(ticker)
    validos = [c for c in comps if c.get("origen") != "rechazado"]
    filas = db_supabase.leer_multiplos(tuple(c["peer"] for c in validos)) if validos else {}
    peers_valores = [f.get("valores") or {} for f in filas.values()]
    refs = core_referencias.construir(fund.get("sector"), fund.get("industria"), peers_valores,
                                      _sector_real(fund.get("sector")))
    refs["peers_con_dato"] = sorted(filas)
    return refs, validos


def fila_multiplos(ticker: str, info: dict | None, fund: dict) -> dict:
    """Fila para `multiplos`: lo que este ticker aporta como comparable."""
    info = info or {}
    return {"ticker": ticker, "nombre": info.get("shortName") or info.get("longName"),
            "sector": fund.get("sector"), "industria": fund.get("industria"),
            "divisa": fund.get("divisa_cotizacion") or fund.get("divisa"),
            "valores": core_referencias.multiplos_de(fund)}


def analizar(ticker: str, ligero: bool = False, persistir: bool = True, origen: str = "individual",
             posiciones: dict | None = None) -> dict | None:
    """Análisis completo. Orden de los motores: Calidad -> Fair Value ->
    Confluencia -> Plan DCA (necesita el FV para S3) -> Timing (necesita el
    plan para la cercanía a E1, los earnings para el riesgo binario y las
    revisiones de analistas) -> veredicto (calidad, upside y timing) ->
    narrativa e invalidación.
    `ligero` omite noticias y la siembra de comparables (no entran en
    ninguna nota); la traducción de la descripción ya es perezosa.
    `origen` ('individual' | 'rastreador' | 'cron') se guarda en el
    histórico: el Screener filtra por él. `posiciones` = {real: set, paper:
    set} precalculado por el cron para no consultar Supabase por ticker."""
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
    fund["crecimiento_bpa"] = core_fair_value.crecimiento_estimado(fund)
    referencias, comparables = referencias_para(ticker, fund, sembrar=not ligero)
    indicadores = core_indicadores.resumen(historico.valor)
    precio_ref = (precio.valor or {}).get("precio") or indicadores.get("precio")
    calidad = core_calidad.calcular(fund, estados.valor, referencias)
    fair_value = core_fair_value.calcular(fund, estados.valor, historico.valor, precio_ref, calidad["perfil"], referencias)
    earnings = datos_finnhub.obtener_earnings(ticker)
    recomendaciones = datos_finnhub.obtener_recomendaciones(ticker)
    analistas = core_analistas.resumen(recomendaciones.valor)
    confluencia = core_confluencia.calcular(historico.valor, indicadores, precio_ref)
    plan = core_plan_dca.plan(confluencia, indicadores, precio_ref, fair_value.get("fair_value"))
    timing = core_timing.calcular(historico.valor, indicadores, fund, calidad, fair_value, earnings.valor, plan, analistas)
    if posiciones is not None:
        posicion = {"real": ticker in posiciones.get("real", ()), "paper": ticker in posiciones.get("paper", ())}
    else:
        posicion = posicion_abierta(ticker)
    veredicto = core_plan_dca.veredicto(calidad.get("nota"), fair_value.get("upside_pct"), timing.get("nota"),
                                        posicion_abierta=posicion["real"] or posicion["paper"])
    a = {
        "posicion": posicion,
        "ticker": ticker,
        "cubo": cubo,
        "historico": historico,
        "info": info,
        "estados": estados,
        "precio": precio,
        "noticias": None if ligero else datos_finnhub.obtener_noticias(ticker),
        "earnings": earnings,
        "recomendaciones": recomendaciones,
        "analistas": analistas,
        "referencias": referencias,
        "comparables": comparables,
        "origen": origen,
        "fundamentales": fund,
        "indicadores": indicadores,
        "calidad": calidad,
        "fair_value": fair_value,
        "confluencia": confluencia,
        "plan": plan,
        "timing": timing,
        "veredicto": veredicto,
        "narrativa": core_plan_dca.narrativa(ticker, calidad, fair_value, timing, plan, veredicto,
                                             fund.get("divisa_cotizacion") or ""),
        "invalidacion": core_plan_dca.invalidacion(calidad, fair_value, plan, earnings.valor),
    }
    if persistir:
        db_supabase.guardar_analisis(fila_historico(a))
        if info.ok:
            db_supabase.guardar_multiplos(fila_multiplos(ticker, info.valor, fund))   # alimenta comparables y sector real
    return a


def posicion_abierta(ticker: str) -> dict:
    """¿Hay posición abierta en el ticker? En la cartera real (acciones > 0
    en el libro) o en Paper Trading (plan con entradas ejecutadas). Es lo que
    habilita el veredicto REDUCIR: sin posición no hay nada que reducir."""
    ops = db_supabase.listar_operaciones("real", ticker)
    plan = db_supabase.plan_activo_para(ticker)
    return {
        "real": core_cartera.disponibles(ops, ticker) > 0,
        "paper": plan is not None and plan.get("estado") in ("parcial_entrada", "abierta", "parcial_salida"),
    }


def fila_historico(a: dict) -> dict:
    """Fila para `analisis_historico` (deduplicada por ticker/fecha/versión).
    `entradas` guarda los fundamentales crudos: con ellos y la versión del
    motor la nota es reconstruible."""
    fv, cal, t, p = a["fair_value"], a["calidad"], a.get("timing") or {}, a.get("plan")
    info = (a["info"].valor if a.get("info") is not None and a["info"].ok else None) or {}
    return {
        "ticker": a["ticker"],
        "fecha_analisis": date.today().isoformat(),
        "motor_version": MOTOR_VERSION,
        "origen": a.get("origen") or "individual",
        "nombre": info.get("shortName") or info.get("longName"),
        "sector": a["fundamentales"].get("sector"),
        "timing_bruto": t.get("nota_bruta"),
        "banda": (fv.get("banda") or (None,))[0],
        "precio": fv.get("precio"),
        "divisa": a["fundamentales"].get("divisa_cotizacion"),
        "calidad": cal.get("nota"),
        "fair_value": fv.get("fair_value"),
        "upside_pct": fv.get("upside_pct"),
        "timing": t.get("nota"),
        "senal_timing": t["senal"][0] if t.get("senal") else None,
        "veredicto": (a.get("veredicto") or {}).get("etiqueta"),
        "perfil": cal.get("perfil"),
        "cobertura": {"calidad": cal.get("cobertura"), "fair_value": fv.get("cobertura"), "timing": t.get("cobertura")},
        "plan": ({"entradas": [(e["nivel"], e["precio"]) for e in p["entradas"]],
                  "salidas": [(s["nivel"], s["precio"]) for s in p["salidas"]], "stop": p["stop"]} if p else None),
        "entradas": {k: v for k, v in a["fundamentales"].items() if isinstance(v, (int, float, str)) or v is None},
    }
