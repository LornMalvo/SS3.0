"""Regla de oro del proyecto: un dato ausente NUNCA se convierte en cero.

Todo cálculo ponderado (Calidad, Fair Value, Timing, veredicto) pasa por
`ponderar()`, que excluye los componentes sin dato, reparte su peso entre los
disponibles y devuelve la cobertura real para que la interfaz la enseñe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def es_dato(valor) -> bool:
    """True si `valor` es un número utilizable (ni None, ni NaN, ni infinito)."""
    if valor is None:
        return False
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(v) or math.isinf(v))


@dataclass(frozen=True)
class Ponderado:
    valor: float | None
    cobertura: float                     # peso disponible / peso total (0-1)
    peso_total: float
    peso_disponible: float
    usados: dict[str, float] = field(default_factory=dict)      # clave -> peso efectivo (suma 1)
    excluidos: dict[str, str] = field(default_factory=dict)     # clave -> motivo

    @property
    def cobertura_pct(self) -> float:
        return round(self.cobertura * 100, 1)

    @property
    def fiable(self) -> bool:
        return self.valor is not None


def ponderar(
    componentes: dict[str, tuple[float, float | None]],
    cobertura_minima: float = 0.0,
    motivos: dict[str, str] | None = None,
) -> Ponderado:
    """Media ponderada con exclusión y redistribución.

    `componentes`: clave -> (peso, valor). Un valor None/NaN se excluye y su
    peso se reparte proporcionalmente entre los demás. Si la cobertura queda
    por debajo de `cobertura_minima`, el resultado es None: con demasiados
    huecos, la redistribución ya no rellena, inventa.
    `motivos`: texto opcional por clave para explicar en la interfaz por qué
    falta (p. ej. "sin EBITDA positivo").
    """
    motivos = motivos or {}
    peso_total = float(sum(p for p, _ in componentes.values()))
    if peso_total <= 0:
        return Ponderado(None, 0.0, 0.0, 0.0)

    disponibles = {k: (p, float(v)) for k, (p, v) in componentes.items() if es_dato(v) and p > 0}
    excluidos = {
        k: motivos.get(k, "sin dato")
        for k in componentes
        if k not in disponibles
    }
    peso_disponible = float(sum(p for p, _ in disponibles.values()))
    cobertura = peso_disponible / peso_total

    if peso_disponible <= 0 or cobertura < cobertura_minima:
        return Ponderado(None, cobertura, peso_total, peso_disponible, {}, excluidos)

    usados = {k: p / peso_disponible for k, (p, _) in disponibles.items()}
    valor = sum(usados[k] * v for k, (_, v) in disponibles.items())
    return Ponderado(valor, cobertura, peso_total, peso_disponible, usados, excluidos)


def puntuar_tramos(valor, tramos: list[tuple[float, float]]) -> float | None:
    """Interpola linealmente `valor` sobre `tramos` = [(x, puntos), ...]
    ordenados por x. Fuera del rango devuelve el extremo. None si no hay dato.
    Es la forma canónica de convertir una métrica cruda en 0-100."""
    if not es_dato(valor) or not tramos:
        return None
    v = float(valor)
    if v <= tramos[0][0]:
        return float(tramos[0][1])
    if v >= tramos[-1][0]:
        return float(tramos[-1][1])
    for (x0, y0), (x1, y1) in zip(tramos, tramos[1:]):
        if x0 <= v <= x1:
            if x1 == x0:
                return float(y1)
            return float(y0 + (y1 - y0) * (v - x0) / (x1 - x0))
    return None


def acotar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))
