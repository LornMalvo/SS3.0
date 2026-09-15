"""Persistencia en Supabase. Un repositorio por tabla, funciones pequeñas.

Sin credenciales (desarrollo local o secretos aún no configurados) todo
funciona contra `st.session_state`: el esqueleto arranca igual y la interfaz
avisa de que no hay persistencia. Cualquier error de red devuelve el valor
neutro (lista vacía, "") en vez de romper el análisis.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

import config_secretos


@st.cache_resource(show_spinner=False)
def _cliente():
    url, key = config_secretos.supabase()
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def disponible() -> bool:
    return _cliente() is not None


def _memoria(clave: str, defecto):
    return st.session_state.setdefault(f"_mem_{clave}", defecto)


# ---------------------------------------------------------------- favoritos --
def listar_favoritos() -> list[str]:
    cli = _cliente()
    if cli is None:
        return sorted(_memoria("favoritos", set()))
    try:
        filas = cli.table("favoritos").select("ticker").order("ticker").execute().data
        return [f["ticker"] for f in filas]
    except Exception:
        return []


def es_favorito(ticker: str) -> bool:
    return ticker in listar_favoritos()


def alternar_favorito(ticker: str) -> bool:
    """Añade o quita. Devuelve el estado nuevo (True = ahora es favorito)."""
    cli = _cliente()
    if cli is None:
        favs = _memoria("favoritos", set())
        if ticker in favs:
            favs.discard(ticker)
            return False
        favs.add(ticker)
        return True
    try:
        if es_favorito(ticker):
            cli.table("favoritos").delete().eq("ticker", ticker).execute()
            return False
        cli.table("favoritos").insert({"ticker": ticker}).execute()
        return True
    except Exception:
        return es_favorito(ticker)


# -------------------------------------------------------------- anotaciones --
def leer_anotacion(ticker: str) -> str:
    cli = _cliente()
    if cli is None:
        return _memoria("anotaciones", {}).get(ticker, "")
    try:
        filas = cli.table("anotaciones").select("texto").eq("ticker", ticker).limit(1).execute().data
        return filas[0]["texto"] if filas else ""
    except Exception:
        return ""


def guardar_anotacion(ticker: str, texto: str) -> bool:
    cli = _cliente()
    if cli is None:
        _memoria("anotaciones", {})[ticker] = texto
        return True
    try:
        cli.table("anotaciones").upsert({
            "ticker": ticker,
            "texto": texto,
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception:
        return False


# -------------------------------------------------------- diario y análisis --
def registrar_decision(ticker: str, accion: str, motivo: str, plan_id: int | None = None) -> None:
    cli = _cliente()
    if cli is None:
        _memoria("diario", []).append({"ticker": ticker, "accion": accion, "motivo": motivo})
        return
    try:
        cli.table("diario_decisiones").insert({
            "ticker": ticker, "accion": accion, "motivo": motivo, "plan_id": plan_id,
        }).execute()
    except Exception:
        pass


def guardar_analisis(fila: dict) -> None:
    """Histórico de análisis con deduplicación por (ticker, fecha, versión)."""
    cli = _cliente()
    if cli is None:
        return
    try:
        cli.table("analisis_historico").upsert(
            fila, on_conflict="ticker,fecha_analisis,motor_version"
        ).execute()
    except Exception:
        pass


# ------------------------------------------------------------ paper trading --
def guardar_plan_paper(fila: dict) -> int | None:
    """Inserta un plan en `paper_planes` (estado inicial 'vigilancia').
    Devuelve el id creado, o un id negativo en memoria si no hay Supabase, y
    None si la escritura falla."""
    cli = _cliente()
    if cli is None:
        planes = _memoria("paper_planes", [])
        fila = {**fila, "id": -(len(planes) + 1), "estado": "vigilancia",
                "creado_en": datetime.now(timezone.utc).isoformat()}
        planes.append(fila)
        return fila["id"]
    try:
        r = cli.table("paper_planes").insert({**fila, "estado": "vigilancia"}).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def listar_planes_paper(estados: tuple[str, ...] | None = None) -> list[dict]:
    """Planes guardados, más reciente primero; `estados` filtra si se indica."""
    cli = _cliente()
    if cli is None:
        planes = list(reversed(_memoria("paper_planes", [])))
        return [p for p in planes if not estados or p.get("estado") in estados]
    try:
        q = cli.table("paper_planes").select("*").order("creado_en", desc=True)
        if estados:
            q = q.in_("estado", list(estados))
        return q.execute().data or []
    except Exception:
        return []


def plan_activo_para(ticker: str) -> dict | None:
    """Último plan no descartado ni cerrado del ticker (evita duplicar planes)."""
    from config_settings import PAPER_ESTADOS_ACTIVOS
    for p in listar_planes_paper(PAPER_ESTADOS_ACTIVOS):
        if p.get("ticker") == ticker:
            return p
    return None


def actualizar_plan_paper(plan_id: int, campos: dict) -> bool:
    """Cambia estado, capital... de un plan. Sella `actualizado_en`."""
    cli = _cliente()
    if cli is None:
        for p in _memoria("paper_planes", []):
            if p.get("id") == plan_id:
                p.update(campos)
                return True
        return False
    try:
        cli.table("paper_planes").update({
            **campos, "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }).eq("id", plan_id).execute()
        return True
    except Exception:
        return False


def eliminar_plan_paper(plan_id: int) -> bool:
    """Borra el plan, sus ejecuciones (cascada en BD) y las operaciones
    'paper' que esas ejecuciones crearon en el libro: un plan borrado no
    puede dejar rastro en el rendimiento simulado."""
    cli = _cliente()
    if cli is None:
        planes = _memoria("paper_planes", [])
        planes[:] = [p for p in planes if p.get("id") != plan_id]
        ejec = _memoria("paper_ejecuciones", [])
        ejec[:] = [e for e in ejec if e.get("plan_id") != plan_id]
        ops = _memoria("operaciones", [])
        ops[:] = [o for o in ops if not (o.get("origen") == "paper" and o.get("plan_id") == plan_id)]
        return True
    try:
        cli.table("cartera_operaciones").delete().eq("origen", "paper").eq("plan_id", plan_id).execute()
        cli.table("paper_planes").delete().eq("id", plan_id).execute()
        return True
    except Exception:
        return False


def listar_ejecuciones_paper(plan_ids: tuple[int, ...] | None = None) -> list[dict]:
    """Ejecuciones de nivel, más antigua primero; una consulta para N planes."""
    cli = _cliente()
    if cli is None:
        ejec = _memoria("paper_ejecuciones", [])
        return [e for e in ejec if plan_ids is None or e.get("plan_id") in plan_ids]
    try:
        q = cli.table("paper_ejecuciones").select("*").order("fecha").order("id")
        if plan_ids is not None:
            if not plan_ids:
                return []
            q = q.in_("plan_id", list(plan_ids))
        return q.execute().data or []
    except Exception:
        return []


def registrar_ejecucion_paper(fila: dict) -> int | None:
    cli = _cliente()
    if cli is None:
        ejec = _memoria("paper_ejecuciones", [])
        fila = {**fila, "id": -(len(ejec) + 1)}
        ejec.append(fila)
        return fila["id"]
    try:
        r = cli.table("paper_ejecuciones").insert(fila).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def ejecutar_nivel_paper(plan: dict, ejecuciones: list[dict], nivel: str, precio: float, fecha, acciones: float,
                         fx: float | None, capital: float | None = None, automatica: bool = False) -> dict | None:
    """Flujo completo de una ejecución de nivel (manual desde la vista o
    automática desde la vista/cron): capital del plan si es la primera
    entrada -> operación 'paper' en el libro (en EUR, si la divisa es
    convertible: `fx` es EUR por unidad de la divisa del plan el día de la
    ejecución) -> fila en paper_ejecuciones -> estado derivado -> diario.
    Devuelve la fila de ejecución registrada o None si falló."""
    from config_settings import PAPER_NIVELES_ENTRADA
    import core_paper
    pid = plan["id"]
    if capital is not None:
        actualizar_plan_paper(pid, {"capital_eur": capital})
        plan["capital_eur"] = capital
    precio_eur = precio * fx if fx is not None else None
    op_id = None
    if precio_eur is not None:
        op_id = insertar_operacion({
            "ticker": plan["ticker"], "tipo": "compra" if nivel in PAPER_NIVELES_ENTRADA else "venta",
            "fecha": fecha.isoformat(), "acciones": float(acciones), "precio_eur": float(precio_eur), "comision_eur": 0.0,
            "origen": "paper", "plan_id": pid if pid > 0 else None,
            "nota": f"Paper {nivel}" + (" (automática)" if automatica else ""),
            "divisa": plan.get("divisa"), "precio_origen": float(precio), "fx_aplicado": fx,
        })
    fila = core_paper.fila_ejecucion(pid, nivel, fecha, precio, acciones, op_id if op_id and op_id > 0 else None,
                                     automatica)
    ejec_id = registrar_ejecucion_paper(fila)
    if ejec_id is None:
        if op_id is not None:
            eliminar_operacion(op_id)
        return None
    fila["id"] = ejec_id
    nuevo = core_paper.estado(plan, ejecuciones + [fila])
    if nuevo != plan.get("estado"):
        actualizar_plan_paper(pid, {"estado": nuevo})
        plan["estado"] = nuevo
    registrar_decision(plan["ticker"], "ejecutar_nivel",
                       f"{nivel} a {precio:g} {plan.get('divisa') or ''}" + (" · automática al alcanzar el nivel" if automatica else ""),
                       pid if pid > 0 else None)
    return fila


def ultimos_analisis(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Último análisis guardado de cada ticker: {ticker: {fecha, veredicto,
    upside_pct, calidad, timing, senal_timing, fair_value, sector}}. UNA
    consulta para N tickers; el sector sale del JSON `entradas`. Lo usan la
    exposición sectorial de Cartera (cero peticiones a Yahoo para lo ya
    analizado) y el veto de la recomendación por posición."""
    cli = _cliente()
    if cli is None or not tickers:
        return {}
    try:
        filas = (cli.table("analisis_historico")
                 .select("ticker,fecha_analisis,veredicto,upside_pct,calidad,timing,senal_timing,fair_value,entradas")
                 .in_("ticker", list(tickers)).order("fecha_analisis", desc=True).limit(len(tickers) * 5)
                 .execute().data or [])
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for f in filas:                                  # más reciente primero: el primero que aparece manda
        if f["ticker"] in out:
            continue
        out[f["ticker"]] = {k: f.get(k) for k in ("veredicto", "upside_pct", "calidad", "timing", "senal_timing", "fair_value")}
        out[f["ticker"]]["fecha"] = f.get("fecha_analisis")
        out[f["ticker"]]["sector"] = (f.get("entradas") or {}).get("sector")
    return out


