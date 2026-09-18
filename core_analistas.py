"""Recomendaciones de analistas (sesión 6). Funciones puras sobre la serie
mensual [{periodo, strongBuy, buy, hold, sell, strongSell}] que sirve
datos_finnhub.obtener_recomendaciones (respaldo yfinance).

Dos lecturas distintas, a propósito:
- INFORMATIVA: la distribución del último mes, cuántos analistas cubren y la
  etiqueta de consenso. Es lo que el usuario necesita para saber quién firma
  el 20 % del Fair Value que aporta el precio objetivo.
- PARA EL TIMING: solo la REVISIÓN (variación del índice de recomendación a
  ANALISTAS_MESES_REVISION meses), nunca el nivel: en el mercado la mitad de
  las recomendaciones son compra y una venta pura es rarísima, así que un
  "100 % compra fuerte" con 3 analistas es lo normal, no una señal.

Índice de recomendación: media por analista de (+2 compra fuerte, +1
compra, 0 mantener, -1 venta, -2 venta fuerte). Rango -2..+2.
"""

from __future__ import annotations

from config_settings import ANALISTAS_CONSENSO, ANALISTAS_MESES_REVISION, ANALISTAS_MESES_SERIE, ANALISTAS_MIN_REVISION

CLAVES = ("strongBuy", "buy", "hold", "sell", "strongSell")
_PUNTOS = {"strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2}


def total(mes: dict) -> int:
    return int(sum(int(mes.get(k) or 0) for k in CLAVES))


def indice(mes: dict) -> float | None:
    """Índice -2..+2 del mes; None sin analistas."""
    n = total(mes)
    if n <= 0:
        return None
    return sum(_PUNTOS[k] * int(mes.get(k) or 0) for k in CLAVES) / n


def consenso(valor: float | None) -> tuple[str, str] | None:
    """(etiqueta, color) del índice según ANALISTAS_CONSENSO."""
    if valor is None:
        return None
    for minimo, etiqueta, color in ANALISTAS_CONSENSO:
        if valor >= minimo:
            return etiqueta, color
    return ANALISTAS_CONSENSO[-1][1], ANALISTAS_CONSENSO[-1][2]


def revision(serie: list[dict], meses: int = ANALISTAS_MESES_REVISION) -> tuple[float | None, str | None]:
    """(variación del índice entre el último mes y `meses` atrás, motivo si
    no se puede). Si no hay exactamente ese mes, se usa el más antiguo
    disponible dentro de la ventana (con al menos un mes de distancia)."""
    if not serie:
        return None, "sin serie de recomendaciones"
    ultimo = serie[0]
    if total(ultimo) < ANALISTAS_MIN_REVISION:
        return None, f"menos de {ANALISTAS_MIN_REVISION} analistas"
    candidatos = [m for m in serie[1:meses + 1] if total(m) >= ANALISTAS_MIN_REVISION]
    if not candidatos:
        return None, "sin serie mensual suficiente para medir revisiones"
    anterior = candidatos[-1]
    i0, i1 = indice(ultimo), indice(anterior)
    if i0 is None or i1 is None:
        return None, "sin analistas en la serie"
    return i0 - i1, None


def resumen(serie: list[dict] | None) -> dict | None:
    """Todo lo que enseña la vista y consume el Timing:
    {ultimo: {periodo, strongBuy...}, n, indice, consenso: (etiqueta, color),
     revision, revision_motivo, revision_meses, pct: {clave: %},
     serie: [...ANALISTAS_MESES_SERIE meses], movimiento: {clave: delta}}."""
    if not serie:
        return None
    ultimo = serie[0]
    n = total(ultimo)
    if n <= 0:
        return None
    idx = indice(ultimo)
    rev, motivo = revision(serie)
    comparado = None
    for m in serie[1:ANALISTAS_MESES_REVISION + 1]:
        comparado = m
    movimiento = {k: int(ultimo.get(k) or 0) - int(comparado.get(k) or 0) for k in CLAVES} if comparado else {}
    return {
        "ultimo": ultimo,
        "n": n,
        "indice": idx,
        "consenso": consenso(idx),
        "revision": rev,
        "revision_motivo": motivo,
        "revision_meses": ANALISTAS_MESES_REVISION,
        "periodo_comparado": comparado.get("periodo") if comparado else None,
        "pct": {k: int(ultimo.get(k) or 0) / n * 100 for k in CLAVES},
        "movimiento": movimiento,
        "serie": serie[:ANALISTAS_MESES_SERIE],
    }


def texto_revision(r: dict | None) -> str | None:
    """Frase corta: "3 meses: +2 hacia compra, -1 mantener (índice +0,25)"."""
    if not r:
        return None
    if r.get("revision") is None:
        return r.get("revision_motivo")
    mov = r.get("movimiento") or {}
    subidas = mov.get("strongBuy", 0) + mov.get("buy", 0)
    bajadas = mov.get("sell", 0) + mov.get("strongSell", 0)
    partes = []
    if subidas:
        partes.append(f"{subidas:+d} compra")
    if mov.get("hold"):
        partes.append(f"{mov['hold']:+d} mantener")
    if bajadas:
        partes.append(f"{bajadas:+d} venta")
    cambio = ", ".join(partes) if partes else "sin cambios en la distribución"
    signo = "+" if r["revision"] > 0 else ""
    return f"{r['revision_meses']} meses: {cambio} (índice {signo}{r['revision']:.2f})".replace(".", ",")
