"""Evaluación periódica de alertas (sesión 5). Lo ejecuta GitHub Actions
(cron, ver .github/workflows/alertas.yml), fuera de Streamlit Cloud, que no
tiene planificador. Los módulos de la app funcionan sin runtime de Streamlit
(la caché degrada a memoria de proceso; Supabase es obligatorio: sin él no
hay nada que vigilar).

Flujo de cada pase:
  1. planes activos + ejecuciones y libro real desde Supabase
  2. UNA descarga por lote de precios (planes + cartera) y otra de cierres
     de un año en EUR para valorar la cartera y su momentum
  3. ejecución automática de los niveles de PAPER_AUTO_NIVELES alcanzados
     (mismo flujo que la vista: db_supabase.ejecutar_nivel_paper)
  4. reglas de core_alertas -> deduplicación en `alertas_enviadas` -> un
     único mensaje Telegram
  5. fuera de sesión (pase de cierre): resumen del día, una vez por fecha

`python tarea_alertas.py --prueba` envía un mensaje de conectividad;
`--simular` evalúa e imprime sin enviar ni registrar nada.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import pandas as pd

import config_secretos
import core_alertas
import core_cartera
import core_paper
import datos_telegram
import db_supabase
from config_settings import CARTERA_HISTORICO_DIAS, PAPER_CAPITAL_DEFECTO, PAPER_ESTADOS_ACTIVOS, PAPER_NIVELES_ENTRADA
from core_ponderar import es_dato
from datos_cache import cubo_mercado, es_sesion, mercado_abierto, ultima_sesion_cerrada
from datos_yfinance import fx_en_fecha, obtener_cierres_eur_lote, obtener_divisa, obtener_precios_lote


def _auto_ejecutar(planes: list[dict], ejec_por_plan: dict, precios: dict, simular: bool) -> set[tuple[int, str]]:
    """Dispara E1 (PAPER_AUTO_NIVELES) donde el precio lo haya alcanzado."""
    hechos: set[tuple[int, str]] = set()
    cubo = cubo_mercado()
    hoy = date.today()
    for a in core_paper.auto_ejecuciones(planes, ejec_por_plan, {t: (v or {}).get("precio") for t, v in precios.items()}):
        p, nivel, precio = a["plan"], a["nivel"], a["precio"]
        fx, _ = fx_en_fecha(p.get("divisa"), hoy, cubo)
        acciones = core_paper.acciones_para(p, nivel, precio, a["ejecuciones"], fx)
        if not es_dato(acciones) or acciones <= 0:
            continue
        primera = not (core_paper.ejecutadas(a["ejecuciones"]) & set(PAPER_NIVELES_ENTRADA))
        capital = float(p.get("capital_eur") or PAPER_CAPITAL_DEFECTO) if primera else None
        print(f"auto {p['ticker']} {nivel} a {precio:g} x {acciones:g}" + (" (simulado)" if simular else ""))
        if simular:
            hechos.add((p["id"], nivel))
            continue
        fila = db_supabase.ejecutar_nivel_paper(p, a["ejecuciones"], nivel, precio, hoy, acciones, fx, capital,
                                                automatica=True)
        if fila is not None:
            ejec_por_plan.setdefault(p["id"], []).append(fila)
            hechos.add((p["id"], nivel))
    return hechos


def _cartera(operaciones: list[dict]) -> tuple[dict, dict]:
    """Posiciones valoradas, con variación diaria y recomendación, y resumen."""
    posiciones = core_cartera.libro(operaciones)
    abiertas = [t for t, p in posiciones.items() if not p["cerrada"]]
    if not abiertas:
        return posiciones, core_cartera.resumen(posiciones)
    divisas = tuple(obtener_divisa(t) for t in abiertas)
    primera = min(pd.Timestamp(o["fecha"]).date() for o in operaciones)
    desde = min(primera, date.today() - timedelta(days=CARTERA_HISTORICO_DIAS)) - timedelta(days=7)
    lote = obtener_cierres_eur_lote(tuple(abiertas), divisas, desde.isoformat(), cubo_mercado())
    v = (lote.valor or {}) if lote.ok else {}
    core_cartera.valorar(posiciones, v.get("precios", {}))
    core_cartera.variacion_diaria(posiciones, v.get("cierres_nativos"), v.get("cierres"))
    ultimos = db_supabase.ultimos_analisis(tuple(abiertas))
    for t in abiertas:
        p = posiciones[t]
        p["momentum"] = core_cartera.momentum((v.get("cierres_nativos") or {}).get(t))
        p["recomendacion"] = core_cartera.recomendar(p.get("latente_pct"), p["momentum"], ultimos.get(t))
    return posiciones, core_cartera.resumen(posiciones)


def main() -> int:
    simular = "--simular" in sys.argv
    url, key = config_secretos.supabase()
    token, chat = config_secretos.telegram()
    print(f"Supabase configurado: {bool(url and key)} · Telegram configurado: {bool(token and chat)}")
    if "--prueba" in sys.argv:
        ok = datos_telegram.enviar("StockScanner: prueba de alertas OK")
        print(f"Mensaje de prueba enviado: {ok}")
        return 0
    if not db_supabase.disponible():
        print("Sin Supabase: nada que vigilar.")
        return 0

    hoy = date.today()
    planes = db_supabase.listar_planes_paper(PAPER_ESTADOS_ACTIVOS)
    ejecuciones = db_supabase.listar_ejecuciones_paper(tuple(p["id"] for p in planes))
    ejec_por_plan: dict[int, list[dict]] = {}
    for e in ejecuciones:
        ejec_por_plan.setdefault(e["plan_id"], []).append(e)
    planes = [p for p in planes if core_paper.estado(p, ejec_por_plan.get(p["id"], [])) in PAPER_ESTADOS_ACTIVOS]
    operaciones = db_supabase.listar_operaciones("real")

    tickers = tuple(sorted({p["ticker"] for p in planes}))
    lote = obtener_precios_lote(tickers, cubo_mercado()) if tickers else None
    precios = (lote.valor or {}) if lote is not None else {}
    print(f"{len(planes)} planes activos · {len(precios)} precios · {len(operaciones)} operaciones reales")

    auto = _auto_ejecutar(planes, ejec_por_plan, precios, simular)
    eventos = core_alertas.alertas_planes(planes, ejec_por_plan, precios, hoy, auto)

    posiciones, resumen = _cartera(operaciones)
    eventos += core_alertas.alertas_cartera(posiciones, hoy)
    # Resumen de cierre: solo con el mercado cerrado y una vez por sesión
    # (el pase de las 21:05 UTC es el primero tras el cierre).
    if not mercado_abierto() and es_sesion(hoy) and ultima_sesion_cerrada() == hoy:
        r = core_alertas.resumen_cierre(resumen, posiciones, hoy)
        if r:
            eventos.append(r)

    ya = db_supabase.alertas_ya_enviadas([e["clave"] for e in eventos])
    nuevos = [e for e in eventos if e["clave"] not in ya]
    print(f"{len(eventos)} eventos, {len(nuevos)} nuevos")
    if not nuevos:
        return 0
    mensaje = core_alertas.componer(sorted(nuevos, key=lambda e: e["prioridad"]))
    if simular:
        print(mensaje)
        return 0
    if datos_telegram.enviar(mensaje):
        for e in nuevos:
            db_supabase.registrar_alerta(e["tipo"], e["ticker"], e["clave"])
        print("Enviado y registrado.")
    else:
        print("No se pudo enviar por Telegram (no se registran las claves: se reintentará en el próximo pase).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
