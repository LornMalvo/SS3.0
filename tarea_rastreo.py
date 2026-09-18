"""Rastreo nocturno de índices enteros (sesión 6). Lo ejecuta GitHub Actions
(cron, ver .github/workflows/rastreo.yml) fuera de Streamlit Cloud, igual
que tarea_alertas.py. Sin prisa: nadie está esperando, así que se recorre el
índice en serie con pausas y se aborta si Yahoo corta el grifo.

Flujo de cada pase:
  1. asegura que todos los índices de config_settings.INDICES existen en
     `rastreador_indices` (activos o no: se activan desde la app)
  2. por cada índice ACTIVO (o el de --indice): refresca sus constituyentes
     desde Wikipedia si tienen más de INDICES_REFRESCO_DIAS días
  3. analiza cada ticker con datos_analisis.analizar(ligero=True,
     origen="cron"): calidad, fair value, timing, plan y veredicto quedan en
     `analisis_historico` (el Screener del Rastreador filtra ahí, coste cero)
     y sus múltiplos en `multiplos`
  4. recalcula las medianas REALES por sector sobre toda la tabla `multiplos`
     (`sector_referencias`): sustituyen a la semilla de config_sectores en
     Fair Value, Calidad y panel de métricas cuando hay muestra suficiente
  5. deja constancia del pase en `rastreo_pases`

`--indice "S&P 500"` rastrea solo ese índice (aunque no esté activo);
`--max N` limita a N tickers (pruebas); `--simular` no escribe nada;
`--solo-referencias` salta el rastreo y solo recalcula las medianas.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

import core_cartera
import core_referencias
import datos_analisis
import datos_indices
import db_supabase
from config_settings import (
    INDICES,
    INDICES_REFRESCO_DIAS,
    PAPER_ESTADOS_ACTIVOS,
    RASTREO_CRON_MAX_ERRORES_SEGUIDOS,
    RASTREO_CRON_PAUSA_429_SEG,
    RASTREO_CRON_PAUSA_SEG,
    REFERENCIA_SECTOR_MIN,
)
from datos_yfinance import obtener_estados_financieros, obtener_historico, obtener_info

_LIMPIAR_CADA = 40   # tickers: vaciar la caché en memoria para no acumular 500 históricos


def _arg(nombre: str) -> str | None:
    if nombre in sys.argv:
        i = sys.argv.index(nombre)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    return None


def _viejo(actualizado_en) -> bool:
    if not actualizado_en:
        return True
    try:
        cuando = pd.Timestamp(actualizado_en).to_pydatetime()
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return datetime.now(timezone.utc) - cuando > timedelta(days=INDICES_REFRESCO_DIAS)


def _constituyentes(fila: dict, simular: bool) -> list[str]:
    """Tickers del índice, refrescados desde Wikipedia si toca."""
    if fila.get("tickers") and not _viejo(fila.get("actualizado_en")):
        return list(fila["tickers"])
    tickers, error = datos_indices.obtener_constituyentes(fila["nombre"])
    if not tickers:
        print(f"  {fila['nombre']}: no se pudieron refrescar los constituyentes ({error}); se usa la lista guardada")
        return list(fila.get("tickers") or [])
    print(f"  {fila['nombre']}: {len(tickers)} constituyentes refrescados desde Wikipedia")
    if not simular:
        db_supabase.guardar_indice(fila["nombre"], tickers=tickers)
    return tickers


def _posiciones() -> dict:
    """Tickers con posición abierta (real y paper), UNA vez por pase."""
    posiciones = core_cartera.libro(db_supabase.listar_operaciones("real"))
    real = {t for t, p in posiciones.items() if not p["cerrada"]}
    paper = {p["ticker"] for p in db_supabase.listar_planes_paper(PAPER_ESTADOS_ACTIVOS)
             if p.get("estado") in ("parcial_entrada", "abierta", "parcial_salida")}
    return {"real": real, "paper": paper}


def _limpiar_cache() -> None:
    for f in (obtener_historico, obtener_info, obtener_estados_financieros):
        try:
            f.clear()
        except Exception:
            pass


def rastrear(nombre: str, tickers: list[str], simular: bool, posiciones: dict) -> tuple[int, int, str, list[str]]:
    """Analiza en serie. Devuelve (ok, error, estado del pase, tickers fallidos)."""
    ok = err = seguidos = 0
    fallidos: list[str] = []
    estado = "completado"
    for i, t in enumerate(tickers, start=1):
        try:
            a = datos_analisis.analizar(t, ligero=True, persistir=not simular, origen="cron", posiciones=posiciones)
        except Exception as e:      # un fallo no para el pase
            print(f"  {t}: excepción {type(e).__name__}: {e}")
            a = None
        if a is None:
            err += 1
            seguidos += 1
            fallidos.append(t)
            print(f"  [{i}/{len(tickers)}] {t}: sin datos ({seguidos} seguidos)")
            if seguidos >= RASTREO_CRON_MAX_ERRORES_SEGUIDOS:
                print(f"  {seguidos} fallos seguidos: Yahoo ha cortado; se aborta el pase de {nombre}")
                estado = "abortado"
                break
            if seguidos % 5 == 0:   # posible límite de peticiones: pausa larga y seguir
                print(f"  pausa de {RASTREO_CRON_PAUSA_429_SEG} s por posible límite de Yahoo")
                time.sleep(RASTREO_CRON_PAUSA_429_SEG)
        else:
            ok += 1
            seguidos = 0
            v = (a.get("veredicto") or {}).get("etiqueta")
            print(f"  [{i}/{len(tickers)}] {t}: calidad {_n(a['calidad'].get('nota'))} · upside {_n(a['fair_value'].get('upside_pct'))} · "
                  f"timing {_n((a.get('timing') or {}).get('nota'))} · {v}")
        if i % _LIMPIAR_CADA == 0:
            _limpiar_cache()
        time.sleep(RASTREO_CRON_PAUSA_SEG)
    return ok, err, estado, fallidos


def _n(v) -> str:
    return f"{v:.0f}" if isinstance(v, (int, float)) else "—"


def recalcular_referencias(simular: bool) -> int:
    """Medianas reales por sector sobre toda la tabla `multiplos`. Solo se
    guardan los sectores con al menos REFERENCIA_SECTOR_MIN tickers."""
    filas = db_supabase.listar_multiplos_todos()
    por_sector: dict[str, list[dict]] = {}
    for f in filas:
        if f.get("sector"):
            por_sector.setdefault(f["sector"], []).append(f.get("valores") or {})
    salida = []
    for sector, valores in por_sector.items():
        if len(valores) < REFERENCIA_SECTOR_MIN:
            continue
        salida.append({"sector": sector, "referencias": core_referencias.medianas(valores), "n": len(valores)})
        print(f"  {sector}: {len(valores)} tickers · " + ", ".join(
            f"{k} {v['mediana']:.2f} (n={v['n']})" for k, v in salida[-1]["referencias"].items() if k in ("per_forward", "ev_ebitda", "roic")))
    if salida and not simular:
        db_supabase.guardar_sector_referencias(salida)
    return len(salida)


def main() -> int:
    simular = "--simular" in sys.argv
    solo_indice = _arg("--indice")
    maximo = int(_arg("--max") or 0) or None
    if not db_supabase.disponible():
        print("Sin Supabase: nada que rastrear.")
        return 0
    if "--solo-referencias" not in sys.argv:
        guardados = {f["nombre"]: f for f in db_supabase.listar_indices()}
        for nombre in INDICES:
            if nombre not in guardados:
                db_supabase.guardar_indice(nombre, tickers=[], activo=False)
                guardados[nombre] = {"nombre": nombre, "activo": False, "tickers": [], "actualizado_en": None}
        objetivo = [guardados[solo_indice]] if solo_indice and solo_indice in guardados else \
            [f for f in guardados.values() if f.get("activo")]
        if not objetivo:
            print("Ningún índice activo (actívalos en Rastreador > Rastreo nocturno) y sin --indice.")
        posiciones = _posiciones()
        for fila in objetivo:
            tickers = _constituyentes(fila, simular)
            if maximo:
                tickers = tickers[:maximo]
            print(f"{fila['nombre']}: {len(tickers)} tickers · {date.today()}" + (" (simulación)" if simular else ""))
            pase = None if simular else db_supabase.abrir_pase(fila["nombre"], len(tickers))
            inicio = time.time()
            ok, err, estado, fallidos = rastrear(fila["nombre"], tickers, simular, posiciones)
            print(f"{fila['nombre']}: {ok} ok, {err} sin datos, {estado} en {(time.time() - inicio) / 60:.0f} min")
            db_supabase.cerrar_pase(pase, estado, ok, err, {"fallidos": fallidos[:100]})
    print("Medianas reales por sector:")
    n = recalcular_referencias(simular)
    print(f"{n} sectores con muestra suficiente" + (" (simulación)" if simular else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
