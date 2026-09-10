"""Panel de métricas del Bloque 3, bajo el gráfico: FUNDAMENTALES (tamaño,
valoración, rentabilidad, balance y caja) y TÉCNICOS. Las comparativas
"vs media sector" leen las tablas de config_sectores y se etiquetan como
referencia de sector; sin sector conocido no se muestra referencia alguna.

Cada valor lleva un semáforo (verde bueno / rojo malo / neutro) calculado en
core_interpretar; bajo RSI, ADX y short interest se añade una frase que
traduce el número a una lectura (zona, tendencia y dirección, sentimiento).
"""

from __future__ import annotations

import streamlit as st

import config_sectores as sec
import core_interpretar as ci
import ui_componentes as ui
from core_ponderar import es_dato


def _ref(tabla: dict, sector: str | None, fmt) -> tuple[str | None, float | None]:
    v = tabla.get(sector) if sector else None
    return (f"sector {fmt(v)}", v) if es_dato(v) else (None, None)


def _ratio(v, decimales: int = 1) -> str:
    return ui.fmt_num(v, decimales) if es_dato(v) else ui.TEXTO_ND


def _pct(v) -> str:
    return ui.fmt_pct(v * 100, signo=False) if es_dato(v) else ui.TEXTO_ND


def _subtitulo(texto: str) -> None:
    st.markdown(f'<div class="ss-racha-tit">{texto}</div>', unsafe_allow_html=True)


def _titulo(texto: str) -> None:
    st.markdown(f'<div class="ss-etiqueta" style="margin-top:.6rem">{texto}</div>', unsafe_allow_html=True)


def _vs_sector(etiqueta: str, valor, tabla: dict, sector: str | None, fmt_valor, fmt_ref,
               menor_mejor: bool, clave_abs: str | None = None) -> None:
    """Fila con referencia sectorial y semáforo relativo; sin referencia,
    semáforo absoluto si la métrica lo tiene definido."""
    ref_txt, ref = _ref(tabla, sector, fmt_ref)
    sem = ci.semaforo_relativo(valor, ref, menor_mejor) if ref is not None else ci.semaforo_absoluto(clave_abs or "", valor)
    ui.metrica(etiqueta, fmt_valor(valor), ref_txt, sem)


