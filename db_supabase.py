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


def sectores_conocidos(tickers: tuple[str, ...]) -> dict[str, str]:
    """Sector de cada ticker según su ÚLTIMO análisis guardado (el JSON de
    `entradas` lleva los fundamentales, sector incluido). Cero peticiones a
    Yahoo para lo ya analizado; la vista solo pide `info` para lo que falte."""
    cli = _cliente()
    if cli is None or not tickers:
        return {}
    try:
        filas = (cli.table("analisis_historico").select("ticker,fecha_analisis,entradas")
                 .in_("ticker", list(tickers)).order("fecha_analisis", desc=True).limit(len(tickers) * 5)
                 .execute().data or [])
    except Exception:
        return {}
    sectores: dict[str, str] = {}
    for f in filas:                                  # más reciente primero: el primero que aparece manda
        sector = (f.get("entradas") or {}).get("sector")
        if sector and f["ticker"] not in sectores:
            sectores[f["ticker"]] = sector
    return sectores


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
