"""Motor de Fair Value: ¿está barata?

Métodos de una sola multiplicación, sin DCF (ver justificación en el diseño
de la sesión 1 y en config_settings.FV_PESOS):
  A per_historico   mediana del PER propio (cierre de cada ejercicio) x BPA TTM
  B per_forward     PER forward mediano del sector x BPA forward
  C peg             PEG objetivo x crecimiento estimado (%) x BPA forward
  D ev_ebitda       EV/EBITDA sector x EBITDA, menos deuda, más caja, / acciones
  E ev_ventas       EV/Ventas sector (solo perfil pre_rentabilidad)
  consenso          precio objetivo medio de analistas (peso FIJO)

Flujo: métodos -> banda de cordura sobre ancla mixta -> ponderar() -> upside
-> banda de alerta. Sensibilidad = el mismo flujo con multiplicadores por
escenario. Función pura y reconstruible: recibe fundamentales, estados,
histórico y precio; devuelve el detalle de cada método (usado, recortado o
excluido y por qué).
"""

from __future__ import annotations

import statistics

import pandas as pd

import config_sectores as sec
from config_settings import (
    BANDAS_VALORACION,
    FV_BANDA_SUELO,
    FV_BANDA_TECHO,
    FV_CONSENSO_MIN_ANALISTAS,
    FV_ESCENARIOS,
    FV_EXCLUSION_SUELO,
    FV_EXCLUSION_TECHO,
    FV_PEG_CRECIMIENTO_MAX,
    FV_PEG_CRECIMIENTO_MIN,
    FV_PEG_OBJETIVO,
    FV_PER_HISTORICO_ANIOS,
    FV_PER_HISTORICO_INESTABILIDAD_MAX,
    FV_PER_HISTORICO_MIN_ANIOS,
    FV_PESOS,
    FV_PESOS_PRE_RENTABILIDAD,
    FV_UPSIDE_ANOMALIA,
    MOTOR_VERSION,
    PERFIL_PRE_RENTABILIDAD,
)
from core_calidad import serie
from core_ponderar import acotar, es_dato, ponderar

ETIQUETAS = {
    "per_historico": "A · PER histórico propio",
    "per_forward": "B · PER forward sector",
    "peg": "C · PEG",
    "ev_ebitda": "D · EV/EBITDA sector",
    "ev_ventas": "E · EV/Ventas sector",
    "consenso": "Consenso de analistas",
}


