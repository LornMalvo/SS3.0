"""Motor de Gestión de Cartera. Todo se DERIVA del libro de operaciones
(`cartera_operaciones`): no hay estado redundante que pueda desincronizarse.

Funciones puras sobre listas de dicts y DataFrames: sin Streamlit, sin red.
Las usa también Paper Trading (operaciones con origen 'paper'), así el
rendimiento simulado y el real salen del mismo código.

Dos costes medios, a propósito:
- PONDERADO: (suma de compras + comisiones) / acciones. Es el que se enseña
  en la ficha y sobre el que trabaja el stop del plan DCA.
- FIFO: las primeras acciones compradas son las primeras que salen. Es el
  que manda en el beneficio REALIZADO (criterio fiscal español).
Las comisiones de compra se capitalizan en el coste; las de venta restan del
realizado. Divisa base EUR: aquí ya no hay divisas, entran `precio_eur`.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from config_settings import (
    CARTERA_CORRELACION_ALTA,
    CARTERA_CORRELACION_MIN_SESIONES,
    CARTERA_PESO_ALERTA,
    CARTERA_RECO_AMPLIAR_MAX,
    CARTERA_RECO_GANANCIA_PARCIAL,
    CARTERA_RECO_GANANCIA_PROTEGER,
    CARTERA_RECO_PERDIDA_REDUCIR,
    CARTERA_RECO_PERDIDA_VENDER,
    CARTERA_SECTOR_ALERTA,
    CARTERA_TOLERANCIA_ACCIONES,
    INDICADOR_VENTANAS,
    MOMENTUM_MIN_SESIONES,
    MOMENTUM_NIVELES,
    MOMENTUM_RSI_SOBRECOMPRA,
    MOMENTUM_TRAMOS,
    RECO_VEREDICTOS_VETO_AMPLIAR,
    RECOMENDACIONES,
)
from core_indicadores import macd, media_movil, rsi
from core_ponderar import es_dato, puntuar_tramos


def _f(v, defecto: float = 0.0) -> float:
    return float(v) if es_dato(v) else defecto


def _fecha(v) -> date:
    if isinstance(v, date):
        return v
    return pd.Timestamp(v).date()


# -------------------------------------------------------------------- libro --
def _posicion_vacia(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "acciones": 0.0,
        "coste_medio_eur": None,     # ponderado, con comisiones de compra
        "coste_total_eur": 0.0,      # acciones * coste_medio
        "invertido_eur": 0.0,        # todo lo que ha entrado en compras (histórico)
        "comisiones_eur": 0.0,
        "realizado_fifo_eur": 0.0,
        "lotes": [],                 # FIFO: [{fecha, acciones, precio_eur (con comisión prorrateada)}]
        "n_compras": 0,
        "n_ventas": 0,
        "primera_fecha": None,
        "ultima_fecha": None,
        "cerrada": True,
    }


def _comprar(pos: dict, op: dict) -> None:
    acc, precio, com = _f(op["acciones"]), _f(op["precio_eur"]), _f(op.get("comision_eur"))
    importe = acc * precio + com
    pos["coste_total_eur"] += importe
    pos["acciones"] += acc
    pos["coste_medio_eur"] = pos["coste_total_eur"] / pos["acciones"]
    pos["invertido_eur"] += importe
    pos["comisiones_eur"] += com
    pos["n_compras"] += 1
    pos["lotes"].append({"fecha": _fecha(op["fecha"]), "acciones": acc, "precio_eur": importe / acc if acc else precio})


def _vender(pos: dict, op: dict) -> None:
    """Venta: el coste medio ponderado no cambia (solo salen acciones); el
    realizado sale del FIFO. Una venta mayor que la posición se recorta a
    lo que hay (la interfaz ya la bloquea antes de insertarla)."""
    acc = min(_f(op["acciones"]), pos["acciones"])
    precio, com = _f(op["precio_eur"]), _f(op.get("comision_eur"))
    coste_fifo, restante = 0.0, acc
    while restante > CARTERA_TOLERANCIA_ACCIONES and pos["lotes"]:
        lote = pos["lotes"][0]
        tomo = min(lote["acciones"], restante)
        coste_fifo += tomo * lote["precio_eur"]
        lote["acciones"] -= tomo
        restante -= tomo
        if lote["acciones"] <= CARTERA_TOLERANCIA_ACCIONES:
            pos["lotes"].pop(0)
    pos["realizado_fifo_eur"] += acc * precio - com - coste_fifo
    pos["comisiones_eur"] += com
    pos["acciones"] -= acc
    if pos["acciones"] <= CARTERA_TOLERANCIA_ACCIONES:
        pos["acciones"] = 0.0
        pos["coste_total_eur"] = 0.0
        pos["lotes"] = []
    else:
        pos["coste_total_eur"] = pos["acciones"] * (pos["coste_medio_eur"] or 0.0)
    pos["n_ventas"] += 1


def orden_cronologico(operaciones: list[dict]) -> list[dict]:
    """Orden (fecha, id). El id desempata dentro del mismo día; los ids en
    memoria (sin Supabase) son negativos y crecen en valor absoluto, de ahí
    el abs(): sin él, una venta registrada después de la compra del mismo
    día se procesaría antes y el FIFO no encontraría lote que vender."""
    return sorted(operaciones, key=lambda o: (str(o.get("fecha")), abs(o.get("id") or 0)))


def libro(operaciones: list[dict]) -> dict[str, dict]:
    """Reproduce el libro en orden cronológico y devuelve ticker -> posición."""
    posiciones: dict[str, dict] = {}
    for op in orden_cronologico(operaciones):
        t = op["ticker"]
        pos = posiciones.setdefault(t, _posicion_vacia(t))
        f = _fecha(op["fecha"])
        pos["primera_fecha"] = pos["primera_fecha"] or f
        pos["ultima_fecha"] = f
        if op["tipo"] == "compra":
            _comprar(pos, op)
        else:
            _vender(pos, op)
        pos["cerrada"] = pos["acciones"] <= CARTERA_TOLERANCIA_ACCIONES
    return posiciones


def disponibles(operaciones: list[dict], ticker: str) -> float:
    """Acciones que se pueden vender hoy de un ticker (bloqueo de sobreventa)."""
    pos = libro([o for o in operaciones if o.get("ticker") == ticker]).get(ticker)
    return pos["acciones"] if pos else 0.0


# --------------------------------------------------------------- valoración --
def valorar(posiciones: dict[str, dict], precios_eur: dict[str, float | None]) -> dict[str, dict]:
    """Añade valor actual, latente y peso a cada posición ABIERTA. Sin precio
    en EUR (ticker sin dato o divisa no convertible) el valor queda None y la
    posición no entra en los pesos: nunca se inventa un cero."""
    abiertas = {t: p for t, p in posiciones.items() if not p["cerrada"]}
    for p in abiertas.values():
        precio = precios_eur.get(p["ticker"])
        if es_dato(precio):
            p["precio_eur"] = float(precio)
            p["valor_eur"] = p["acciones"] * float(precio)
            p["latente_eur"] = p["valor_eur"] - p["coste_total_eur"]
            p["latente_pct"] = (p["latente_eur"] / p["coste_total_eur"] * 100) if p["coste_total_eur"] else None
        else:
            p["precio_eur"] = p["valor_eur"] = p["latente_eur"] = p["latente_pct"] = None
    total = sum(p["valor_eur"] for p in abiertas.values() if es_dato(p.get("valor_eur")))
    for p in abiertas.values():
        p["peso_pct"] = (p["valor_eur"] / total * 100) if total and es_dato(p.get("valor_eur")) else None
        p["peso_alto"] = es_dato(p.get("peso_pct")) and p["peso_pct"] / 100 >= CARTERA_PESO_ALERTA
    return posiciones


def resumen(posiciones: dict[str, dict]) -> dict:
    """Totales de la cartera. `retorno_total_pct` es (latente + realizado)
    sobre todo lo invertido históricamente: una sola cifra de "cómo va"."""
    abiertas = [p for p in posiciones.values() if not p["cerrada"]]
    con_precio = [p for p in abiertas if es_dato(p.get("valor_eur"))]
    coste = sum(p["coste_total_eur"] for p in abiertas)
    valor = sum(p["valor_eur"] for p in con_precio)
    latente = sum(p["latente_eur"] for p in con_precio)
    realizado = sum(p["realizado_fifo_eur"] for p in posiciones.values())
    invertido = sum(p["invertido_eur"] for p in posiciones.values())
    comisiones = sum(p["comisiones_eur"] for p in posiciones.values())
    return {
        "n_abiertas": len(abiertas),
        "n_cerradas": sum(1 for p in posiciones.values() if p["cerrada"]),
        "n_sin_precio": len(abiertas) - len(con_precio),
        "coste_eur": coste,
        "valor_eur": valor if con_precio else None,
        "latente_eur": latente if con_precio else None,
        "latente_pct": (latente / sum(p["coste_total_eur"] for p in con_precio) * 100)
                        if con_precio and sum(p["coste_total_eur"] for p in con_precio) else None,
        "realizado_eur": realizado,
        "invertido_eur": invertido,
        "comisiones_eur": comisiones,
        # Con todo cerrado no hay latente pero sí un resultado: se informa igual.
        "retorno_total_pct": ((latente + realizado) / invertido * 100) if invertido and (con_precio or not abiertas) else None,
    }


# -------------------------------------------------------------- benchmark ----
def curva_vs_benchmark(operaciones: list[dict], cierres_eur: pd.DataFrame,
                       bench_eur: pd.Series | None) -> pd.DataFrame | None:
    """Curva diaria del valor de la cartera frente a una "cartera sombra"
    que hace EXACTAMENTE los mismos movimientos en el benchmark: cada compra
    de X EUR compra X EUR de SPY ese día; cada venta de una fracción de la
    posición vende la misma fracción de su sombra. Así se compara el mismo
    dinero en las mismas fechas (money-weighted), no dos índices base 100.

    Columnas: cartera, benchmark, invertido (coste vivo). None sin datos."""
    if not operaciones or cierres_eur is None or cierres_eur.empty or bench_eur is None or bench_eur.empty:
        return None
    ops = orden_cronologico(operaciones)
    inicio = pd.Timestamp(_fecha(ops[0]["fecha"]))
    idx = cierres_eur.index.union(bench_eur.index)
    idx = idx[idx >= inicio]
    if len(idx) == 0:
        return None
    cierres = cierres_eur.reindex(idx).ffill()
    bench = bench_eur.reindex(idx).ffill()

    acciones: dict[str, float] = {}
    sombra: dict[str, float] = {}      # unidades de benchmark por ticker
    coste: dict[str, float] = {}
    filas = []
    i_op = 0
    for dia in idx:
        while i_op < len(ops) and pd.Timestamp(_fecha(ops[i_op]["fecha"])) <= dia:
            op = ops[i_op]
            i_op += 1
            t, acc = op["ticker"], _f(op["acciones"])
            b = bench.get(dia)
            if op["tipo"] == "compra":
                importe = acc * _f(op["precio_eur"]) + _f(op.get("comision_eur"))
                acciones[t] = acciones.get(t, 0.0) + acc
                coste[t] = coste.get(t, 0.0) + importe
                if es_dato(b) and b:
                    sombra[t] = sombra.get(t, 0.0) + importe / float(b)
            else:
                tenia = acciones.get(t, 0.0)
                if tenia <= CARTERA_TOLERANCIA_ACCIONES:
                    continue
                frac = min(acc, tenia) / tenia
                acciones[t] = tenia * (1 - frac)
                coste[t] = coste.get(t, 0.0) * (1 - frac)
                sombra[t] = sombra.get(t, 0.0) * (1 - frac)
                if acciones[t] <= CARTERA_TOLERANCIA_ACCIONES:
                    acciones[t] = coste[t] = sombra[t] = 0.0
        valor = 0.0
        for t, n in acciones.items():
            if n <= 0 or t not in cierres.columns:
                continue
            c = cierres.at[dia, t]
            if es_dato(c):
                valor += n * float(c)
        b = bench.get(dia)
        filas.append({
            "fecha": dia,
            "cartera": valor,
            "benchmark": sum(sombra.values()) * float(b) if es_dato(b) else np.nan,
            "invertido": sum(coste.values()),
        })
    df = pd.DataFrame(filas).set_index("fecha")
    return df if not df.empty else None


def retorno_curva(df: pd.DataFrame | None) -> dict:
    """Retorno final de cada curva sobre el coste vivo (misma base para ambas)."""
    if df is None or df.empty:
        return {"cartera_pct": None, "benchmark_pct": None, "diferencia_pp": None}
    ult = df.iloc[-1]
    inv = ult["invertido"]
    if not inv:
        return {"cartera_pct": None, "benchmark_pct": None, "diferencia_pp": None}
    c = (ult["cartera"] / inv - 1) * 100
    b = (ult["benchmark"] / inv - 1) * 100 if es_dato(ult["benchmark"]) else None
    return {"cartera_pct": c, "benchmark_pct": b, "diferencia_pp": (c - b) if es_dato(b) else None}


# ------------------------------------------------------------------ riesgo --
def exposicion_sector(posiciones: dict[str, dict], sectores: dict[str, str | None]) -> list[dict]:
    """Peso de cada sector sobre el valor de las posiciones abiertas con
    precio. Sin sector conocido -> "Sin sector" (no se inventa uno)."""
    abiertas = [p for p in posiciones.values() if not p["cerrada"] and es_dato(p.get("valor_eur"))]
    total = sum(p["valor_eur"] for p in abiertas)
    if not total:
        return []
    acum: dict[str, dict] = {}
    for p in abiertas:
        s = sectores.get(p["ticker"]) or "Sin sector"
        d = acum.setdefault(s, {"sector": s, "valor_eur": 0.0, "tickers": []})
        d["valor_eur"] += p["valor_eur"]
        d["tickers"].append(p["ticker"])
    out = sorted(acum.values(), key=lambda d: -d["valor_eur"])
    for d in out:
        d["peso_pct"] = d["valor_eur"] / total * 100
        d["alerta"] = d["peso_pct"] / 100 >= CARTERA_SECTOR_ALERTA
    return out


def correlacion(cierres: pd.DataFrame | None) -> tuple[pd.DataFrame | None, list[dict]]:
    """Correlación de rendimientos diarios entre posiciones (matriz) y lista
    de pares por encima del umbral "misma apuesta". Tickers con menos de
    CARTERA_CORRELACION_MIN_SESIONES sesiones comunes quedan fuera."""
    if cierres is None or cierres.empty or cierres.shape[1] < 2:
        return None, []
    rend = cierres.pct_change().dropna(how="all")
    rend = rend.dropna(axis=1, thresh=CARTERA_CORRELACION_MIN_SESIONES)
    if rend.shape[1] < 2:
        return None, []
    m = rend.corr(min_periods=CARTERA_CORRELACION_MIN_SESIONES)
    pares = []
    cols = list(m.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            v = m.at[a, b]
            if es_dato(v) and v >= CARTERA_CORRELACION_ALTA:
                pares.append({"a": a, "b": b, "corr": float(v)})
    pares.sort(key=lambda d: -d["corr"])
    return m, pares


# ------------------------------------------------------- variación diaria --
def variacion_diaria(posiciones: dict[str, dict], cierres_nativos: dict[str, pd.Series] | None,
                     cierres_eur: pd.DataFrame | None) -> dict[str, dict]:
    """Añade a cada posición abierta `var_dia_pct` (variación de la sesión en
    la divisa de cotización: es el movimiento del valor, sin ruido de divisa)
    y `var_dia_eur` (acciones x diferencia de cierres en EUR: lo que de
    verdad ha ganado o perdido hoy la posición, divisa incluida). En sesión
    la última fila del lote es el precio en vivo y la anterior el cierre de
    ayer; fuera de sesión son los dos últimos cierres."""
    for t, p in posiciones.items():
        if p["cerrada"]:
            continue
        p["var_dia_pct"] = p["var_dia_eur"] = None
        serie = (cierres_nativos or {}).get(t)
        if serie is not None and len(serie.dropna()) >= 2:
            v = serie.dropna()
            if v.iloc[-2]:
                p["var_dia_pct"] = float(v.iloc[-1] / v.iloc[-2] - 1) * 100
        if cierres_eur is not None and t in getattr(cierres_eur, "columns", []):
            v = cierres_eur[t].dropna()
            if len(v) >= 2:
                p["var_dia_eur"] = p["acciones"] * float(v.iloc[-1] - v.iloc[-2])
    return posiciones


# --------------------------------------------------------------- momentum --
def momentum(cierres: pd.Series | None) -> dict | None:
    """Índice de momentum 0-100 de un valor a partir de sus cierres diarios
    (divisa de cotización). Cinco componentes puntuados por tramos
    (MOMENTUM_TRAMOS) y promediados a partes iguales; nivel -2..+2 y etiqueta
    por MOMENTUM_NIVELES. None con menos de MOMENTUM_MIN_SESIONES cierres.
    El MACD se normaliza por el precio (histograma en % del cierre): aquí no
    hay ATR porque solo se dispone de cierres, y el orden de magnitud es el
    mismo que el del Timing para un ATR del 1-2 %."""
    if cierres is None:
        return None
    serie = cierres.dropna().astype(float)
    if len(serie) < MOMENTUM_MIN_SESIONES:
        return None
    df = pd.DataFrame({"Close": serie})
    precio = float(serie.iloc[-1])
    v = INDICADOR_VENTANAS
    mm50 = media_movil(df, v["mm50"]).iloc[-1]
    mm200 = media_movil(df, v["mm200"]).iloc[-1]
    hist = macd(df)["hist"].iloc[-1]
    crudos = {
        "rsi": float(rsi(df, v["rsi"]).iloc[-1]),
        "dist_mm50": (precio / mm50 - 1) * 100 if es_dato(mm50) and mm50 else None,
        "dist_mm200": (precio / mm200 - 1) * 100 if es_dato(mm200) and mm200 else None,
        "ret_20": (precio / float(serie.iloc[-21]) - 1) * 100 if len(serie) > 21 and serie.iloc[-21] else None,
        "macd": (hist / precio * 100) if es_dato(hist) and precio else None,
    }
    puntos = {k: puntuar_tramos(val, MOMENTUM_TRAMOS[k]) for k, val in crudos.items() if es_dato(val)}
    if not puntos:
        return None
    nota = sum(puntos.values()) / len(puntos)
    nivel, etiqueta = next((n, e) for minimo, n, e in MOMENTUM_NIVELES if nota >= minimo)
    return {"nota": nota, "nivel": nivel, "etiqueta": etiqueta, "componentes": crudos, "puntos": puntos,
            "sobrecompra": es_dato(crudos["rsi"]) and crudos["rsi"] >= MOMENTUM_RSI_SOBRECOMPRA}


# ---------------------------------------------------------- recomendación --
def recomendar(latente_pct: float | None, mom: dict | None, ultimo_analisis: dict | None = None) -> dict | None:
    """Qué hacer con una posición abierta. Matriz latente x momentum con
    motivo en una frase; el último veredicto guardado del ticker (si lo
    hay) solo actúa como veto sobre AMPLIAR. None sin latente o sin
    momentum: no se recomienda a ciegas.

    Por debajo del coste medio:
      pérdida <= VENDER  y momentum bajista fuerte -> VENDER (tesis técnica rota)
      pérdida <= REDUCIR y momentum bajista        -> REDUCIR (no promediar contra la tendencia)
      giro alcista confirmado                      -> AMPLIAR (promediar a la baja con la tendencia a favor)
      resto                                        -> ESPERAR
    Por encima del coste medio:
      momentum bajista fuerte                      -> REDUCIR (proteger lo ganado)
      ganancia >= PARCIAL con sobrecompra o giro   -> VENTA PARCIAL
      ganancia >= PROTEGER con momentum bajista    -> VENTA PARCIAL
      momentum alcista fuerte cerca del coste      -> AMPLIAR (piramidar)
      resto                                        -> MANTENER (dejar correr)"""
    if not es_dato(latente_pct) or not mom:
        return None
    nivel, etiqueta_mom = mom["nivel"], mom["etiqueta"]
    veredicto = (ultimo_analisis or {}).get("veredicto")
    veto = veredicto in RECO_VEREDICTOS_VETO_AMPLIAR

    def r(clave: str, motivo: str) -> dict:
        etiqueta, color = RECOMENDACIONES[clave]
        if clave == "ampliar" and veto:
            etiqueta, color = RECOMENDACIONES["esperar"]
            return {"clave": "esperar", "etiqueta": etiqueta, "color": color,
                    "motivo": f"{motivo}; pero el último análisis dice {veredicto}: no se amplía lo que el motor no compraría hoy"}
        return {"clave": clave, "etiqueta": etiqueta, "color": color, "motivo": motivo}

    lat = f"{latente_pct:+.1f} %".replace(".", ",")
    if latente_pct < 0:
        if latente_pct <= CARTERA_RECO_PERDIDA_VENDER and nivel <= -2:
            return r("vender", f"pérdida {lat} con momentum {etiqueta_mom}: la tendencia no acompaña y la pérdida ya es grande")
        if latente_pct <= CARTERA_RECO_PERDIDA_REDUCIR and nivel <= -1:
            return r("reducir", f"pérdida {lat} con momentum {etiqueta_mom}: no conviene promediar contra la tendencia")
        if nivel >= 1:
            return r("ampliar", f"precio bajo el coste medio ({lat}) con momentum {etiqueta_mom}: promediar a la baja con la tendencia girada")
        if nivel <= -1:
            return r("esperar", f"pérdida {lat} contenida pero momentum {etiqueta_mom}: esperar a que gire antes de decidir")
        return r("esperar", f"pérdida {lat} con momentum {etiqueta_mom}: sin señal para ampliar ni para reducir")
    if nivel <= -2:
        return r("reducir", f"ganancia {lat} con momentum {etiqueta_mom}: proteger lo ganado antes de que se evapore")
    if latente_pct >= CARTERA_RECO_GANANCIA_PARCIAL and (mom.get("sobrecompra") or nivel <= -1):
        causa = "sobrecompra (RSI alto)" if mom.get("sobrecompra") else f"momentum {etiqueta_mom}"
        return r("venta_parcial", f"ganancia {lat} con {causa}: recoger una parte y dejar correr el resto")
    if latente_pct >= CARTERA_RECO_GANANCIA_PROTEGER and nivel <= -1:
        return r("venta_parcial", f"ganancia {lat} con momentum {etiqueta_mom}: asegurar parte del beneficio")
    if nivel >= 2 and latente_pct < CARTERA_RECO_AMPLIAR_MAX:
        return r("ampliar", f"ganancia {lat} cerca del coste con momentum {etiqueta_mom}: piramidar a favor de tendencia")
    return r("mantener", f"ganancia {lat} con momentum {etiqueta_mom}: la posición funciona, dejar correr")
