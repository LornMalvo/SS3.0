"""Panel de métricas del Bloque 3, bajo el gráfico: FUNDAMENTALES (tamaño,
valoración, rentabilidad, balance y caja) y TÉCNICOS. Las comparativas
"vs media sector" leen las tablas de config_sectores y se etiquetan como
referencia de sector; sin sector conocido no se muestra referencia alguna.
"""

from __future__ import annotations

import streamlit as st

import config_sectores as sec
import ui_componentes as ui
from core_ponderar import es_dato


def _ref(tabla: dict, sector: str | None, fmt) -> str | None:
    v = tabla.get(sector) if sector else None
    return f"sector {fmt(v)}" if es_dato(v) else None


def _ratio(v, decimales: int = 1) -> str:
    return ui.fmt_num(v, decimales) if es_dato(v) else ui.TEXTO_ND


def _pct(v) -> str:
    return ui.fmt_pct(v * 100, signo=False) if es_dato(v) else ui.TEXTO_ND


def _subtitulo(texto: str) -> None:
    st.markdown(f'<div class="ss-racha-tit">{texto}</div>', unsafe_allow_html=True)


def _titulo(texto: str) -> None:
    st.markdown(f'<div class="ss-etiqueta" style="margin-top:.6rem">{texto}</div>', unsafe_allow_html=True)


def render(fund: dict, ind: dict, ind_extra: dict | None = None) -> None:
    """`fund`: dict de core_fundamentales.extraer; `ind`: core_indicadores.resumen."""
    sector = fund.get("sector")
    divisa = fund.get("divisa")
    importe = lambda v: ui.fmt_importe(v, divisa)  # noqa: E731

    col_f, col_t = st.columns([1.35, 1])

    with col_f:
        _titulo("Fundamentales")
        ui.metrica("Capitalización", importe(fund.get("capitalizacion")))
        ui.metrica("Acciones en circulación", ui.fmt_grande(fund.get("acciones")))

        _subtitulo("Valoración")
        ui.metrica("PER (trailing)", _ratio(fund.get("per_trailing")))
        ui.metrica("PER forward", _ratio(fund.get("per_forward")),
                   _ref(sec.PER_FORWARD_SECTOR, sector, lambda v: ui.fmt_num(v, 1)))
        ui.metrica("PEG", _ratio(fund.get("peg"), 2), _ref(sec.PEG_SECTOR, sector, lambda v: ui.fmt_num(v, 2)))
        ui.metrica("Precio / Ventas", _ratio(fund.get("precio_ventas"), 2))
        ui.metrica("Precio / Valor contable", _ratio(fund.get("precio_valor_contable"), 2))
        ui.metrica("EV / EBITDA", _ratio(fund.get("ev_ebitda")),
                   _ref(sec.EV_EBITDA_SECTOR, sector, lambda v: ui.fmt_num(v, 1)))

        _subtitulo("Rentabilidad")
        ui.metrica("Margen neto", _pct(fund.get("margen_neto")), _ref(sec.MARGEN_NETO_SECTOR, sector, _pct))
        ui.metrica("Margen operativo", _pct(fund.get("margen_operativo")),
                   _ref(sec.MARGEN_OPERATIVO_SECTOR, sector, _pct))
        ui.metrica("Margen EBITDA", _pct(fund.get("margen_ebitda")))
        ui.metrica("ROE", _pct(fund.get("roe")), _ref(sec.ROE_SECTOR, sector, _pct))
        ui.metrica("ROIC", _pct(fund.get("roic")), _ref(sec.ROIC_SECTOR, sector, _pct))
        ui.metrica("ROA", _pct(fund.get("roa")))

        _subtitulo("Balance y caja")
        ui.metrica("Caja total", importe(fund.get("caja_total")))
        ui.metrica("Deuda total", importe(fund.get("deuda_total")))
        ui.metrica("Deuda / Equity", _ratio(fund.get("deuda_patrimonio"), 2))
        ui.metrica("Current ratio", _ratio(fund.get("current_ratio"), 2))
        ui.metrica("Flujo de caja operativo", importe(fund.get("flujo_caja_operativo")))
        ui.metrica("Free cash flow", importe(fund.get("flujo_caja_libre")))

    with col_t:
        _titulo("Técnicos")
        ui.metrica("RSI (14)", _ratio(ind.get("rsi")))
        ui.metrica("MACD", _ratio(ind.get("macd"), 3))
        ui.metrica("Señal MACD", _ratio(ind.get("macd_senal"), 3))
        ui.metrica("ADX (14)", _ratio(ind.get("adx")))
        ui.metrica("ATR (14)", _ratio(ind.get("atr"), 2), ui.fmt_pct(ind.get("atr_pct"), signo=False))
        ui.metrica("MM50", _ratio(ind.get("mm50"), 2), ui.fmt_pct(ind.get("dist_mm50")))
        ui.metrica("MM100", _ratio(ind.get("mm100"), 2), ui.fmt_pct(ind.get("dist_mm100")))
        ui.metrica("MM200", _ratio(ind.get("mm200"), 2), ui.fmt_pct(ind.get("dist_mm200")))
        ui.metrica("Máximo 52 semanas", _ratio(ind.get("max_52s"), 2),
                   ui.fmt_pct(_dist(ind.get("precio"), ind.get("max_52s"))))
        ui.metrica("Mínimo 52 semanas", _ratio(ind.get("min_52s"), 2),
                   ui.fmt_pct(_dist(ind.get("precio"), ind.get("min_52s"))))
        ui.metrica("Variación 1 año", ui.fmt_pct(ind.get("variacion_1a")))
        ui.metrica("Volumen medio 3 meses", ui.fmt_grande(fund.get("volumen_medio_3m")))
        ui.metrica("Short interest", _pct(fund.get("short_interest")))
        ui.metrica("Short ratio (días para cubrir)", _ratio(fund.get("short_ratio")))
        ui.metrica("Beta (β)", _ratio(fund.get("beta"), 2))


def _dist(precio, referencia) -> float | None:
    if not es_dato(precio) or not es_dato(referencia) or not referencia:
        return None
    return (precio / referencia - 1) * 100
