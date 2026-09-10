"""Envío de alertas por Telegram (Bot API, sin dependencias extra)."""

from __future__ import annotations

import requests

import config_secretos


def enviar(texto: str) -> bool:
    token, chat_id = config_secretos.telegram()
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
        return r.ok
    except requests.RequestException:
        return False