# ------------------------------------------------------------ entradas ------
def per_historico(estados: dict | None, historico: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Mediana del PER al cierre de cada ejercicio (precio de cierre del
    ejercicio / BPA diluido del ejercicio). None con motivo si no hay
    suficientes ejercicios rentables o la serie es inestable."""
    if not estados or historico is None or historico.empty:
        return None, "sin estados o histórico"
    res = estados.get("resultados")
    if res is None or res.empty:
        return None, "sin cuenta de resultados"
    fila = next((f for f in ("Diluted EPS", "Basic EPS") if f in res.index), None)
    if fila is None:
        return None, "sin BPA en los estados"
    pers = []
    for fecha, bpa in list(res.loc[fila].items())[:FV_PER_HISTORICO_ANIOS]:
        if not es_dato(bpa) or bpa <= 0:
            continue
        cierre = historico.loc[:pd.Timestamp(fecha)]
        if cierre.empty:
            continue
        pers.append(float(cierre["Close"].iloc[-1]) / float(bpa))
    if len(pers) < FV_PER_HISTORICO_MIN_ANIOS:
        return None, f"menos de {FV_PER_HISTORICO_MIN_ANIOS} ejercicios con BPA positivo"
    if max(pers) / min(pers) > FV_PER_HISTORICO_INESTABILIDAD_MAX:
        return None, f"serie de PER inestable (máx/mín {max(pers) / min(pers):.1f}x)"
    return statistics.median(pers), None


def crecimiento_estimado(fund: dict) -> float | None:
    """Crecimiento del BPA implícito en las estimaciones (forward / TTM). Solo
    tiene sentido con ambos positivos."""
    ttm, fwd = fund.get("bpa_ttm"), fund.get("bpa_forward")
    if es_dato(ttm) and es_dato(fwd) and ttm > 0 and fwd > 0:
        return fwd / ttm - 1
    return None


# ------------------------------------------------------------- métodos ------
def _metodos(fund: dict, estados: dict | None, historico: pd.DataFrame | None, perfil: str,
             escenario: dict) -> tuple[dict[str, float | None], dict[str, str]]:
    sector = fund.get("sector")
    industria = fund.get("industria")
    reit = industria in sec.INDUSTRIAS_REIT
    f_mult, f_crec = escenario["multiplo"], escenario["crecimiento"]
    acciones = fund.get("acciones")
    deuda, caja = fund.get("deuda_total") or 0.0, fund.get("caja_total") or 0.0
    v: dict[str, float | None] = {}
    motivos: dict[str, str] = {}

    def desde_ev(ev_justo: float) -> float | None:
        if not es_dato(acciones) or acciones <= 0:
            return None
        equity = ev_justo - deuda + caja
        return equity / acciones if equity > 0 else None

    if perfil == PERFIL_PRE_RENTABILIDAD:
        mult = sec.EV_VENTAS_SECTOR.get(sector)
        ingresos = fund.get("ingresos_ttm")
        if es_dato(mult) and es_dato(ingresos) and ingresos > 0:
            v["ev_ventas"] = desde_ev(mult * f_mult * ingresos)
            if v["ev_ventas"] is None:
                motivos["ev_ventas"] = "valor de los fondos propios no positivo o sin nº de acciones"
        else:
            v["ev_ventas"] = None
            motivos["ev_ventas"] = "sin ingresos o sin referencia sectorial"
    else:
        bpa_ttm, bpa_fwd = fund.get("bpa_ttm"), fund.get("bpa_forward")
        if reit:
            for k in ("per_historico", "per_forward", "peg"):
                v[k] = None
                motivos[k] = "REIT: el BPA GAAP no es magnitud válida (pendiente P/FFO)"
        else:
            per_h, motivo = per_historico(estados, historico)
            if per_h is not None and es_dato(bpa_ttm) and bpa_ttm > 0:
                v["per_historico"] = per_h * f_mult * bpa_ttm
            else:
                v["per_historico"] = None
                motivos["per_historico"] = motivo or "BPA TTM no positivo"

            per_f = sec.PER_FORWARD_SECTOR.get(sector)
            if es_dato(per_f) and es_dato(bpa_fwd) and bpa_fwd > 0:
                v["per_forward"] = per_f * f_mult * bpa_fwd
            else:
                v["per_forward"] = None
                motivos["per_forward"] = "BPA forward no positivo" if es_dato(bpa_fwd) else "sin BPA forward o sin sector"

            g = crecimiento_estimado(fund)
            if g is None:
                v["peg"] = None
                motivos["peg"] = "crecimiento no estimable (BPA TTM o forward no positivos)"
            elif g * f_crec < FV_PEG_CRECIMIENTO_MIN:
                v["peg"] = None
                motivos["peg"] = f"crecimiento {g * 100:.0f} % por debajo del mínimo ({FV_PEG_CRECIMIENTO_MIN * 100:.0f} %)"
            else:
                g_ef = acotar(g * f_crec, FV_PEG_CRECIMIENTO_MIN, FV_PEG_CRECIMIENTO_MAX)
                v["peg"] = FV_PEG_OBJETIVO * (g_ef * 100) * bpa_fwd

    mult = sec.EV_EBITDA_SECTOR.get(sector)
    ebitda = fund.get("ebitda")
    if es_dato(mult) and es_dato(ebitda) and ebitda > 0:
        v["ev_ebitda"] = desde_ev(mult * f_mult * ebitda)
        if v["ev_ebitda"] is None:
            motivos["ev_ebitda"] = "valor de los fondos propios no positivo o sin nº de acciones"
    else:
        v["ev_ebitda"] = None
        motivos["ev_ebitda"] = "EBITDA no positivo" if es_dato(ebitda) else "sin EBITDA o sin sector"

    n = fund.get("n_analistas")
    clave_obj = {"bajo": "objetivo_bajo", "medio": "objetivo_medio", "alto": "objetivo_alto"}[escenario["consenso"]]
    obj = fund.get(clave_obj)
    if es_dato(n) and n >= FV_CONSENSO_MIN_ANALISTAS and es_dato(obj) and obj > 0:
        v["consenso"] = obj
    else:
        v["consenso"] = None
        motivos["consenso"] = (f"menos de {FV_CONSENSO_MIN_ANALISTAS} analistas" if es_dato(n) else "sin cobertura de analistas")
    return v, motivos


def _banda_cordura(valores: dict[str, float | None]) -> tuple[dict[str, float | None], dict[str, str]]:
    """Ancla mixta = mediana de todos los métodos disponibles (propios +
    consenso). Cada método propio se usa, se recorta al borde o se excluye
    según su distancia al ancla. El consenso no se recorta: ya está dentro
    del ancla y su sesgo se corrige con la asimetría de la banda."""
    disponibles = {k: x for k, x in valores.items() if es_dato(x) and x > 0}
    estados: dict[str, str] = {}
    if len(disponibles) < 2:
        return valores, {k: "usado" for k in disponibles}
    ancla = statistics.median(disponibles.values())
    ajustados = dict(valores)
    for k, x in disponibles.items():
        if k == "consenso":
            estados[k] = "usado"
            continue
        ratio = x / ancla
        if FV_BANDA_SUELO <= ratio <= FV_BANDA_TECHO:
            estados[k] = "usado"
        elif FV_EXCLUSION_SUELO <= ratio <= FV_EXCLUSION_TECHO:
            ajustados[k] = ancla * (FV_BANDA_SUELO if ratio < 1 else FV_BANDA_TECHO)
            estados[k] = "recortado"
        else:
            ajustados[k] = None
            estados[k] = "excluido"
    return ajustados, estados


def banda_valoracion(upside_pct: float | None) -> tuple[str, str] | None:
    if not es_dato(upside_pct):
        return None
    for minimo, maximo, etiqueta, color in BANDAS_VALORACION:
        if (minimo is None or upside_pct >= minimo) and (maximo is None or upside_pct < maximo):
            return etiqueta, color
    return None


def _valorar(fund, estados, historico, precio, perfil, escenario) -> dict:
    brutos, motivos = _metodos(fund, estados, historico, perfil, escenario)
    ajustados, estados_banda = _banda_cordura(brutos)
    pesos = FV_PESOS_PRE_RENTABILIDAD if perfil == PERFIL_PRE_RENTABILIDAD else FV_PESOS
    componentes = {k: (p, ajustados.get(k)) for k, p in pesos.items()}
    p = ponderar(componentes, motivos={**motivos, **{k: "fuera de la banda de cordura" for k, e in estados_banda.items() if e == "excluido"}})
    fv = p.valor
    upside = (fv / precio - 1) * 100 if es_dato(fv) and es_dato(precio) and precio > 0 else None
    detalle = {}
    for k, peso in pesos.items():
        estado = estados_banda.get(k) or ("excluido" if brutos.get(k) is None else "usado")
        detalle[k] = {"etiqueta": ETIQUETAS[k], "bruto": brutos.get(k), "usado": ajustados.get(k),
                      "peso": peso, "peso_efectivo": p.usados.get(k), "estado": estado,
                      "motivo": p.excluidos.get(k)}
    return {"fair_value": fv, "upside_pct": upside, "cobertura": p.cobertura, "metodos": detalle}


def calcular(fund: dict, estados: dict | None, historico: pd.DataFrame | None, precio: float | None,
             perfil: str) -> dict:
    base = _valorar(fund, estados, historico, precio, perfil, FV_ESCENARIOS["base"])
    sensibilidad = {
        nombre: {k: r[k] for k in ("fair_value", "upside_pct")}
        for nombre, esc in FV_ESCENARIOS.items()
        for r in [base if nombre == "base" else _valorar(fund, estados, historico, precio, perfil, esc)]
    }
    avisos = []
    if fund.get("divisa") and (fund.get("divisa_cotizacion") or fund.get("divisa")) != fund.get("divisa"):
        avisos.append("La divisa de los estados financieros no coincide con la de cotización: revisar manualmente.")
    up = base["upside_pct"]
    if es_dato(up) and not (FV_UPSIDE_ANOMALIA[0] <= up <= FV_UPSIDE_ANOMALIA[1]):
        avisos.append("Upside fuera del rango razonable: resultado marcado para revisar manualmente.")
    return {
        **base,
        "precio": precio,
        "perfil": perfil,
        "banda": banda_valoracion(up),
        "sensibilidad": sensibilidad,
        "avisos": avisos,
        "anomalia": bool(avisos),
        "version": MOTOR_VERSION,
    }
