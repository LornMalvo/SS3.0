"""Reglas de alerta (sesión 5). Funciones puras: reciben planes, ejecuciones,
posiciones y precios y devuelven eventos con texto y clave de
deduplicación; quién los envía (tarea_alertas.py) y cómo (Telegram) va
aparte, así las reglas se pueden probar sin red.

Cada evento: {tipo, ticker, clave, texto, prioridad}. La clave decide
cuántas veces se avisa de lo mismo (ver ALERTAS en config_settings):
  nivel      -> "nivel:{plan}:{nivel}"            una vez por nivel y plan
  cerca      -> "cerca:{plan}:{nivel}:{fecha}"    una vez al día
  movimiento -> "mov:{ticker}:{fecha}"            una vez al día
  reco       -> "reco:{ticker}:{clave}:{fecha}"   una vez al día por recomendación
  resumen    -> "resumen:{fecha}"                 una vez por sesión
  screener   -> "scr:{ticker}:{motivo}:{fecha}"   una vez al día por ticker y motivo (sesión 7)
"""

from __future__ import annotations

from datetime import date

from config_settings import (
    SCREENER_ALERTA_CALIDAD_MIN,
    SCREENER_ALERTA_E1_PCT,
    SCREENER_ALERTA_MAX,
    SCREENER_ALERTA_VEREDICTOS,
    ALERTA_CERCA_PCT,
    ALERTA_MOVIMIENTO_PCT,
    ALERTA_RECOS_AVISO,
    ALERTA_RESUMEN_MOVERS,
    PAPER_NIVEL_STOP,
    PAPER_NIVELES_ENTRADA,
)
from core_paper import nivel_alcanzado, niveles_pendientes, precio_nivel
from core_ponderar import es_dato


def _fmt(v, dec: int = 2) -> str:
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".") if es_dato(v) else "n/d"


def _pct(v) -> str:
    return f"{v:+.1f} %".replace(".", ",") if es_dato(v) else "n/d"


# ---------------------------------------------------------- paper trading --
def alertas_planes(planes: list[dict], ejec_por_plan: dict, precios: dict[str, dict], hoy: date,
                   auto_ejecutados: set[tuple[int, str]] | None = None) -> list[dict]:
    """Niveles pendientes alcanzados (una vez por nivel) y niveles a menos
    de ALERTA_CERCA_PCT (una vez al día). `auto_ejecutados` marca los
    (plan, nivel) que el cron acaba de ejecutar solo, para decirlo."""
    auto_ejecutados = auto_ejecutados or set()
    out = []
    for p in planes:
        ejec = ejec_por_plan.get(p["id"], [])
        cot = precios.get(p["ticker"]) or {}
        precio = cot.get("precio")
        if not es_dato(precio):
            continue
        divisa = p.get("divisa") or ""
        # Los niveles recién ejecutados por el cron ya no están pendientes,
        # pero hay que avisar de ellos igual.
        recien = [n for pid, n in auto_ejecutados if pid == p["id"]]
        for nivel in niveles_pendientes(p, ejec) + [n for n in recien if n not in niveles_pendientes(p, ejec)]:
            objetivo = precio_nivel(p, nivel)
            if not es_dato(objetivo):
                continue
            dist = (precio / objetivo - 1) * 100
            if nivel_alcanzado(nivel, objetivo, precio) or (p["id"], nivel) in auto_ejecutados:
                que = ("entrada" if nivel in PAPER_NIVELES_ENTRADA else "STOP" if nivel == PAPER_NIVEL_STOP else "salida")
                extra = " — ejecutado automáticamente en Paper Trading" if (p["id"], nivel) in auto_ejecutados else ""
                out.append({"tipo": "nivel", "ticker": p["ticker"], "clave": f"nivel:{p['id']}:{nivel}",
                            "prioridad": 0 if nivel == PAPER_NIVEL_STOP else 1,
                            "texto": f"<b>{p['ticker']}</b> alcanza {nivel} ({que}) en {_fmt(objetivo)} {divisa}: "
                                     f"cotiza a {_fmt(precio)}{extra}."})
            elif abs(dist) <= ALERTA_CERCA_PCT:
                out.append({"tipo": "cerca", "ticker": p["ticker"], "clave": f"cerca:{p['id']}:{nivel}:{hoy.isoformat()}",
                            "prioridad": 2,
                            "texto": f"<b>{p['ticker']}</b> a {_pct(dist)} de {nivel} ({_fmt(objetivo)} {divisa}); "
                                     f"cotiza a {_fmt(precio)}."})
    return out