def sectores_conocidos(tickers: tuple[str, ...]) -> dict[str, str]:
    """Sector de cada ticker según su ÚLTIMO análisis guardado."""
    return {t: a["sector"] for t, a in ultimos_analisis(tickers).items() if a.get("sector")}


def listar_analisis(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Filas de `analisis_historico` (sin el JSON de entradas) para la
    evaluación de señales del Rastreador: una consulta, más antigua primero."""
    cli = _cliente()
    if cli is None:
        return []
    try:
        q = (cli.table("analisis_historico")
             .select("id,ticker,fecha_analisis,motor_version,precio,divisa,calidad,fair_value,upside_pct,timing,"
                     "senal_timing,veredicto,plan")
             .order("fecha_analisis"))
        if desde:
            q = q.gte("fecha_analisis", desde)
        if hasta:
            q = q.lte("fecha_analisis", hasta)
        return q.execute().data or []
    except Exception:
        return []


def guardar_backtest(filas: list[dict]) -> bool:
    """Retornos a 3/6/12 meses de cada señal, deduplicados por (versión,
    ticker, fecha): se reescriben conforme se cumplen horizontes."""
    cli = _cliente()
    if cli is None or not filas:
        return False
    try:
        cli.table("backtest_resultados").upsert(filas, on_conflict="motor_version,ticker,fecha_senal").execute()
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ cartera --
def listar_operaciones(origen: str = "real", ticker: str | None = None) -> list[dict]:
    """Libro de operaciones por orden cronológico (fecha, id): el orden es
    lo que hace válido el FIFO de core_cartera."""
    cli = _cliente()
    if cli is None:
        ops = [o for o in _memoria("operaciones", []) if o.get("origen") == origen]
        if ticker:
            ops = [o for o in ops if o.get("ticker") == ticker]
        return sorted(ops, key=lambda o: (str(o.get("fecha")), abs(o.get("id", 0))))   # ids en memoria: negativos
    try:
        q = cli.table("cartera_operaciones").select("*").eq("origen", origen).order("fecha").order("id")
        if ticker:
            q = q.eq("ticker", ticker)
        return q.execute().data or []
    except Exception:
        return []


def insertar_operacion(fila: dict) -> int | None:
    """Inserta una compra/venta. La validación (no vender más de lo que se
    tiene) es responsabilidad de core_cartera ANTES de llamar aquí."""
    cli = _cliente()
    if cli is None:
        ops = _memoria("operaciones", [])
        fila = {**fila, "id": -(len(ops) + 1), "creado_en": datetime.now(timezone.utc).isoformat()}
        fila.setdefault("origen", "real")
        ops.append(fila)
        return fila["id"]
    try:
        r = cli.table("cartera_operaciones").insert(fila).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def eliminar_operacion(op_id: int) -> bool:
    cli = _cliente()
    if cli is None:
        ops = _memoria("operaciones", [])
        ops[:] = [o for o in ops if o.get("id") != op_id]
        return True
    try:
        cli.table("cartera_operaciones").delete().eq("id", op_id).execute()
        return True
    except Exception:
        return False


def eliminar_posicion(ticker: str, origen: str = "real") -> bool:
    """Botón papelera de la ficha: borra TODAS las operaciones del ticker
    (compras y ventas). Es un borrado del libro, no una venta."""
    cli = _cliente()
    if cli is None:
        ops = _memoria("operaciones", [])
        ops[:] = [o for o in ops if not (o.get("ticker") == ticker and o.get("origen") == origen)]
        return True
    try:
        cli.table("cartera_operaciones").delete().eq("ticker", ticker).eq("origen", origen).execute()
        return True
    except Exception:
        return False


# ------------------------------------------------------------- rastreador --
def listar_universo() -> list[str]:
    """Tickers del universo propio del Rastreador (persistidos)."""
    cli = _cliente()
    if cli is None:
        return sorted(_memoria("universo", set()))
    try:
        return [f["ticker"] for f in cli.table("rastreador_universo").select("ticker").order("ticker").execute().data or []]
    except Exception:
        return []


def anadir_universo(tickers: list[str]) -> bool:
    cli = _cliente()
    tickers = [t for t in dict.fromkeys(t.strip().upper() for t in tickers) if t]
    if not tickers:
        return True
    if cli is None:
        _memoria("universo", set()).update(tickers)
        return True
    try:
        cli.table("rastreador_universo").upsert([{"ticker": t} for t in tickers], on_conflict="ticker").execute()
        return True
    except Exception:
        return False


def quitar_universo(ticker: str) -> bool:
    cli = _cliente()
    if cli is None:
        _memoria("universo", set()).discard(ticker)
        return True
    try:
        cli.table("rastreador_universo").delete().eq("ticker", ticker).execute()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- alertas --
def alertas_ya_enviadas(claves: list[str]) -> set[str]:
    """Claves de deduplicación ya registradas (una consulta)."""
    cli = _cliente()
    if cli is None or not claves:
        return set()
    try:
        filas = cli.table("alertas_enviadas").select("clave_dedup").in_("clave_dedup", claves).execute().data or []
        return {f["clave_dedup"] for f in filas}
    except Exception:
        return set()


def registrar_alerta(tipo: str, ticker: str, clave: str) -> bool:
    cli = _cliente()
    if cli is None:
        return False
    try:
        cli.table("alertas_enviadas").upsert({"tipo": tipo, "ticker": ticker, "clave_dedup": clave},
                                             on_conflict="clave_dedup").execute()
        return True
    except Exception:
        return False
