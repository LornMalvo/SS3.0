"""Gestión de Cartera — hueco funcional. La lógica llega en la sesión indicada."""

from __future__ import annotations

import ui_componentes as ui


def render() -> None:
    with ui.tarjeta("Gestión de Cartera"):
        ui.pendiente("Libro de operaciones con coste medio ponderado (interfaz) y FIFO (fiscal), comisiones, divisa base EUR, rendimiento frente a benchmark y riesgo por sector/correlación. Sesión 4.")
