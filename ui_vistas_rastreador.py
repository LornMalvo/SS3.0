"""Rastreador — hueco funcional. La lógica llega en la sesión indicada."""

from __future__ import annotations

import ui_componentes as ui


def render() -> None:
    with ui.tarjeta("Rastreador"):
        ui.pendiente("Análisis en bloque con descarga por lote, filtros por calidad / infravaloración / timing y ranking comparativo con vista lado a lado de 2-3 tickers. Sesión 5 (requiere los tres motores).")
