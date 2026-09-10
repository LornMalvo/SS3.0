"""Interpretación de métricas para el panel del Bloque 3: semáforo
("bien" / "mal" / None) por métrica y frases de lectura (zona del RSI,
fuerza y dirección del ADX, sentimiento por short interest).

Funciones puras: reciben números y devuelven etiquetas. Los umbrales viven
en config_settings (bloque INTERPRETACIÓN). Un dato ausente devuelve None y
texto "no disponible": nunca se colorea lo que no existe.
"""

from __future__ import annotations

from config_settings import (
    ADX_FUERZA,
    ADX_TENDENCIA_MIN,
    RSI_ZONAS,
    SEMAFORO_ABSOLUTO,
    SEMAFORO_RATIO_MAYOR_MEJOR,
    SEMAFORO_RATIO_MENOR_MEJOR,
    SHORT_INTEREST_TRAMOS,
    SHORT_RATIO_SQUEEZE,
    TEXTO_ND,
)
from core_ponderar import es_dato

BIEN, MAL = "bien", "mal"


# ------------------------------------------------------------- semáforos ----
def semaforo_relativo(valor, referencia, menor_mejor: bool) -> str | None:
    """Juzga `valor` por su cociente frente a la referencia sectorial."""
    if not es_dato(valor) or not es_dato(referencia) or referencia <= 0:
        return None
    if valor < 0 and not menor_mejor:
        return MAL                      # margen o retorno negativo: malo sin más
    if valor <= 0 and menor_mejor:
        return None                     # múltiplo negativo no es "barato", es sin beneficio
    ratio = valor / referencia
    lo, hi = SEMAFORO_RATIO_MENOR_MEJOR if menor_mejor else SEMAFORO_RATIO_MAYOR_MEJOR
    if menor_mejor:
        return BIEN if ratio <= lo else MAL if ratio >= hi else None
    return BIEN if ratio >= hi else MAL if ratio <= lo else None


def semaforo_absoluto(clave: str, valor) -> str | None:
    if not es_dato(valor) or clave not in SEMAFORO_ABSOLUTO:
        return None
    sentido, verde, rojo = SEMAFORO_ABSOLUTO[clave]
    if sentido == "menor":
        if valor <= 0:
            return None
        return BIEN if valor <= verde else MAL if valor >= rojo else None
    return BIEN if valor >= verde else MAL if valor <= rojo else None


def semaforo_signo(valor) -> str | None:
    """Verde si positivo, rojo si negativo (FCF, flujo operativo, variación)."""
    if not es_dato(valor):
        return None
    return BIEN if valor > 0 else MAL if valor < 0 else None


def semaforo_encima(valor) -> str | None:
    """Distancia (%) del precio a una media: por encima verde, por debajo rojo."""
    return semaforo_signo(valor)


def semaforo_macd(macd, senal) -> str | None:
    if not es_dato(macd) or not es_dato(senal):
        return None
    return BIEN if macd > senal else MAL if macd < senal else None


# -------------------------------------------------------------- lecturas ----
def rsi(valor) -> tuple[str, str | None]:
    """(texto, semáforo). Sobreventa se lee en verde: para quien busca
    comprar, es donde el riesgo asimétrico está a favor."""
    if not es_dato(valor):
        return f"RSI {TEXTO_ND.lower()}", None
    for tope, etiqueta, sem in RSI_ZONAS:
        if valor < tope:
            return f"RSI {valor:.0f}: {etiqueta}", sem
    return f"RSI {valor:.0f}: {RSI_ZONAS[-1][1]}", RSI_ZONAS[-1][2]


def adx(valor, di_pos, di_neg) -> tuple[str, str | None]:
    """Fuerza por tramos de ADX y dirección por +DI/-DI. Sin tendencia (ADX
    bajo) la dirección no se afirma: los DI cruzan constantemente en rango."""
    if not es_dato(valor):
        return f"ADX {TEXTO_ND.lower()}", None
    fuerza = next((e for tope, e in ADX_FUERZA if valor < tope), ADX_FUERZA[-1][1])
    if not es_dato(di_pos) or not es_dato(di_neg):
        return f"ADX {valor:.0f}: {fuerza}", None
    alcista = di_pos > di_neg
    if valor < ADX_TENDENCIA_MIN:
        sesgo = "sesgo alcista" if alcista else "sesgo bajista"
        return f"ADX {valor:.0f}: {fuerza}, {sesgo} sin confirmar (+DI {di_pos:.0f} / -DI {di_neg:.0f})", None
    direccion = "ALCISTA" if alcista else "BAJISTA"
    return (f"ADX {valor:.0f}: {fuerza} {direccion} (+DI {di_pos:.0f} / -DI {di_neg:.0f})",
            BIEN if alcista else MAL)


def short_interest(pct_float, dias_cubrir) -> tuple[str, str | None]:
    """Sentimiento del mercado a partir del % del float en corto y los días
    para cubrir. Un short ratio alto sobre un short interest alto es
    combustible de squeeze: se avisa, pero no se colorea en verde, porque
    sigue siendo una apuesta binaria."""
    if not es_dato(pct_float):
        return f"Short interest {TEXTO_ND.lower()}: sin lectura de sentimiento", None
    for tope, etiqueta, sem in SHORT_INTEREST_TRAMOS:
        if pct_float < tope:
            break
    else:
        etiqueta, sem = SHORT_INTEREST_TRAMOS[-1][1:]
    texto = f"Short interest {pct_float * 100:.1f} % del float: {etiqueta}"
    if es_dato(dias_cubrir):
        if dias_cubrir >= SHORT_RATIO_SQUEEZE and pct_float >= SHORT_INTEREST_TRAMOS[1][0]:
            texto += f". {dias_cubrir:.1f} días para cubrir: un squeeze es plausible si hay catalizador"
        elif dias_cubrir >= SHORT_RATIO_SQUEEZE:
            texto += f". {dias_cubrir:.1f} días para cubrir: los cortos tardarían en salir"
        else:
            texto += f". {dias_cubrir:.1f} días para cubrir: los cortos pueden cerrarse con rapidez"
    return texto, sem
