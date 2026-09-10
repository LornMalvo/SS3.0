"""Constantes globales de StockScanner.

Todo "número mágico" (pesos, umbrales, colores, TTL) vive aquí para que los
módulos de cálculo sean auditables sin tocar la lógica. Cada decisión no obvia
lleva su porqué al lado, como pide el protocolo del proyecto.
"""

APP_NOMBRE = "StockScanner"
APP_CLAIM = "Tu análisis del mercado"

# Se guarda junto a cada análisis persistido. Si cambia un peso o un umbral
# de cualquier motor, se sube la versión: así el backtesting sabe qué
# parámetros produjeron cada señal pasada y puede reconstruirla.
MOTOR_VERSION = "0.1.0"

# ---------------------------------------------------------------- paleta ----
C_PRIMARIO = "#004e64"
C_AZUL = "#0056a2"
C_VERDE = "#10b981"
C_VERDE_OSCURO = "#065f46"
C_TEAL = "#25a18e"
C_AMBAR = "#ffcb77"
C_NARANJA = "#f97316"
C_ROJO = "#dc2626"
C_ROJO_OSCURO = "#7f1d1d"
C_FONDO = "#f8fafc"
C_SUPERFICIE = "#ffffff"
C_TEXTO = "#0f172a"
C_TEXTO_TENUE = "#64748b"
C_BORDE = "#e2e8f0"
C_NAVBAR_FONDO = "#f1f5f9"

# ------------------------------------------------------------ navegación ----
SECCIONES = [
    "Análisis Individual",
    "Rastreador",
    "Gestión de Cartera",
    "Paper Trading",
    "Favoritos",
]
ICONOS_SECCION = {
    "Análisis Individual": "search",
    "Rastreador": "radar",
    "Gestión de Cartera": "work",
    "Paper Trading": "science",
    "Favoritos": "star",
}

TEXTO_ND = "Dato no disponible"

# --------------------------------------------------------------- gráfico ----
GRAFICO_ALTO = 560
GRAFICO_PROPORCION_FILAS = (0.75, 0.25)  # precio / MACD
# El histórico base se pide UNA vez en "max" diario y se recorta en pantalla
# para 1M/1A/MAX: cambiar de rango no gasta petición. Solo 1D y 1S necesitan
# velas intradía, que son una petición distinta (y ligera) que se cachea aparte.
RANGOS_GRAFICO = {
    "1D": ("1d", "5m"),
    "1S": ("7d", "30m"),
    "1M": None,   # recorte del histórico base
    "1A": None,
    "MAX": None,
}
RANGO_GRAFICO_DEFECTO = "1A"
DIAS_RANGO = {"1M": 31, "1A": 366}

# Colores del plan DCA sobre el gráfico: entradas en familia azul, salidas en
# familia verde, stop en rojo. El tono se aclara del nivel 1 al 3, de modo que
# el color codifica qué se hace y en qué orden llega.
PLAN_COLORES_ENTRADA = ("#1d4ed8", "#3b82f6", "#93c5fd")
PLAN_COLORES_SALIDA = ("#059669", "#10b981", "#6ee7b7")
PLAN_COLOR_STOP = C_ROJO

# ================================================================ CALIDAD ====
# Tres bloques. La "valoración relativa al sector" NO forma parte de Calidad:
# mide precio, que es lo que responde el Fair Value, y meterla aquí hacía que
# la valoración entrase dos veces en el Timing (vía upside y vía salud) y que
# el gate de salud >= 60 se pudiera superar solo por estar barata. Ver diseño
# de motores en el CHANGELOG de la sesión 1.
CALIDAD_BLOQUES = {
    "I. Crecimiento": {
        "cagr_ingresos_3a": 12,
        "cagr_bpa_3a": 10,
        "consistencia_ingresos": 5,   # % de ejercicios con ingresos crecientes
        "crecimiento_fcf": 3,
    },
    "II. Rentabilidad y foso": {
        "roic": 12,
        "margen_bruto": 7,
        "margen_operativo": 7,
        "margen_fcf": 6,
        "calidad_beneficio": 5,       # FCF / beneficio neto
        "roe": 3,
    },
    "III. Salud financiera": {
        "deuda_neta_ebitda": 8,
        "cobertura_intereses": 6,
        "dilucion": 6,                # variación de acciones en circulación 3a
        "current_ratio": 4,
        "fcf_positivo": 3,
        "deuda_patrimonio": 3,
    },
}
CALIDAD_PESOS = {m: p for b in CALIDAD_BLOQUES.values() for m, p in b.items()}
assert sum(CALIDAD_PESOS.values()) == 100

# Por debajo de esta cobertura el motor no devuelve nota: con menos de la
# mitad de las métricas, la redistribución de peso ya no "rellena huecos",
# inventa una empresa. Se muestra "Dato no disponible" con la cobertura real.
CALIDAD_COBERTURA_MINIMA = 0.50

