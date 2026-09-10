"""Evaluación periódica de alertas. Lo ejecuta GitHub Actions (cron), fuera de
Streamlit Cloud, que no tiene planificador.

Flujo previsto (sesión 5): leer planes activos y posiciones abiertas de
Supabase → una sola descarga por lote de precios → evaluar reglas de
core_alertas → deduplicar contra `alertas_enviadas` → enviar por Telegram.
Hoy solo verifica conectividad, para que el workflow quede validado desde el
principio.
"""

from __future__ import annotations

import sys

import config_secretos
import datos_telegram


def main() -> int:
    url, key = config_secretos.supabase()
    token, chat = config_secretos.telegram()
    print(f"Supabase configurado: {bool(url and key)} · Telegram configurado: {bool(token and chat)}")
    if "--prueba" in sys.argv:
        ok = datos_telegram.enviar("StockScanner: prueba de alertas OK")
        print(f"Mensaje de prueba enviado: {ok}")
    print("Sin reglas de alerta registradas todavía (sesión 5).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
