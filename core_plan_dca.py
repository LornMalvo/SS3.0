"""Plan de inversión DCA y veredicto final.

Entradas: N1 es la zona de confluencia más fuerte por debajo del precio, SIN
separación mínima respecto a él (si hay confluencia fuerte pegada al precio,
ahí va). N2 y N3 son las zonas más fuertes por debajo del nivel anterior
menos una separación adaptativa (DCA_SEPARACION_ATR_ENTRADAS x ATR, acotada
en %). Si no queda zona en el rango de trabajo, el nivel se sintetiza a un
escalón de ATR y se marca como tal: el usuario ve qué niveles tienen
argumento técnico y cuáles son solo escalera.

Salidas: S1 y S2 son resistencias por encima del precio con la misma lógica
de separación; S3 se ancla al fair value salvo resistencia fuerte cerca, y
con tendencia fuerte confirmada (ADX >= DCA_SALIDA_ADX_TENDENCIA, +DI > -DI
y precio sobre la MM200) puede extenderse hasta DCA_SALIDA_EXTENSION_MAX x FV.

Stop: sobre el coste medio ponderado del plan (no sobre N1): la restricción
es "no arriesgo más de un X % de lo invertido", nunca choca con la escalera
y siempre queda DCA_STOP_MARGEN_ATR_BAJO_N3 x ATR por debajo de N3.

Veredicto: matriz con vetos, no media. Calidad < 60 veta la compra; con
calidad, decide el upside del fair value y, si hay margen, el timing.
Etiquetas de dos palabras; la narrativa va aparte.
"""

from __future__ import annotations

from datetime import date

from config_settings import (
    CALIDAD_MINIMA_TIMING,
    DCA_PESOS_ENTRADA,
    DCA_PESOS_SALIDA,
    DCA_RANGO_ATR,
    DCA_RANGO_ENTRADAS_MAX_PCT,
    DCA_RANGO_ENTRADAS_MIN_PCT,
    DCA_RANGO_SALIDAS_MAX_PCT,
    DCA_RANGO_SALIDAS_MIN_PCT,
    DCA_SALIDA_ADX_TENDENCIA,
    DCA_SALIDA_EXTENSION_MAX,
    DCA_SEPARACION_ATR_ENTRADAS,
    DCA_SEPARACION_ATR_SALIDAS,
    DCA_SEPARACION_MAX_PCT,
    DCA_SEPARACION_MIN_PCT,
    DCA_STOP_ATR_MULT,
    DCA_STOP_CAIDA_MAX,
    DCA_STOP_CAIDA_RESPALDO,
    DCA_STOP_MARGEN_ATR_BAJO_N3,
    MOTOR_VERSION,
    SENIALES_TIMING,
    VEREDICTO_UPSIDE_MIN,
    VEREDICTO_UPSIDE_REDUCIR,
    VEREDICTOS,
)
from core_ponderar import acotar, es_dato


# ------------------------------------------------------------- utilidades ---
def _separacion(precio: float, atr: float | None, mult: float) -> float:
    base = mult * atr if es_dato(atr) and atr > 0 else DCA_SEPARACION_MIN_PCT * 2 * precio
    return acotar(base, DCA_SEPARACION_MIN_PCT * precio, DCA_SEPARACION_MAX_PCT * precio)


def _rango(precio: float, atr: float | None, min_pct: float, max_pct: float) -> float:
    base = DCA_RANGO_ATR * atr if es_dato(atr) and atr > 0 else min_pct * precio
    return acotar(base, min_pct * precio, max_pct * precio)


def _nivel(precio: float, zona: dict | None, sintetico: str | None = None) -> dict:
    if zona is not None:
        return {"precio": round(zona["precio"], 4), "fuerza": round(zona["fuerza"], 2), "fuerte": zona["fuerte"],
                "motivos": zona["motivos"][:4], "sintetico": False}
    return {"precio": round(precio, 4), "fuerza": 0.0, "fuerte": False,
            "motivos": [sintetico or "escalón de ATR sin confluencia"], "sintetico": True}