# Perfil de empresa: gobierna qué métodos de Fair Value se activan. Es
# pre_rentabilidad si el BPA TTM y el forward son ambos <= 0.
PERFIL_RENTABLE = "rentable"
PERFIL_PRE_RENTABILIDAD = "pre_rentabilidad"

# ============================================================= FAIR VALUE ====
# Métodos de una sola multiplicación. Los forward pesan más que los trailing
# porque el precio descuenta el futuro, y el consenso tiene peso FIJO: si su
# peso creciera con el nº de analistas acabaría siendo a la vez el método
# dominante y el ancla de la banda de cordura (se vigilaría a sí mismo).
FV_PESOS = {
    "per_historico": 0.15,   # A. mediana PER propio 5a x BPA TTM
    "per_forward": 0.25,     # B. PER forward de industria x BPA forward
    "peg": 0.20,             # C. PEG objetivo x crecimiento x BPA forward
    "ev_ebitda": 0.20,       # D. EV/EBITDA de industria
    "consenso": 0.20,        # precio objetivo medio de analistas
}
# Empresas sin beneficio: A, B y C no tienen BPA que multiplicar. Se apoya en
# ventas y EBITDA (si es positivo) y en el consenso, con más peso porque en
# estos negocios los analistas incorporan información (pipeline, contratos)
# que ningún múltiplo captura.
FV_PESOS_PRE_RENTABILIDAD = {
    "ev_ventas": 0.45,
    "ev_ebitda": 0.20,
    "consenso": 0.35,
}
FV_PER_HISTORICO_ANIOS = 5
# Si el PER más alto de la serie supera al más bajo en más de este factor, la
# empresa no tiene un "PER propio" fiable (rampa de crecimiento o cargo
# puntual) y el método se excluye.
FV_PER_HISTORICO_INESTABILIDAD_MAX = 2.0
# Regla de Lynch: PEG 1 = precio razonable para su crecimiento. No se usa un
# PEG sectorial como objetivo porque al multiplicarse por el crecimiento
# dispara el PER justo a niveles absurdos.
FV_PEG_OBJETIVO = 1.0
FV_PEG_CRECIMIENTO_MIN = 0.08   # por debajo, el PEG es un error de categoría: se excluye
FV_PEG_CRECIMIENTO_MAX = 0.30   # techo: no extrapolar crecimientos explosivos
FV_CONSENSO_MIN_ANALISTAS = 4

# Banda de cordura sobre un ancla MIXTA (mediana de métodos propios + consenso).
# Asimétrica: el sell-side publica objetivos por encima del precio de forma
# sistemática, así que se tolera más desviación por abajo que por arriba.
# Dentro de la banda: se usa tal cual. Hasta el límite de exclusión: se recorta
# al borde (discrepa, pero su dirección es información). Más allá: se excluye
# (ha fallado; recortarlo solo arrastraría la media con un número inventado).
FV_BANDA_SUELO = 0.60
FV_BANDA_TECHO = 1.60
FV_EXCLUSION_SUELO = 0.35
FV_EXCLUSION_TECHO = 2.50

# Sensibilidad: cada escenario mueve a la vez el múltiplo de referencia y el
# crecimiento estimado, y cambia el consenso medio por el bajo/alto.
FV_ESCENARIOS = {
    "conservador": {"multiplo": 0.85, "crecimiento": 0.80, "consenso": "bajo"},
    "base": {"multiplo": 1.00, "crecimiento": 1.00, "consenso": "medio"},
    "optimista": {"multiplo": 1.15, "crecimiento": 1.20, "consenso": "alto"},
}

# Bandas de valoración: (upside_min, upside_max, etiqueta, color), % sobre el
# precio. Zona neutra +-5%: la dispersión típica entre métodos es del 20-30%,
# así que dentro de +-5% nada es distinguible de "precio justo".
BANDAS_VALORACION = [
    (35.0, None, "MUY INFRAVALORADA — Oportunidad excepcional", C_VERDE_OSCURO),
    (15.0, 35.0, "INFRAVALORADA — Potencial alcista significativo", C_VERDE),
    (5.0, 15.0, "LIGERAMENTE INFRAVALORADA — Entrada atractiva", C_TEAL),
    (-5.0, 5.0, "PRECIO JUSTO — En rango de valor razonable", C_AMBAR),
    (-20.0, -5.0, "EN OBSERVACIÓN — Por encima del valor objetivo", C_NARANJA),
    (-35.0, -20.0, "SOBREVALORADA — Riesgo de corrección moderada", C_ROJO),
    (None, -35.0, "MUY SOBREVALORADA — Riesgo de corrección severa", C_ROJO_OSCURO),
]

