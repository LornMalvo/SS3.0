"""Referencias de múltiplos y márgenes (sesión 6). Un solo sitio decide
QUÉ referencia usa cada motor para "PER forward del sector", "EV/EBITDA del
sector", "ROIC del sector"..., con este orden de preferencia por clave:

  1. comparables  mediana de los comparables validados del ticker (tabla
                  `comparables` x múltiplos guardados en `multiplos`), si
                  hay al menos REFERENCIA_PEERS_MIN con dato
  2. sector real  mediana del sector calculada por el rastreo nocturno sobre
                  todo lo analizado (`sector_referencias`), si n >= REFERENCIA_SECTOR_MIN
  3. semilla      tabla de config_sectores (orden de magnitud)

Cada referencia sale con su fuente y su n, y los motores (Fair Value B/D/E/
P-B/P-FFO, Calidad relativa, panel de métricas) la enseñan tal cual. Así
la debilidad conocida de las tablas semilla se corrige sola conforme se
validan comparables y el cron rastrea índices.

Funciones puras: reciben dicts ya leídos de Supabase, no consultan nada.
"""

from __future__ import annotations

import statistics

import config_sectores as sec
from config_settings import REFERENCIA_PEERS_MIN, REFERENCIA_SECTOR_MIN, REIT_P_FFO_REFERENCIA
from core_ponderar import es_dato

# Claves que son múltiplos (solo cuentan valores positivos; un PER negativo
# no es un múltiplo, es una pérdida) frente a márgenes/retornos (cualquier
# valor cuenta).
MULTIPLOS = ("per_forward", "ev_ebitda", "ev_ventas", "precio_valor_contable", "p_ffo", "peg")
MARGENES = ("margen_bruto", "margen_operativo", "margen_neto", "roe", "roic", "deuda_neta_ebitda")
CLAVES = MULTIPLOS + MARGENES

FUENTE_PEERS = "comparables"
FUENTE_SECTOR_REAL = "sector real"
FUENTE_SEMILLA = "sector (semilla)"


def multiplos_de(fund: dict) -> dict:
    """Fila de `multiplos.valores` a partir de core_fundamentales.extraer:
    lo que un comparable aporta a las medianas."""
    deuda_neta_ebitda = None
    ebitda = fund.get("ebitda")
    if es_dato(ebitda) and ebitda > 0 and es_dato(fund.get("deuda_total")):
        deuda_neta_ebitda = (fund["deuda_total"] - (fund.get("caja_total") or 0.0)) / ebitda
    v = {k: fund.get(k) for k in CLAVES if es_dato(fund.get(k))}
    if deuda_neta_ebitda is not None:
        v["deuda_neta_ebitda"] = deuda_neta_ebitda
    for k in ("capitalizacion", "bpa_forward", "crecimiento_bpa"):
        if es_dato(fund.get(k)):
            v[k] = fund[k]
    return v


def mediana(valores: list, clave: str) -> tuple[float | None, int]:
    """(mediana, n) ignorando None y, en múltiplos, valores no positivos."""
    xs = [float(x) for x in valores if es_dato(x)]
    if clave in MULTIPLOS:
        xs = [x for x in xs if x > 0]
    if not xs:
        return None, 0
    return statistics.median(xs), len(xs)


def medianas(filas: list[dict]) -> dict[str, dict]:
    """{clave: {mediana, n}} sobre una lista de `valores` de la tabla multiplos."""
    out = {}
    for clave in CLAVES:
        m, n = mediana([f.get(clave) for f in filas], clave)
        if m is not None:
            out[clave] = {"mediana": m, "n": n}
    return out


def construir(sector: str | None, industria: str | None, peers_valores: list[dict] | None,
              sector_real: dict | None) -> dict:
    """Referencias por clave con su fuente:
    {clave: {"valor": x, "fuente": ..., "n": n}} + resumen de qué escalón
    domina, para etiquetar el bloque entero."""
    refs: dict[str, dict] = {}
    peers_med = medianas(peers_valores or [])
    real = (sector_real or {}).get("referencias") or {}
    for clave in CLAVES:
        p = peers_med.get(clave)
        if p and p["n"] >= REFERENCIA_PEERS_MIN:
            refs[clave] = {"valor": p["mediana"], "fuente": FUENTE_PEERS, "n": p["n"]}
            continue
        r = real.get(clave)
        if r and es_dato(r.get("mediana")) and int(r.get("n") or 0) >= REFERENCIA_SECTOR_MIN:
            refs[clave] = {"valor": float(r["mediana"]), "fuente": FUENTE_SECTOR_REAL, "n": int(r["n"])}
            continue
        semilla = sec.REFERENCIAS_SEMILLA.get(clave, {}).get(sector) if sector else None
        if clave == "p_ffo" and industria in sec.INDUSTRIAS_REIT:
            semilla = REIT_P_FFO_REFERENCIA
        if es_dato(semilla):
            refs[clave] = {"valor": float(semilla), "fuente": FUENTE_SEMILLA, "n": 0}
    fuentes = {r["fuente"] for r in refs.values()}
    if FUENTE_PEERS in fuentes:
        dominante = FUENTE_PEERS
    elif FUENTE_SECTOR_REAL in fuentes:
        dominante = FUENTE_SECTOR_REAL
    else:
        dominante = FUENTE_SEMILLA
    return {"por_clave": refs, "dominante": dominante, "n_peers": len(peers_valores or []), "sector": sector}


def valor(refs: dict | None, clave: str) -> float | None:
    r = ((refs or {}).get("por_clave") or {}).get(clave)
    return r["valor"] if r else None


def etiqueta(refs: dict | None, clave: str, fmt=None) -> str | None:
    """"comparables (5) 22,4" / "sector real (31) 18,0" / "sector (semilla) 20,0"."""
    r = ((refs or {}).get("por_clave") or {}).get(clave)
    if not r:
        return None
    fmt = fmt or (lambda v: f"{v:.1f}".replace(".", ","))
    n = f" ({r['n']})" if r["n"] else ""
    return f"{r['fuente']}{n} {fmt(r['valor'])}"


def solo_semilla(sector: str | None, industria: str | None = None) -> dict:
    """Referencias sin comparables ni sector real (rastreador ligero, tests)."""
    return construir(sector, industria, None, None)