def render(fund: dict, ind: dict, ind_extra: dict | None = None) -> None:
    """`fund`: dict de core_fundamentales.extraer; `ind`: core_indicadores.resumen."""
    sector = fund.get("sector")
    divisa = fund.get("divisa")
    importe = lambda v: ui.fmt_importe(v, divisa)  # noqa: E731
    f1 = lambda v: ui.fmt_num(v, 1)  # noqa: E731
    f2 = lambda v: ui.fmt_num(v, 2)  # noqa: E731

    col_f, col_t = st.columns([1.35, 1])

    with col_f:
        _titulo("Fundamentales")
        ui.metrica("Capitalización", importe(fund.get("capitalizacion")))
        ui.metrica("Acciones en circulación", ui.fmt_grande(fund.get("acciones")))

        _subtitulo("Valoración")
        ui.metrica("PER (trailing)", _ratio(fund.get("per_trailing")),
                   semaforo=ci.semaforo_absoluto("per_trailing", fund.get("per_trailing")))
        _vs_sector("PER forward", fund.get("per_forward"), sec.PER_FORWARD_SECTOR, sector, _ratio, f1, True)
        _vs_sector("PEG", fund.get("peg"), sec.PEG_SECTOR, sector, lambda v: _ratio(v, 2), f2, True)
        ui.metrica("Precio / Ventas", _ratio(fund.get("precio_ventas"), 2),
                   semaforo=ci.semaforo_absoluto("precio_ventas", fund.get("precio_ventas")))
        ui.metrica("Precio / Valor contable", _ratio(fund.get("precio_valor_contable"), 2),
                   semaforo=ci.semaforo_absoluto("precio_valor_contable", fund.get("precio_valor_contable")))
        _vs_sector("EV / EBITDA", fund.get("ev_ebitda"), sec.EV_EBITDA_SECTOR, sector, _ratio, f1, True)

        _subtitulo("Rentabilidad")
        _vs_sector("Margen neto", fund.get("margen_neto"), sec.MARGEN_NETO_SECTOR, sector, _pct, _pct, False)
        _vs_sector("Margen operativo", fund.get("margen_operativo"), sec.MARGEN_OPERATIVO_SECTOR, sector,
                   _pct, _pct, False)
        ui.metrica("Margen EBITDA", _pct(fund.get("margen_ebitda")),
                   semaforo=ci.semaforo_absoluto("margen_ebitda", fund.get("margen_ebitda")))
        _vs_sector("ROE", fund.get("roe"), sec.ROE_SECTOR, sector, _pct, _pct, False)
        _vs_sector("ROIC", fund.get("roic"), sec.ROIC_SECTOR, sector, _pct, _pct, False)
        ui.metrica("ROA", _pct(fund.get("roa")), semaforo=ci.semaforo_absoluto("roa", fund.get("roa")))

        _subtitulo("Balance y caja")
        ui.metrica("Caja total", importe(fund.get("caja_total")))
        ui.metrica("Deuda total", importe(fund.get("deuda_total")))
        ui.metrica("Deuda / Equity", _ratio(fund.get("deuda_patrimonio"), 2),
                   semaforo=ci.semaforo_absoluto("deuda_patrimonio", fund.get("deuda_patrimonio")))
        ui.metrica("Current ratio", _ratio(fund.get("current_ratio"), 2),
                   semaforo=ci.semaforo_absoluto("current_ratio", fund.get("current_ratio")))
        ui.metrica("Flujo de caja operativo", importe(fund.get("flujo_caja_operativo")),
                   semaforo=ci.semaforo_signo(fund.get("flujo_caja_operativo")))
        ui.metrica("Free cash flow", importe(fund.get("flujo_caja_libre")),
                   semaforo=ci.semaforo_signo(fund.get("flujo_caja_libre")))

    with col_t:
        _titulo("Técnicos")
        txt_rsi, sem_rsi = ci.rsi(ind.get("rsi"))
        ui.metrica("RSI (14)", _ratio(ind.get("rsi")), semaforo=sem_rsi)
        ui.lectura(txt_rsi, sem_rsi)

        sem_macd = ci.semaforo_macd(ind.get("macd"), ind.get("macd_senal"))
        ui.metrica("MACD", _ratio(ind.get("macd"), 3), semaforo=sem_macd)
        ui.metrica("Señal MACD", _ratio(ind.get("macd_senal"), 3))

        txt_adx, sem_adx = ci.adx(ind.get("adx"), ind.get("di_pos"), ind.get("di_neg"))
        ui.metrica("ADX (14)", _ratio(ind.get("adx")), semaforo=sem_adx)
        ui.lectura(txt_adx, sem_adx)

        ui.metrica("ATR (14)", _ratio(ind.get("atr"), 2), ui.fmt_pct(ind.get("atr_pct"), signo=False))
        for etiqueta, clave, dist in (("MM50", "mm50", "dist_mm50"), ("MM100", "mm100", "dist_mm100"),
                                      ("MM200", "mm200", "dist_mm200")):
            ui.metrica(etiqueta, _ratio(ind.get(clave), 2), ui.fmt_pct(ind.get(dist)),
                       semaforo=ci.semaforo_encima(ind.get(dist)))
        ui.metrica("Máximo 52 semanas", _ratio(ind.get("max_52s"), 2),
                   ui.fmt_pct(_dist(ind.get("precio"), ind.get("max_52s"))))
        ui.metrica("Mínimo 52 semanas", _ratio(ind.get("min_52s"), 2),
                   ui.fmt_pct(_dist(ind.get("precio"), ind.get("min_52s"))))
        ui.metrica("Variación 1 año", ui.fmt_pct(ind.get("variacion_1a")),
                   semaforo=ci.semaforo_signo(ind.get("variacion_1a")))
        ui.metrica("Volumen medio 3 meses", ui.fmt_grande(fund.get("volumen_medio_3m")))

        txt_si, sem_si = ci.short_interest(fund.get("short_interest"), fund.get("short_ratio"))
        ui.metrica("Short interest", _pct(fund.get("short_interest")), semaforo=sem_si)
        ui.metrica("Short ratio (días para cubrir)", _ratio(fund.get("short_ratio")),
                   semaforo=ci.semaforo_absoluto("short_ratio", fund.get("short_ratio")))
        ui.lectura(txt_si, sem_si)
        ui.metrica("Beta (β)", _ratio(fund.get("beta"), 2))


def _dist(precio, referencia) -> float | None:
    if not es_dato(precio) or not es_dato(referencia) or not referencia:
        return None
    return (precio / referencia - 1) * 100
