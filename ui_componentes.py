"""Piezas visuales compartidas por todas las vistas."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import streamlit as st

from config_settings import C_ROJO, C_TEXTO_TENUE, C_VERDE, FRESCURA_ESPERADA, TEXTO_ND
from core_ponderar import es_dato
from datos_cache import antiguedad_seg
from datos_yfinance import convertir_a_eur

# Color del valor de una métrica según su lectura (core_interpretar.SEMAFORO).
COLOR_SEMAFORO = {"bien": C_VERDE, "mal": C_ROJO}


@contextmanager
def tarjeta(titulo: str | None = None):
    """Tarjeta con borde redondeado (18px vía CSS) que admite widgets dentro."""
    with st.container(border=True):
        if titulo:
            st.markdown(f'<div class="ss-card-titulo">{titulo}</div>', unsafe_allow_html=True)
        yield


def escapar(texto: str) -> str:
    """Streamlit interpreta pares de `$` como LaTeX, así que el símbolo se
    neutraliza siempre en texto dinámico (convención del proyecto).

    Se usa la entidad HTML `&#36;` y no la barra `\\$`: dentro de un bloque
    HTML (todo lo que pintamos con unsafe_allow_html) Markdown no procesa
    escapes, así que la barra se mostraba literalmente ("207,17 \\$"). La
    entidad la resuelve el navegador en ambos contextos y nunca dispara
    LaTeX."""
    return (texto or "").replace("$", "&#36;")


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
    """Importe grande en MILLONES enteros ("2960 M", "3.500.000 M"): un solo
    orden de magnitud en toda la app, así "2960 M$ (2580 M€)" se lee de un
    vistazo y sin la ambigüedad de mM/B (decisión de Samuel, sesión 6).
    Sin separador de miles hasta cuatro cifras (convención española); por
    debajo de un millón se muestra el número tal cual."""
    if not es_dato(valor):
        return TEXTO_ND
    v = float(valor)
    if abs(v) < 1e6:
        return fmt_num(v, 0)
    millones = round(v / 1e6)
    txt = f"{millones}" if abs(millones) < 10000 else fmt_num(millones, 0)
    return f"{txt} M"


def _con_simbolo(texto: str, simbolo: str) -> str:
    """"2960 M" + "$" -> "2960 M$"; "850.000" + "$" -> "850.000 $"."""
    if not simbolo:
        return texto
    return f"{texto}{simbolo}" if texto.endswith(" M") else f"{texto} {simbolo}"


def fmt_importe(valor, divisa: str | None) -> str:
    """Importe grande (capitalización, caja, FCF) en su divisa y, si no es
    EUR, su conversión entre paréntesis: "2960 M$ (2580 M€)"."""
    if not es_dato(valor):
        return TEXTO_ND
    simbolo = {"USD": "$", "EUR": "€", "GBP": "£"}.get(divisa or "", divisa or "")
    base = _con_simbolo(fmt_grande(valor), simbolo)
    if divisa == "EUR" or not divisa:
        return base
    eur, _ = convertir_a_eur(valor, divisa)
    return f"{base} ({_con_simbolo(fmt_grande(eur), '€')})" if eur is not None else base


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


def metrica(etiqueta: str, valor: str, referencia: str | None = None, semaforo: str | None = None,
            color_en: str = "valor") -> None:
    """Fila etiqueta / valor. `semaforo` ("bien" | "mal" | None) colorea en
    verde o rojo; sin lectura clara se deja en el color del texto.

    `color_en` decide QUÉ se colorea: "valor" (por defecto) tiñe el dato;
    "referencia" tiñe solo el texto de referencia y deja el dato neutro. Es el
    caso de las medias móviles y los extremos de 52 semanas: el nivel en sí
    (4,14 $) no es bueno ni malo, lo que tiene lectura es la distancia del
    precio a ese nivel (-22,9 %)."""
    color = COLOR_SEMAFORO.get(semaforo or "")
    estilo_valor = f' style="color:{color}"' if color and color_en == "valor" else ""
    ref = ""
    if referencia:
        clase = "ss-ref-semaforo" if color and color_en == "referencia" else "ss-media-sector"
        estilo_ref = f' style="color:{color}"' if color and color_en == "referencia" else ""
        ref = f'<span class="{clase}"{estilo_ref}>{escapar(referencia)}</span>'
    st.markdown(
        f'<div class="ss-metrica"><span>{etiqueta}</span><span{estilo_valor}>{escapar(valor)}{ref}</span></div>',
        unsafe_allow_html=True,
    )


def lectura(texto: str, semaforo: str | None = None) -> None:
    """Frase de interpretación bajo una métrica (zona del RSI, tendencia del
    ADX, sentimiento...). El borde izquierdo toma el color del semáforo."""
    color = COLOR_SEMAFORO.get(semaforo or "", C_TEXTO_TENUE)
    st.markdown(f'<div class="ss-lectura" style="border-left-color:{color}">{escapar(texto)}</div>',
                unsafe_allow_html=True)


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


def rejilla(elementos: list, pintar, columnas: int = 3) -> None:
    """Fichas en una rejilla de N columnas FILA A FILA: cada fila es un
    `st.columns` nuevo, así los bordes superiores de las fichas de una misma
    fila quedan alineados aunque las fichas tengan alturas distintas (con
    un solo st.columns cada columna apila a su ritmo y la segunda fila se
    desalinea, que era lo que pasaba en Paper Trading). `pintar(elemento)`
    dibuja una ficha."""
    for i in range(0, len(elementos), columnas):
        cols = st.columns(columnas)
        for col, e in zip(cols, elementos[i:i + columnas]):
            with col:
                pintar(e)


def nd(texto: str = TEXTO_ND) -> None:
    st.markdown(f'<span class="ss-nd" style="color:{C_TEXTO_TENUE}">{texto}</span>',
                unsafe_allow_html=True)