def _escalera(zonas: list[dict], precio: float, tope: float, sep: float, abajo: bool, n: int = 3) -> list[dict]:
    """Elige n niveles: el más fuerte dentro del rango [precio, tope], luego
    el más fuerte más allá de `sep` desde el anterior, etc. Sin zona, nivel
    sintético a `sep` del anterior."""
    if abajo:
        cands = [z for z in zonas if precio > z["precio"] >= tope]
    else:
        cands = [z for z in zonas if precio < z["precio"] <= tope]
    niveles: list[dict] = []
    frontera = precio          # N1: sin separación mínima respecto al precio
    for i in range(n):
        if abajo:
            validos = [z for z in cands if z["precio"] <= frontera - (sep if i else 0)]
        else:
            validos = [z for z in cands if z["precio"] >= frontera + (sep if i else 0)]
        if validos:
            z = max(validos, key=lambda z: z["fuerza"])
            niveles.append(_nivel(z["precio"], z))
            frontera = z["precio"]
        else:
            frontera = frontera - sep if abajo else frontera + sep
            niveles.append(_nivel(frontera, None))
    return niveles


# ----------------------------------------------------------------- plan -----
def plan(confluencia: dict, ind: dict, precio: float | None, fair_value: float | None) -> dict | None:
    if not es_dato(precio) or precio <= 0 or not confluencia:
        return None
    precio = float(precio)
    atr = ind.get("atr")
    zonas = confluencia.get("zonas", [])

    # --- entradas
    sep_e = _separacion(precio, atr, DCA_SEPARACION_ATR_ENTRADAS)
    suelo = precio - _rango(precio, atr, DCA_RANGO_ENTRADAS_MIN_PCT, DCA_RANGO_ENTRADAS_MAX_PCT)
    entradas = _escalera(zonas, precio, suelo, sep_e, abajo=True)
    for i, (e, w) in enumerate(zip(entradas, DCA_PESOS_ENTRADA), start=1):
        e.update({"nivel": f"E{i}", "peso": w, "dist_pct": (e["precio"] / precio - 1) * 100})
    coste_medio = sum(e["precio"] * e["peso"] for e in entradas)

    # --- salidas
    sep_s = _separacion(precio, atr, DCA_SEPARACION_ATR_SALIDAS)
    techo = precio + _rango(precio, atr, DCA_RANGO_SALIDAS_MIN_PCT, DCA_RANGO_SALIDAS_MAX_PCT)
    salidas = _escalera(zonas, precio, techo, sep_s, abajo=False, n=2)
    s3, motivo_s3 = _tercera_salida(zonas, ind, precio, salidas[-1]["precio"], sep_s, techo, fair_value)
    salidas.append(s3)
    for i, (s, w) in enumerate(zip(salidas, DCA_PESOS_SALIDA), start=1):
        s.update({"nivel": f"S{i}", "peso": w, "dist_pct": (s["precio"] / precio - 1) * 100})
    if motivo_s3:
        salidas[-1]["motivos"] = [motivo_s3] + [m for m in salidas[-1]["motivos"] if m != motivo_s3]
    salida_media = sum(s["precio"] * s["peso"] for s in salidas)

    # --- stop sobre el coste medio
    n3 = entradas[-1]["precio"]
    if es_dato(atr) and atr > 0:
        stop = coste_medio - DCA_STOP_ATR_MULT * atr
        stop = min(stop, n3 - DCA_STOP_MARGEN_ATR_BAJO_N3 * atr)
        stop = max(stop, coste_medio * (1 - DCA_STOP_CAIDA_MAX))
        stop = min(stop, n3 * 0.995)          # nunca por encima de N3, aunque el techo de caída lo empuje
        motivo_stop = f"{DCA_STOP_ATR_MULT:.1f} x ATR bajo el coste medio, con margen bajo E3 y caída máxima {DCA_STOP_CAIDA_MAX * 100:.0f} %"
    else:
        stop = coste_medio * (1 - DCA_STOP_CAIDA_RESPALDO)
        motivo_stop = f"sin ATR utilizable: caída del {DCA_STOP_CAIDA_RESPALDO * 100:.0f} % sobre el coste medio"

    riesgo_pct = (coste_medio - stop) / coste_medio * 100
    beneficio_pct = (salida_media / coste_medio - 1) * 100
    return {
        "precio": precio,
        "entradas": entradas,
        "salidas": salidas,
        "stop": round(stop, 4),
        "motivo_stop": motivo_stop,
        "coste_medio": round(coste_medio, 4),
        "salida_media": round(salida_media, 4),
        "riesgo_pct": riesgo_pct,
        "beneficio_pct": beneficio_pct,
        "ratio_br": (beneficio_pct / riesgo_pct) if riesgo_pct > 0 else None,
        "n1_dist_atr": ((precio - entradas[0]["precio"]) / atr) if es_dato(atr) and atr > 0 else None,
        "n1_fuerte": entradas[0]["fuerte"],
        "version": MOTOR_VERSION,
    }


