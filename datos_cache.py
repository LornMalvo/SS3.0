"""Calendario de mercado y "cubo de mercado".

El cubo es una cadena que se pasa como argumento a las funciones cacheadas
de datos: mientras el mercado está cerrado no cambia (la caché queda
congelada, cero peticiones); en sesión cambia una vez por hora (revalidación
horaria). Así el TTL numérico deja de ser el mecanismo real de invalidación
y pasa a ser solo un cinturón de seguridad.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from config_settings import MERCADO_HORA_APERTURA, MERCADO_HORA_CIERRE, MERCADO_ZONA_HORARIA

_TZ = ZoneInfo(MERCADO_ZONA_HORARIA)
_APERTURA = time(*MERCADO_HORA_APERTURA)
_CIERRE = time(*MERCADO_HORA_CIERRE)


def _festivos_nyse(anio: int) -> set[date]:
    """Festivos NYSE de reglas fijas y móviles. Good Friday se calcula con
    Pascua (algoritmo anónimo gregoriano). Si un festivo se traslada por caer
    en fin de semana no se contempla: coste, una petición extra ese día."""
    def n_esimo(mes, weekday, n):
        d = date(anio, mes, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)

    def ultimo(mes, weekday):
        d = date(anio, mes + 1, 1) - timedelta(days=1) if mes < 12 else date(anio, 12, 31)
        return d - timedelta(days=(d.weekday() - weekday) % 7)

    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    pascua = date(anio, mes, dia)

    return {
        date(anio, 1, 1), n_esimo(1, 0, 3), n_esimo(2, 0, 3), pascua - timedelta(days=2),
        ultimo(5, 0), date(anio, 6, 19), date(anio, 7, 4), n_esimo(9, 0, 1),
        n_esimo(11, 3, 4), date(anio, 12, 25),
    }


def es_sesion(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in _festivos_nyse(dia.year)


def ahora_mercado() -> datetime:
    return datetime.now(_TZ)


def mercado_abierto(ahora: datetime | None = None) -> bool:
    ahora = ahora or ahora_mercado()
    return es_sesion(ahora.date()) and _APERTURA <= ahora.time() < _CIERRE


def ultima_sesion_cerrada(ahora: datetime | None = None) -> date:
    """Fecha de la última sesión ya cerrada (hoy si ya pasó el cierre)."""
    ahora = ahora or ahora_mercado()
    dia = ahora.date()
    if not (es_sesion(dia) and ahora.time() >= _CIERRE):
        dia -= timedelta(days=1)
    while not es_sesion(dia):
        dia -= timedelta(days=1)
    return dia


def cubo_mercado(ahora: datetime | None = None) -> str:
    ahora = ahora or ahora_mercado()
    if mercado_abierto(ahora):
        return f"sesion:{ahora:%Y-%m-%d-%H}"
    return f"cerrado:{ultima_sesion_cerrada(ahora):%Y-%m-%d}"


def antiguedad_seg(obtenido_en: datetime | None) -> float | None:
    if obtenido_en is None:
        return None
    return (datetime.now(obtenido_en.tzinfo) - obtenido_en).total_seconds()
