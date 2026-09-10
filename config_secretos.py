"""Secretos: `st.secrets` dentro de la app, variables de entorno en el cron
de GitHub Actions. Misma clave en los dos sitios.

Claves esperadas: SUPABASE_URL, SUPABASE_KEY, FINNHUB_KEY, TELEGRAM_TOKEN,
TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import os


def obtener(clave: str, defecto: str | None = None) -> str | None:
    try:
        import streamlit as st  # noqa: WPS433 — import perezoso: el cron no tiene runtime
        if clave in st.secrets:
            return str(st.secrets[clave])
    except Exception:
        pass
    return os.environ.get(clave, defecto)


def supabase() -> tuple[str | None, str | None]:
    return obtener("SUPABASE_URL"), obtener("SUPABASE_KEY")


def finnhub() -> str | None:
    return obtener("FINNHUB_KEY")


def telegram() -> tuple[str | None, str | None]:
    return obtener("TELEGRAM_TOKEN"), obtener("TELEGRAM_CHAT_ID")