def _tercera_salida(zonas, ind, precio, s2, sep, techo, fair_value):
    """S3 anclada al fair value cuando queda por encima de S2 + separación;
    una resistencia fuerte a menos de una separación del FV la sustituye
    (el precio suele frenar antes en el nivel técnico). Con tendencia fuerte
    confirmada se admite extender hasta FV x DCA_SALIDA_EXTENSION_MAX si hay
    resistencia ahí. Sin FV utilizable, escalera técnica normal."""
    minimo = s2 + sep
    tendencia_fuerte = (es_dato(ind.get("adx")) and ind["adx"] >= DCA_SALIDA_ADX_TENDENCIA
                        and es_dato(ind.get("di_pos")) and es_dato(ind.get("di_neg")) and ind["di_pos"] > ind["di_neg"]
                        and es_dato(ind.get("mm200")) and precio > ind["mm200"])
    if es_dato(fair_value) and fair_value >= minimo:
        fv = float(fair_value)
        cerca = [z for z in zonas if z["fuerte"] and z["precio"] >= minimo and abs(z["precio"] - fv) <= sep]
        if cerca:
            z = max(cerca, key=lambda z: z["fuerza"])
            return _nivel(z["precio"], z), "resistencia fuerte junto al fair value"
        if tendencia_fuerte:
            ext = [z for z in zonas if fv < z["precio"] <= fv * DCA_SALIDA_EXTENSION_MAX]
            if ext:
                z = max(ext, key=lambda z: z["fuerza"])
                return _nivel(z["precio"], z), "extensión sobre el fair value por tendencia fuerte"
        return _nivel(fv, None, "fair value (valor objetivo)"), "fair value (valor objetivo)"
    nivel = _escalera(zonas, s2, techo, sep, abajo=False, n=1)[0]
    if es_dato(fair_value) and fair_value < minimo:
        nivel["motivos"] = ["fair value por debajo de S2: salida técnica"] + nivel["motivos"]
    return nivel, None


# ------------------------------------------------------------- veredicto ----
def senal_timing(nota: float | None) -> tuple[str, str] | None:
    if not es_dato(nota):
        return None
    for umbral, etiqueta, color in SENIALES_TIMING:
        if nota >= umbral:
            return etiqueta, color
    return SENIALES_TIMING[-1][1:]


def veredicto(calidad: float | None, upside_pct: float | None, timing: float | None,
              posicion_abierta: bool = False) -> dict:
    """Matriz con vetos. Devuelve {clave, etiqueta, color, motivo}."""
    def r(clave, motivo):
        etiqueta, color = VEREDICTOS[clave]
        return {"clave": clave, "etiqueta": etiqueta, "color": color, "motivo": motivo}

    if not es_dato(calidad):
        return r("vigilar", "sin nota de calidad fiable (cobertura insuficiente): no se emite compra")
    if calidad < CALIDAD_MINIMA_TIMING:
        if posicion_abierta and es_dato(upside_pct) and upside_pct <= VEREDICTO_UPSIDE_REDUCIR:
            return r("reducir", f"calidad {calidad:.0f} < {CALIDAD_MINIMA_TIMING} y sobrevaloración con posición abierta")
        return r("no_comprar", f"calidad {calidad:.0f} < {CALIDAD_MINIMA_TIMING}: el veto de calidad prevalece sobre precio y timing")
    if not es_dato(upside_pct):
        return r("vigilar", "empresa de calidad sin fair value calculable: falta el argumento de precio")
    if upside_pct <= VEREDICTO_UPSIDE_REDUCIR and posicion_abierta:
        return r("reducir", f"sobrevalorada ({upside_pct:+.0f} %) con posición abierta")
    if upside_pct < -VEREDICTO_UPSIDE_MIN:
        return r("no_comprar", f"cotiza por encima del fair value ({upside_pct:+.0f} %)")
    if upside_pct < VEREDICTO_UPSIDE_MIN:
        return r("vigilar", f"precio justo ({upside_pct:+.0f} %): sin margen suficiente para entrar")
    s = senal_timing(timing)
    if s and s[0] == "ENTRAR":
        return r("comprar", f"calidad {calidad:.0f}, upside {upside_pct:+.0f} % y timing {timing:.0f} (ENTRAR)")
    if s and s[0] == "ACUMULAR":
        return r("acumular", f"calidad {calidad:.0f}, upside {upside_pct:+.0f} % y timing {timing:.0f}: entrar por tramos según el plan")
    return r("vigilar", f"calidad y precio acompañan pero el timing ({timing:.0f} — {s[0] if s else 'sin dato'}) pide esperar")


