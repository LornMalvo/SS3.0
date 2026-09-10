"""Motor de confluencia: ¿dónde están los soportes y resistencias que importan?

Cada candidato (media móvil, pivote, POC, diagonal, gap, extremo 52s,
Fibonacci, número redondo) es una gaussiana centrada en su precio, de
anchura SIGMA (medio ATR, acotado en % del precio) y altura igual a su peso
(config_settings.CONFLUENCIA_PESOS). Las ZONAS son los máximos locales de
la suma: donde varios candidatos coinciden la densidad se apila y la zona
sale fuerte; un candidato aislado deja una zona débil. No hay umbral binario
de "cluster": dos niveles a 0,3 ATR se funden solos, a 3 ATR no.

Funciones puras sobre (histórico OHLCV, indicadores, precio). El plan DCA
consume las zonas; la interfaz enseña qué candidatos componen cada una.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config_settings import (
    CONFLUENCIA_FUERTE,
    CONFLUENCIA_PESO_MIN_ZONA,
    CONFLUENCIA_PESOS,
    CONFLUENCIA_REJILLA,
    CONFLUENCIA_SIGMA_ATR,
    CONFLUENCIA_SIGMA_MAX_PCT,
    CONFLUENCIA_SIGMA_MIN_PCT,
    CONFLUENCIA_SIGMA_PCT_RESPALDO,
    DIAGONAL_MAX_POR_LADO,
    DIAGONAL_MIN_TOQUES,
    DIAGONAL_SESIONES,
    DIAGONAL_TOLERANCIA_ATR,
    GAP_MIN_PCT,
    NIVEL_REDONDO_MAX,
    PIVOTE_DECADENCIA_ANIOS,
    PIVOTE_DECADENCIA_MIN,
    PIVOTE_TOQUES_MULT,
    PIVOTE_VENTANA_DIARIA,
    PIVOTE_VENTANA_SEMANAL,
    VP_BANDAS,
    VP_SESIONES,
    VP_VALUE_AREA_PCT,
)
from core_indicadores import pivotes
from core_ponderar import acotar, es_dato

ETIQUETAS = {
    "mm50": "MM50", "mm100": "MM100", "mm200": "MM200",
    "pivote_diario": "pivote diario", "pivote_semanal": "pivote semanal",
    "poc": "POC (volumen)", "value_area": "value area",
    "diagonal": "directriz", "gap": "gap sin cerrar",
    "min_52s": "mínimo 52s", "max_52s": "máximo 52s",
    "fibonacci": "Fibonacci", "redondo": "nº redondo",
}


def _cand(tipo: str, precio: float, peso: float | None = None, detalle: str = "") -> dict:
    return {"tipo": tipo, "precio": float(precio), "peso": float(peso if peso is not None else CONFLUENCIA_PESOS[tipo]),
            "etiqueta": ETIQUETAS[tipo] + (f" {detalle}" if detalle else "")}


# ---------------------------------------------------------- candidatos -----
def _pivotes_agrupados(serie: pd.Series, tipo: str, tolerancia: float, fin: pd.Timestamp) -> list[dict]:
    """Agrupa pivotes cercanos (misma zona) y pondera cada grupo por nº de
    toques (crecimiento logarítmico) y por antigüedad del último toque."""
    if serie.empty:
        return []
    grupos: list[list[tuple[pd.Timestamp, float]]] = []
    for fecha, precio in sorted(serie.items(), key=lambda x: x[1]):
        if grupos and abs(precio - grupos[-1][-1][1]) <= tolerancia:
            grupos[-1].append((fecha, precio))
        else:
            grupos.append([(fecha, precio)])
    salida = []
    for g in grupos:
        toques = len(g)
        ultimo = max(f for f, _ in g)
        anios = max(0.0, (fin - ultimo).days / 365.25)
        decadencia = max(PIVOTE_DECADENCIA_MIN, 1 - (1 - PIVOTE_DECADENCIA_MIN) * anios / PIVOTE_DECADENCIA_ANIOS)
        peso = CONFLUENCIA_PESOS[tipo] * (1 + PIVOTE_TOQUES_MULT * math.log(toques)) * decadencia
        salida.append(_cand(tipo, float(np.mean([p for _, p in g])), peso,
                            f"({toques} toque{'s' if toques > 1 else ''})"))
    return salida


def _volume_profile(df: pd.DataFrame) -> list[dict]:
    """POC y value area (VP_VALUE_AREA_PCT del volumen alrededor del POC)
    sobre las últimas VP_SESIONES. El volumen de cada sesión se reparte por
    igual entre las bandas que cubre su rango High-Low."""
    d = df.iloc[-VP_SESIONES:]
    if len(d) < 60:
        return []
    lo, hi = float(d["Low"].min()), float(d["High"].max())
    if hi <= lo:
        return []
    bordes = np.linspace(lo, hi, VP_BANDAS + 1)
    vol = np.zeros(VP_BANDAS)
    h, l, v = d["High"].to_numpy(), d["Low"].to_numpy(), d["Volume"].fillna(0).to_numpy()
    for hi_i, lo_i, v_i in zip(h, l, v):
        i0 = int(np.searchsorted(bordes, lo_i, side="right") - 1)
        i1 = int(np.searchsorted(bordes, hi_i, side="right") - 1)
        i0, i1 = max(0, min(i0, VP_BANDAS - 1)), max(0, min(i1, VP_BANDAS - 1))
        vol[i0:i1 + 1] += v_i / (i1 - i0 + 1)
    if vol.sum() <= 0:
        return []
    centros = (bordes[:-1] + bordes[1:]) / 2
    poc = int(vol.argmax())
    # value area: expandir desde el POC hacia el lado con más volumen
    objetivo = VP_VALUE_AREA_PCT * vol.sum()
    a = b = poc
    acumulado = vol[poc]
    while acumulado < objetivo and (a > 0 or b < VP_BANDAS - 1):
        arriba = vol[b + 1] if b < VP_BANDAS - 1 else -1
        abajo = vol[a - 1] if a > 0 else -1
        if arriba >= abajo:
            b += 1
            acumulado += arriba
        else:
            a -= 1
            acumulado += abajo
    return [_cand("poc", centros[poc]),
            _cand("value_area", bordes[a], detalle="baja (VAL)"),
            _cand("value_area", bordes[b + 1], detalle="alta (VAH)")]


def _diagonales(df: pd.DataFrame, atr: float) -> list[dict]:
    """Directrices con >= DIAGONAL_MIN_TOQUES pivotes alineados (tolerancia
    en ATR) y al menos 60 sesiones entre el primer y el último toque,
    proyectadas a la sesión actual. Se conservan como mucho DIAGONAL_MAX_POR_LADO
    por lado (las de más toques), separadas entre sí más de 2 tolerancias:
    sin este tope, decenas de líneas casi iguales ahogaban al resto de
    candidatos."""
    d = df.iloc[-DIAGONAL_SESIONES:]
    if len(d) < 60 or not es_dato(atr) or atr <= 0:
        return []
    tol = DIAGONAL_TOLERANCIA_ATR * atr
    hoy = len(d) - 1
    pos = {f: i for i, f in enumerate(d.index)}
    salida = []
    for serie in pivotes(d, PIVOTE_VENTANA_DIARIA):
        puntos = [(pos[f], float(p)) for f, p in serie.items() if f in pos]
        if len(puntos) < DIAGONAL_MIN_TOQUES:
            continue
        lineas = []
        for i in range(len(puntos)):
            for j in range(i + 1, len(puntos)):
                (x0, y0), (x1, y1) = puntos[i], puntos[j]
                if x1 - x0 < 20:
                    continue
                m = (y1 - y0) / (x1 - x0)
                tocados = [x for x, y in puntos if abs(y - (y0 + m * (x - x0))) <= tol]
                if len(tocados) < DIAGONAL_MIN_TOQUES or max(tocados) - min(tocados) < 60:
                    continue
                proy = y0 + m * (hoy - x0)
                if proy > 0:
                    lineas.append((len(tocados), proy))
        elegidas: list[tuple[int, float]] = []
        for toques, proy in sorted(lineas, key=lambda t: -t[0]):
            if any(abs(proy - v) <= 2 * tol for _, v in elegidas):
                continue
            elegidas.append((toques, proy))
            if len(elegidas) >= DIAGONAL_MAX_POR_LADO:
                break
        for toques, proy in elegidas:
            salida.append(_cand("diagonal", proy, CONFLUENCIA_PESOS["diagonal"] * (1 + 0.15 * (toques - DIAGONAL_MIN_TOQUES)),
                                f"({toques} toques)"))
    return salida


def _gaps(df: pd.DataFrame) -> list[dict]:
    """Huecos de al menos GAP_MIN_PCT que el precio no ha vuelto a cubrir.
    El candidato se sitúa en el centro del hueco."""
    d = df.iloc[-VP_SESIONES:]
    if len(d) < 3:
        return []
    h, l = d["High"].to_numpy(), d["Low"].to_numpy()
    salida = []
    for t in range(1, len(d)):
        if l[t] > h[t - 1] * (1 + GAP_MIN_PCT):          # gap alcista
            a, b = h[t - 1], l[t]
            if (l[t + 1:] <= a).any() if t + 1 < len(d) else False:
                continue
            salida.append(_cand("gap", (a + b) / 2, detalle="alcista"))
        elif h[t] < l[t - 1] * (1 - GAP_MIN_PCT):        # gap bajista
            a, b = h[t], l[t - 1]
            if (h[t + 1:] >= b).any() if t + 1 < len(d) else False:
                continue
            salida.append(_cand("gap", (a + b) / 2, detalle="bajista"))
    return salida[-6:]


def _fibonacci(ind: dict) -> list[dict]:
    lo, hi = ind.get("min_52s"), ind.get("max_52s")
    if not es_dato(lo) or not es_dato(hi) or hi <= lo:
        return []
    return [_cand("fibonacci", hi - (hi - lo) * r, detalle=f"{r:.3f}") for r in (0.382, 0.5, 0.618)]


def _redondos(precio: float) -> list[dict]:
    """NIVEL_REDONDO_MAX niveles "psicológicos" más cercanos al precio, con
    un paso proporcional a su magnitud (200/250 para un valor de 207;
    45/50 para uno de 47)."""
    if precio <= 0:
        return []
    paso = 5 * 10 ** (math.floor(math.log10(precio)) - 1)
    base = math.floor(precio / paso) * paso
    niveles = sorted({base - paso, base, base + paso, base + 2 * paso}, key=lambda x: abs(x - precio))
    return [_cand("redondo", n) for n in niveles[:NIVEL_REDONDO_MAX] if n > 0]


def candidatos(df: pd.DataFrame, ind: dict, precio: float) -> list[dict]:
    atr = ind.get("atr")
    tol = (CONFLUENCIA_SIGMA_ATR * atr) if es_dato(atr) and atr > 0 else CONFLUENCIA_SIGMA_PCT_RESPALDO * precio
    fin = df.index[-1]
    c: list[dict] = []
    for k in ("mm50", "mm100", "mm200"):
        if es_dato(ind.get(k)):
            c.append(_cand(k, ind[k]))
    sop_d, res_d = pivotes(df.iloc[-VP_SESIONES:], PIVOTE_VENTANA_DIARIA)
    c += _pivotes_agrupados(pd.concat([sop_d, res_d]), "pivote_diario", tol, fin)
    semanal = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    sop_s, res_s = pivotes(semanal, PIVOTE_VENTANA_SEMANAL)
    c += _pivotes_agrupados(pd.concat([sop_s, res_s]), "pivote_semanal", tol, fin)
    c += _volume_profile(df)
    c += _diagonales(df, atr)
    c += _gaps(df)
    for k in ("min_52s", "max_52s"):
        if es_dato(ind.get(k)):
            c.append(_cand(k, ind[k]))
    c += _fibonacci(ind)
    c += _redondos(precio)
    return [x for x in c if es_dato(x["precio"]) and x["precio"] > 0]


# ---------------------------------------------------------------- zonas -----
def sigma_para(precio: float, atr: float | None) -> float:
    if es_dato(atr) and atr > 0:
        return acotar(CONFLUENCIA_SIGMA_ATR * atr, CONFLUENCIA_SIGMA_MIN_PCT * precio, CONFLUENCIA_SIGMA_MAX_PCT * precio)
    return CONFLUENCIA_SIGMA_PCT_RESPALDO * precio


def zonas(cands: list[dict], precio: float, sigma: float) -> list[dict]:
    """Máximos locales de la suma de gaussianas. Cada zona: precio (centro),
    fuerza (altura), lado (soporte/resistencia), distancia % al precio y
    los candidatos a menos de 1,5 sigma que la componen."""
    if not cands or sigma <= 0:
        return []
    precios = np.array([c["precio"] for c in cands])
    pesos = np.array([c["peso"] for c in cands])
    lo, hi = precios.min() - 3 * sigma, precios.max() + 3 * sigma
    x = np.linspace(lo, hi, CONFLUENCIA_REJILLA)
    dens = (pesos[None, :] * np.exp(-0.5 * ((x[:, None] - precios[None, :]) / sigma) ** 2)).sum(axis=1)
    picos = np.where((dens[1:-1] > dens[:-2]) & (dens[1:-1] >= dens[2:]) & (dens[1:-1] >= CONFLUENCIA_PESO_MIN_ZONA))[0] + 1
    salida = []
    for i in picos:
        centro = float(x[i])
        comp = [c for c in cands if abs(c["precio"] - centro) <= 1.5 * sigma]
        salida.append({
            "precio": centro,
            "fuerza": float(dens[i]),
            "fuerte": bool(dens[i] >= CONFLUENCIA_FUERTE),
            "lado": "soporte" if centro <= precio else "resistencia",
            "dist_pct": (centro / precio - 1) * 100,
            "componentes": sorted(comp, key=lambda c: -c["peso"]),
            "motivos": [c["etiqueta"] for c in sorted(comp, key=lambda c: -c["peso"])],
        })
    return sorted(salida, key=lambda z: z["precio"])


def calcular(df: pd.DataFrame, ind: dict, precio: float | None) -> dict:
    if df is None or df.empty or not es_dato(precio) or precio <= 0:
        return {"candidatos": [], "zonas": [], "sigma": None}
    cands = candidatos(df, ind, float(precio))
    sigma = sigma_para(float(precio), ind.get("atr"))
    return {"candidatos": cands, "zonas": zonas(cands, float(precio), sigma), "sigma": sigma}
