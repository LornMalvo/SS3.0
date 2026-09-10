"""Paper Trading — hueco funcional. La lógica llega en la sesión indicada."""

from __future__ import annotations

import ui_componentes as ui


def render() -> None:
    with ui.tarjeta("Paper Trading"):
        ui.pendiente("Máquina de estados vigilancia → parcial_entrada → abierta → parcial_salida → cerrada (+ descartada), ejecución de niveles delegada en Cartera y rendimiento simulado frente al benchmark. Sesión 4.")