# ------------------------------------------------------------- narrativa ----
def narrativa(ticker: str, calidad: dict | None, fv: dict | None, timing: dict | None, p: dict | None,
              ver: dict, divisa: str = "") -> str:
    """Cuatro o cinco frases: qué es, qué vale, cuándo, cómo, y la conclusión.
    Solo afirma lo que tiene dato."""
    frases = []
    nota = (calidad or {}).get("nota")
    if es_dato(nota):
        perfil = "en pre-rentabilidad" if (calidad or {}).get("perfil") == "pre_rentabilidad" else "rentable"
        bloques = (calidad or {}).get("bloques", {})
        peor = min(((b["nota"], n) for n, b in bloques.items() if es_dato(b.get("nota"))), default=None)
        frases.append(f"{ticker} es una empresa {perfil} con calidad {nota:.0f}/100"
                      + (f"; su punto débil es {peor[1].split('. ')[-1].lower()} ({peor[0]:.0f})" if peor else "") + ".")
    else:
        frases.append(f"{ticker} no tiene nota de calidad fiable: la cobertura de datos es insuficiente.")
    up, fvv = (fv or {}).get("upside_pct"), (fv or {}).get("fair_value")
    if es_dato(up) and es_dato(fvv):
        banda = (fv or {}).get("banda")
        frases.append(f"El fair value es {fvv:,.2f} {divisa} ({up:+.0f} % sobre el precio)"
                      + (f": {banda[0].split(' — ')[0].lower()}" if banda else "") + ".")
    else:
        frases.append("No hay fair value calculable con los métodos disponibles.")
    if timing and es_dato(timing.get("nota")):
        s = timing.get("senal")
        mejores = timing.get("mejores", [])
        peores = timing.get("peores", [])
        txt = f"El timing puntúa {timing['nota']:.0f} ({s[0] if s else '—'})"
        if mejores:
            txt += f"; a favor: {', '.join(mejores[:2])}"
        if peores:
            txt += f"; en contra: {', '.join(peores[:2])}"
        if timing.get("gate"):
            txt += f". Topado en {timing['nota']:.0f} por el veto de calidad"
        frases.append(txt + ".")
    if p:
        e1 = p["entradas"][0]
        frases.append(f"Plan: primera entrada en {e1['precio']:,.2f} {divisa} ({e1['dist_pct']:+.1f} %, "
                      f"{e1['motivos'][0]}), coste medio {p['coste_medio']:,.2f}, stop {p['stop']:,.2f} "
                      f"(riesgo {p['riesgo_pct']:.0f} %) y salida media {p['salida_media']:,.2f} "
                      f"(+{p['beneficio_pct']:.0f} %)" + (f", ratio {p['ratio_br']:.1f}:1" if es_dato(p.get('ratio_br')) else "") + ".")
    frases.append(f"Veredicto: {ver['etiqueta']} — {ver['motivo']}.")
    return " ".join(frases)


def invalidacion(calidad: dict | None, fv: dict | None, p: dict | None, earnings: dict | None) -> list[dict]:
    """Condiciones que rompen la tesis. Cada una con umbral concreto para
    poder vigilarla (sesión 5: alertas) y con texto para la tarjeta."""
    out = []
    if p:
        out.append({"condicion": "ruptura_soporte", "umbral": {"precio": p["stop"]},
                    "texto": f"Cierre diario por debajo del stop ({p['stop']:,.2f}): la estructura de soportes del plan deja de ser válida."})
    nota = (calidad or {}).get("nota")
    if es_dato(nota):
        umbral = max(CALIDAD_MINIMA_TIMING, nota - 10)
        out.append({"condicion": "calidad_degradada", "umbral": {"calidad_min": umbral},
                    "texto": f"Calidad por debajo de {umbral:.0f} en un análisis posterior (deterioro de márgenes, deuda o crecimiento)."})
    fvv = (fv or {}).get("fair_value")
    if es_dato(fvv):
        out.append({"condicion": "fair_value_caida", "umbral": {"fair_value_min": fvv * 0.85},
                    "texto": f"Fair value revisado por debajo de {fvv * 0.85:,.2f} (−15 %): el margen de seguridad desaparece."})
    proximo = (earnings or {}).get("proximo")
    fecha = proximo.get("fecha") if proximo else None
    out.append({"condicion": "earnings_debiles", "umbral": {"trimestres_fallidos": 2,
                                                            "proximo": fecha.isoformat() if isinstance(fecha, date) else None},
                "texto": "Dos trimestres consecutivos fallando el consenso de BPA"
                         + (f" (próximo: {fecha:%d/%m/%Y})" if isinstance(fecha, date) else "") + "."})
    return out