# ----------------------------------------------------------------- cartera --
def alertas_cartera(posiciones: dict[str, dict], hoy: date) -> list[dict]:
    """Movimientos diarios fuertes y recomendaciones que piden actuar
    (VENDER, REDUCIR, VENTA PARCIAL), una vez al día cada una. Las
    posiciones llegan ya valoradas, con var_dia_pct y recomendacion."""
    out = []
    for t, p in posiciones.items():
        if p.get("cerrada"):
            continue
        var = p.get("var_dia_pct")
        if es_dato(var) and abs(var) >= ALERTA_MOVIMIENTO_PCT:
            eur = p.get("var_dia_eur")
            out.append({"tipo": "movimiento", "ticker": t, "clave": f"mov:{t}:{hoy.isoformat()}", "prioridad": 1,
                        "texto": f"<b>{t}</b> {_pct(var)} hoy" + (f" ({_fmt(eur)} €)" if es_dato(eur) else "")
                                 + f"; latente {_pct(p.get('latente_pct'))}."})
        reco = p.get("recomendacion")
        if reco and reco["clave"] in ALERTA_RECOS_AVISO:
            out.append({"tipo": "reco", "ticker": t, "clave": f"reco:{t}:{reco['clave']}:{hoy.isoformat()}", "prioridad": 1,
                        "texto": f"<b>{t}</b> → <b>{reco['etiqueta']}</b>: {reco['motivo']}."})
    return out


def resumen_cierre(resumen: dict, posiciones: dict[str, dict], hoy: date) -> dict | None:
    """Resumen de la sesión: valor, latente, retorno y mayores movimientos.
    None sin posiciones abiertas."""
    abiertas = [p for p in posiciones.values() if not p.get("cerrada")]
    if not abiertas:
        return None
    con_var = sorted((p for p in abiertas if es_dato(p.get("var_dia_pct"))), key=lambda p: p["var_dia_pct"])
    dia_eur = sum(p["var_dia_eur"] for p in abiertas if es_dato(p.get("var_dia_eur")))
    lineas = [f"<b>Cierre {hoy:%d/%m/%Y}</b> · cartera {_fmt(resumen.get('valor_eur'))} € "
              f"({_pct(resumen.get('latente_pct'))} latente, {_fmt(resumen.get('latente_eur'))} €)",
              f"Hoy: {_fmt(dia_eur)} € · retorno total {_pct(resumen.get('retorno_total_pct'))}"]
    if con_var:
        subidas = [p for p in reversed(con_var) if p["var_dia_pct"] > 0][:ALERTA_RESUMEN_MOVERS]
        bajadas = [p for p in con_var if p["var_dia_pct"] < 0][:ALERTA_RESUMEN_MOVERS]
        if subidas:
            lineas.append("Suben: " + ", ".join(f"{p['ticker']} {_pct(p['var_dia_pct'])}" for p in subidas))
        if bajadas:
            lineas.append("Bajan: " + ", ".join(f"{p['ticker']} {_pct(p['var_dia_pct'])}" for p in bajadas))
    recos = [p for p in abiertas if (p.get("recomendacion") or {}).get("clave") in ALERTA_RECOS_AVISO]
    if recos:
        lineas.append("Revisar: " + ", ".join(f"{p['ticker']} ({p['recomendacion']['etiqueta']})" for p in recos))
    return {"tipo": "resumen", "ticker": "*", "clave": f"resumen:{hoy.isoformat()}", "prioridad": 3,
            "texto": "\n".join(lineas)}