# ================================================================= TIMING ====
# Suman 100 para que el peso bruto coincida con el % en pantalla.
# `margen_seguridad` no existe: era `upside` con otro denominador, la misma
# lectura contada dos veces, y cualquier error del FV entraba por duplicado.
TIMING_PESOS = {
    # Momentum y flujo (27)
    "rsi": 9,
    "macd": 8,
    "obv": 5,
    "adx": 5,
    # Estructura de precio (23)
    "mm50": 5,
    "mm100": 4,
    "mm200": 6,
    "ath_atl": 4,
    "variacion_1a": 4,
    # Valoración (20)
    "upside": 14,
    "peg": 6,
    # Calidad (12)
    "salud_fundamental": 12,
    # Contexto (18)
    "proximidad_earnings": 5,
    "confluencia_dca": 8,
    "volumen_relativo": 5,
}
assert sum(TIMING_PESOS.values()) == 100

# Gate de calidad: sin salud >= 60 el timing no pasa de VIGILAR. Buen timing en
# mala empresa es trading, no lo que busca esta app.
CALIDAD_MINIMA_TIMING = 60
TIMING_TOPE_SIN_SALUD = 59

# Cinco niveles con verbo de acción. La frontera ENTRAR/ACUMULAR (comprar hoy
# vs dejar orden en el nivel 1) es la más accionable y un esquema de 4 la fundía.
SENIALES_TIMING = [
    (80, "ENTRAR", C_VERDE_OSCURO),
    (65, "ACUMULAR", C_VERDE),
    (45, "VIGILAR", C_AMBAR),
    (25, "ESPERAR", C_NARANJA),
    (0, "EVITAR", C_ROJO),
]

# Veredicto final: matriz con vetos, no media (una media esconde el veto de
# calidad). Etiquetas de dos palabras, nunca un párrafo.
VEREDICTOS = {
    "comprar": ("COMPRAR", C_VERDE_OSCURO),
    "acumular": ("ACUMULAR POR TRAMOS", C_VERDE),
    "vigilar": ("VIGILAR", C_AMBAR),
    "no_comprar": ("NO COMPRAR", C_ROJO),
    "reducir": ("REDUCIR", C_ROJO_OSCURO),
}
VEREDICTO_UPSIDE_MIN = 5.0     # % mínimo para considerar compra
VEREDICTO_UPSIDE_REDUCIR = -20.0

INDICADOR_VENTANAS = {"mm50": 50, "mm100": 100, "mm200": 200, "atr": 14, "rsi": 14, "adx": 14}
MACD_PARAMS = (12, 26, 9)
TIMING_VOLUMEN_SESIONES = 5      # ventana corta vs media de 3 meses
TIMING_EARNINGS_DIAS_CERCA = 10  # a menos de esto se penaliza entrar (riesgo binario)

# ============================================================ CONFLUENCIA ====
# Pesos de cada candidato a soporte/resistencia. El orden expresa fiabilidad:
# volumen negociado y estructura semanal por encima de medias móviles cortas.
CONFLUENCIA_PESOS = {
    "mm50": 1.0,
    "mm100": 1.2,
    "mm200": 2.0,
    "pivote_diario": 1.0,
    "pivote_semanal": 1.8,
    "poc": 2.4,
    "value_area": 1.3,
    "diagonal": 1.6,
    "gap": 1.2,
    "min_52s": 2.0,
    "max_52s": 2.0,
    "fibonacci": 0.8,
    "redondo": 0.5,      # desempate, nunca argumento
}
# Cada candidato es una gaussiana de anchura SIGMA (en ATR) y altura = peso;
# las zonas son los máximos locales de la suma. Sin umbral binario de cluster.
CONFLUENCIA_SIGMA_ATR = 0.50
CONFLUENCIA_SIGMA_PCT_RESPALDO = 0.018
CONFLUENCIA_SIGMA_MIN_PCT = 0.004
CONFLUENCIA_SIGMA_MAX_PCT = 0.030
CONFLUENCIA_REJILLA = 800
CONFLUENCIA_PESO_MIN_ZONA = 0.8
CONFLUENCIA_FUERTE = 5.0         # a partir de aquí una zona cuenta como "confluencia fuerte"

PIVOTE_VENTANA_DIARIA = 5        # sesiones a cada lado
PIVOTE_VENTANA_SEMANAL = 4       # semanas a cada lado
PIVOTE_TOQUES_MULT = 0.35        # peso *= 1 + MULT * ln(toques)
PIVOTE_DECADENCIA_ANIOS = 3.0
PIVOTE_DECADENCIA_MIN = 0.60
VP_SESIONES = 504
VP_BANDAS = 60
VP_VALUE_AREA_PCT = 0.70
DIAGONAL_MIN_TOQUES = 3
DIAGONAL_TOLERANCIA_ATR = 0.75
DIAGONAL_SESIONES = 378
GAP_MIN_PCT = 0.02               # huecos menores son ruido de apertura
NIVEL_REDONDO_MAX = 3

