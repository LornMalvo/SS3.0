"""Piezas visuales compartidas por todas las vistas."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import streamlit as st

from config_settings import C_TEXTO_TENUE, FRESCURA_ESPERADA, TEXTO_ND
from core_ponderar import es_dato
from datos_cache import antiguedad_seg
from datos_yfinance import convertir_a_eur


@contextmanager
def tarjeta(titulo: str | None = None):
    """Tarjeta con borde redondeado (18px vía CSS) que admite widgets dentro."""
    with st.container(border=True):
        if titulo:
            st.markdown(f'<div class="ss-card-titulo">{titulo}</div>', unsafe_allow_html=True)
        yield


def escapar(texto: str) -> str:
    """Streamlit interpreta pares de `$` como LaTeX: se escapan siempre en
    texto dinámico (convención del proyecto)."""
    return (texto or "").replace("$", r"\$")


def fmt_num(valor, decimales: int = 2, sufijo: str = "") -> str:
    if not es_dato(valor):
        return TEXTO_ND
    return f"{float(valor):,.{decimales}f}{sufijo}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(valor, decimales: int = 1, signo: bool = True) -> str:
    if not es_dato(valor):
        return TEXTO_ND
    v = float(valor)
    s = "+" if (signo and v > 0) else ""
    return f"{s}{fmt_num(v, decimales)} %"


def fmt_grande(valor) -> str:
    """Capitalización, EBITDA... en M/B con separador español."""
    if not es_dato(valor):
        return TEXTO_ND
    v = float(valor)
    for umbral, letra in ((1e12, "B"), (1e9, "mM"), (1e6, "M")):
        if abs(v) >= umbral:
            return f"{fmt_num(v / umbral, 2)} {letra}"
    return fmt_num(v, 0)


def fmt_precio(valor, divisa: str | None, decimales: int = 2) -> str:
    """Precio en su divisa y, si no es EUR, su equivalente en EUR entre
    paréntesis (convención global de la app)."""
    if not es_dato(valor):
        return TEXTO_ND
    simbolo = {"USD": "$", "EUR": "€", "GBP": "£"}.get(divisa or "", divisa or "")
    base = f"{fmt_num(valor, decimales)} {simbolo}".strip()
    if divisa == "EUR":
        return base
    eur, _ = convertir_a_eur(valor, divisa)
    return f"{base} ({fmt_num(eur, decimales)} €)" if eur is not None else f"{base} (EUR {TEXTO_ND.lower()})"


def metrica(etiqueta: str, valor: str, referencia: str | None = None) -> None:
    ref = f'<span class="ss-media-sector">{referencia}</span>' if referencia else ""
    st.markdown(
        f'<div class="ss-metrica"><span>{etiqueta}</span><span>{escapar(valor)}{ref}</span></div>',
        unsafe_allow_html=True,
    )


def badge(texto: str, color: str) -> str:
    return f'<span class="ss-badge" style="background:{color}">{texto}</span>'


def alerta(texto: str, color: str) -> None:
    st.markdown(f'<div class="ss-alerta" style="background:{color}">{escapar(texto)}</div>',
                unsafe_allow_html=True)


def frescura(obtenido_en: datetime | None, fuente: str, tipo: str) -> None:
    """Indicador de frescura y fuente de un bloque, con aviso si supera la
    antigüedad esperada para ese tipo de dato."""
    seg = antiguedad_seg(obtenido_en)
    if seg is None:
        st.markdown(f'<div class="ss-frescura">Fuente: {fuente} · sin sello de tiempo</div>',
                    unsafe_allow_html=True)
        return
    if seg < 60:
        edad = "hace menos de un minuto"
    elif seg < 3600:
        edad = f"hace {int(seg // 60)} min"
    elif seg < 86400:
        edad = f"hace {int(seg // 3600)} h"
    else:
        edad = f"hace {int(seg // 86400)} d"
    aviso = seg > FRESCURA_ESPERADA.get(tipo, 86400)
    clase = "ss-frescura ss-frescura-aviso" if aviso else "ss-frescura"
    texto = f"Fuente: {fuente} · {edad}" + (" · ⚠ dato más antiguo de lo esperado" if aviso else "")
    st.markdown(f'<div class="{clase}">{texto}</div>', unsafe_allow_html=True)


def pendiente(texto: str) -> None:
    st.markdown(f'<div class="ss-pendiente">{texto}</div>', unsafe_allow_html=True)


def nd(texto: str = TEXTO_ND) -> None:
    st.markdown(f'<span class="ss-nd" style="color:{C_TEXTO_TENUE}">{texto}</span>',
                unsafe_allow_html=True)