# ---------------------------------------------------------------- screener --
def alertas_screener(hoy_filas: list[dict], previos: dict[str, dict], hoy: date) -> list[dict]:
    """Qué ha cambiado en el rastreo nocturno. Dos motivos:
      nuevo   el veredicto de hoy está en SCREENER_ALERTA_VEREDICTOS y el
              del último análisis anterior del cron no (o no había)
      e1      calidad >= SCREENER_ALERTA_CALIDAD_MIN y el precio ha llegado
              a E1 (dist_e1_pct <= SCREENER_ALERTA_E1_PCT) sin estarlo antes
    `hoy_filas`: core_rastreador.fila()/fila_desde_historico de hoy;
    `previos`: {ticker: fila anterior} (mismo formato). Se devuelven como
    mucho SCREENER_ALERTA_MAX por motivo, los de mayor puntuación."""
    nuevos, e1 = [], []
    for f in hoy_filas:
        t = f["ticker"]
        prev = previos.get(t) or {}
        v, v_prev = f.get("veredicto"), prev.get("veredicto")
        if v in SCREENER_ALERTA_VEREDICTOS and v_prev not in SCREENER_ALERTA_VEREDICTOS:
            nuevos.append(f)
        cal, dist, dist_prev = f.get("calidad"), f.get("dist_e1_pct"), prev.get("dist_e1_pct")
        if (es_dato(cal) and cal >= SCREENER_ALERTA_CALIDAD_MIN and es_dato(dist) and dist <= SCREENER_ALERTA_E1_PCT
                and not (es_dato(dist_prev) and dist_prev <= SCREENER_ALERTA_E1_PCT)
                and v not in ("NO COMPRAR", "REDUCIR")):
            e1.append(f)
    puntuacion = lambda f: -(f.get("puntuacion") if es_dato(f.get("puntuacion")) else -1)  # noqa: E731
    out = []
    for f in sorted(nuevos, key=puntuacion)[:SCREENER_ALERTA_MAX]:
        prev = previos.get(f["ticker"]) or {}
        out.append({"tipo": "screener", "ticker": f["ticker"], "clave": f"scr:{f['ticker']}:nuevo:{hoy.isoformat()}",
                    "prioridad": 4,
                    "texto": f"<b>{f['ticker']}</b> pasa a <b>{f['veredicto']}</b>"
                             + (f" (antes {prev['veredicto']})" if prev.get("veredicto") else " (sin análisis previo)")
                             + f": calidad {_fmt(f.get('calidad'), 0)}, upside {_pct(f.get('upside_pct'))}, "
                               f"timing {_fmt(f.get('timing'), 0)}"
                             + (f", E1 {_fmt(f.get('e1'))} {f.get('divisa') or ''}" if es_dato(f.get("e1")) else "") + "."})
    for f in sorted(e1, key=puntuacion)[:SCREENER_ALERTA_MAX]:
        out.append({"tipo": "screener", "ticker": f["ticker"], "clave": f"scr:{f['ticker']}:e1:{hoy.isoformat()}",
                    "prioridad": 4,
                    "texto": f"<b>{f['ticker']}</b> toca E1 ({_fmt(f.get('e1'))} {f.get('divisa') or ''}) con calidad "
                             f"{_fmt(f.get('calidad'), 0)}: cotiza a {_fmt(f.get('precio'))}, {f.get('veredicto') or 'sin veredicto'}, "
                             f"upside {_pct(f.get('upside_pct'))}."})
    return out


# ----------------------------------------------------------------- mensaje --
def componer(eventos: list[dict]) -> str:
    """Un solo mensaje Telegram (HTML) con los eventos por prioridad."""
    titulos = {0: "🛑 STOP", 1: "⚡ Niveles y avisos", 2: "👀 Cerca de un nivel", 3: "📊 Resumen",
               4: "🔭 Screener nocturno"}
    partes = []
    for prio in sorted({e["prioridad"] for e in eventos}):
        bloque = [e["texto"] for e in eventos if e["prioridad"] == prio]
        partes.append(f"<b>{titulos.get(prio, '')}</b>\n" + "\n".join(bloque))
    return "StockScanner\n\n" + "\n\n".join(partes)