# ================================================================ PLAN DCA ====
DCA_PESOS_ENTRADA = (0.40, 0.35, 0.25)
DCA_PESOS_SALIDA = (0.35, 0.35, 0.30)
# El nivel 1 NO tiene separación mínima respecto al precio actual: si hay
# confluencia fuerte pegada al precio, ahí va. La separación solo rige entre
# N1-N2 y N2-N3, adaptativa al ATR y acotada.
DCA_SEPARACION_ATR_ENTRADAS = 2.0
DCA_SEPARACION_ATR_SALIDAS = 1.5
DCA_SEPARACION_MIN_PCT = 0.03
DCA_SEPARACION_MAX_PCT = 0.20
# Rango de trabajo: una zona fortísima a -60% es inútil como entrada de un
# DCA (no se ejecutará nunca) y se descarta ANTES de agrupar.
DCA_RANGO_ATR = 10.0
DCA_RANGO_ENTRADAS_MIN_PCT = 0.20
DCA_RANGO_ENTRADAS_MAX_PCT = 0.40
DCA_RANGO_SALIDAS_MIN_PCT = 0.30
DCA_RANGO_SALIDAS_MAX_PCT = 0.60
# Salidas: la 3ª se ancla al fair value salvo resistencia fuerte cerca; con
# tendencia fuerte confirmada se permite extender por encima hasta este factor.
DCA_SALIDA_ADX_TENDENCIA = 25
DCA_SALIDA_EXTENSION_MAX = 1.15
# Stop sobre el coste medio estimado del plan (no sobre el nivel 1): así la
# restricción es "no arriesgo más de un X% de lo invertido" y no puede chocar
# con la escalera de entradas.
DCA_STOP_ATR_MULT = 2.5
DCA_STOP_CAIDA_MAX = 0.25
DCA_STOP_MARGEN_ATR_BAJO_N3 = 1.5
DCA_STOP_CAIDA_RESPALDO = 0.15   # sin ATR utilizable

# ================================================================ CARTERA ====
CARTERA_DIVISA_BASE = "EUR"
CARTERA_DIVISAS_CONVERTIBLES = ("EUR", "USD")
# El saldo se obtiene sumando y restando flotantes: tras vender todo puede
# quedar un residuo de 1e-14 acciones que dejaría la posición "abierta".
CARTERA_TOLERANCIA_ACCIONES = 1e-6
BENCHMARK = "SPY"   # convertido a EUR para compararlo con la cartera

# ---------------------------------------------------------- paper trading ----
PAPER_ESTADOS = {
    "vigilancia":      ("Vigilando", C_AMBAR),
    "parcial_entrada": ("Abierto, en marcha", C_TEAL),
    "abierta":         ("Abierto, completado", C_VERDE),
    "parcial_salida":  ("Cerrado parcialmente", C_AZUL),
    "cerrada":         ("Cerrado, completado", C_PRIMARIO),
    "descartada":      ("Descartado", C_TEXTO_TENUE),
}
PAPER_ESTADOS_ACTIVOS = ("vigilancia", "parcial_entrada", "abierta", "parcial_salida")
PAPER_ESTADOS_CERRADOS = ("cerrada",)
PAPER_ESTADOS_DESCARTADOS = ("descartada",)

# ================================================================== CACHÉ ====
# TTL en segundos. El histórico diario NO usa TTL como mecanismo real: usa el
# "cubo de mercado" de datos_cache.py, que congela la caché mientras el
# mercado está cerrado y la revalida una vez por hora en sesión. El TTL de
# respaldo es solo cinturón de seguridad.
TTL_PRECIO = 300
TTL_INTRADIA = 300
TTL_HISTORICO_RESPALDO = 21600
TTL_INFO = 3600
TTL_ESTADOS_FINANCIEROS = 172800   # solo cambian 4 veces al año
TTL_NOTICIAS = 900
TTL_FX = 600
TTL_LOTE = 900

# Antigüedad esperada por tipo de dato para el indicador de frescura de cada
# bloque: por encima, aviso visual.
FRESCURA_ESPERADA = {
    "precio": 900,
    "historico": 86400,
    "info": 86400,
    "fundamentales": 172800 * 45,   # ~un trimestre
    "noticias": 3600,
}

MERCADO_ZONA_HORARIA = "America/New_York"
MERCADO_HORA_APERTURA = (9, 30)
MERCADO_HORA_CIERRE = (16, 0)
# Festivos NYSE fijos y móviles se añaden en datos_cache.py; un festivo no
# contemplado se trata como sesión normal (cuesta, como mucho, una petición).
