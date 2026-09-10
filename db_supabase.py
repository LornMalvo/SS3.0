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
