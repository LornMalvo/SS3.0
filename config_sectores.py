"""Tablas de referencia por sector (clasificación de yfinance).

SEMILLA orientativa: valores de orden de magnitud para arrancar los motores
sin bloquear el desarrollo. Desde la sesión 6 son el ÚLTIMO escalón de
core_referencias: cada motor prefiere la mediana de los comparables
validados del ticker y, si no, la mediana real del sector que calcula el
rastreo nocturno (`sector_referencias`); solo sin ninguna de las dos se
usa esta tabla, y la interfaz lo etiqueta como "sector (semilla)".

Las claves de cada tabla coinciden con las de core_fundamentales.extraer /
la tabla `multiplos` (ver REFERENCIAS_SEMILLA al final).
"""

SECTORES = [
    "Basic Materials", "Communication Services", "Consumer Cyclical",
    "Consumer Defensive", "Energy", "Financial Services", "Healthcare",
    "Industrials", "Real Estate", "Technology", "Utilities",
]

# PER forward mediano.
PER_FORWARD_SECTOR = {
    "Basic Materials": 18.0, "Communication Services": 20.0,
    "Consumer Cyclical": 22.0, "Consumer Defensive": 19.0, "Energy": 13.0,
    "Financial Services": 14.0, "Healthcare": 20.0, "Industrials": 21.0,
    "Real Estate": 30.0, "Technology": 28.0, "Utilities": 17.0,
}

# EV/EBITDA mediano (solo empresas con EBITDA positivo).
EV_EBITDA_SECTOR = {
    "Basic Materials": 10.0, "Communication Services": 11.0,
    "Consumer Cyclical": 12.0, "Consumer Defensive": 13.0, "Energy": 7.0,
    "Financial Services": 12.0, "Healthcare": 15.0, "Industrials": 14.0,
    "Real Estate": 18.0, "Technology": 20.0, "Utilities": 12.0,
}

# Precio / Valor contable mediano: múltiplo natural de las financieras
# (método P/B del Fair Value, sesión 6).
PB_SECTOR = {
    "Basic Materials": 2.0, "Communication Services": 2.5,
    "Consumer Cyclical": 3.5, "Consumer Defensive": 3.5, "Energy": 1.8,
    "Financial Services": 1.3, "Healthcare": 4.0, "Industrials": 3.5,
    "Real Estate": 1.8, "Technology": 6.0, "Utilities": 1.8,
}

# EV/Ventas mediano: único múltiplo utilizable en pre-rentabilidad.
EV_VENTAS_SECTOR = {
    "Basic Materials": 1.8, "Communication Services": 2.5,
    "Consumer Cyclical": 1.5, "Consumer Defensive": 1.6, "Energy": 1.3,
    "Financial Services": 3.0, "Healthcare": 3.5, "Industrials": 2.0,
    "Real Estate": 7.0, "Technology": 6.0, "Utilities": 3.0,
}

MARGEN_BRUTO_SECTOR = {
    "Basic Materials": 0.30, "Communication Services": 0.50,
    "Consumer Cyclical": 0.38, "Consumer Defensive": 0.35, "Energy": 0.30,
    "Financial Services": 0.70, "Healthcare": 0.55, "Industrials": 0.32,
    "Real Estate": 0.55, "Technology": 0.55, "Utilities": 0.45,
}
MARGEN_OPERATIVO_SECTOR = {
    "Basic Materials": 0.10, "Communication Services": 0.16,
    "Consumer Cyclical": 0.09, "Consumer Defensive": 0.08, "Energy": 0.11,
    "Financial Services": 0.25, "Healthcare": 0.13, "Industrials": 0.11,
    "Real Estate": 0.35, "Technology": 0.22, "Utilities": 0.20,
}
PEG_SECTOR = {
    "Basic Materials": 1.5, "Communication Services": 1.8,
    "Consumer Cyclical": 1.7, "Consumer Defensive": 2.2, "Energy": 1.3,
    "Financial Services": 1.4, "Healthcare": 1.9, "Industrials": 1.8,
    "Real Estate": 2.3, "Technology": 2.0, "Utilities": 2.5,
}
MARGEN_NETO_SECTOR = {
    "Basic Materials": 0.08, "Communication Services": 0.10,
    "Consumer Cyclical": 0.06, "Consumer Defensive": 0.06, "Energy": 0.08,
    "Financial Services": 0.22, "Healthcare": 0.07, "Industrials": 0.08,
    "Real Estate": 0.13, "Technology": 0.18, "Utilities": 0.11,
}
ROE_SECTOR = {
    "Basic Materials": 0.12, "Communication Services": 0.13,
    "Consumer Cyclical": 0.18, "Consumer Defensive": 0.15, "Energy": 0.11,
    "Financial Services": 0.12, "Healthcare": 0.10, "Industrials": 0.16,
    "Real Estate": 0.05, "Technology": 0.22, "Utilities": 0.09,
}
ROIC_SECTOR = {
    "Basic Materials": 0.07, "Communication Services": 0.10,
    "Consumer Cyclical": 0.10, "Consumer Defensive": 0.11, "Energy": 0.07,
    "Financial Services": 0.08, "Healthcare": 0.09, "Industrials": 0.10,
    "Real Estate": 0.05, "Technology": 0.16, "Utilities": 0.05,
}
DEUDA_NETA_EBITDA_SECTOR = {
    "Basic Materials": 1.5, "Communication Services": 2.5,
    "Consumer Cyclical": 1.5, "Consumer Defensive": 2.0, "Energy": 1.2,
    "Financial Services": None,   # no es magnitud válida para bancos
    "Healthcare": 1.5, "Industrials": 2.0, "Real Estate": 6.0,
    "Technology": 0.5, "Utilities": 4.5,
}

# Sectores estructuralmente apalancados: la deuda no penaliza igual.
SECTORES_APALANCADOS = {"Financial Services", "Real Estate", "Utilities"}

# REITs: el BPA GAAP no es una magnitud económica válida (la amortización del
# inmueble se come el beneficio contable). Los métodos basados en BPA se
# excluyen; el fair value se apoya en EV/EBITDA y consenso hasta implementar
# P/FFO.
INDUSTRIAS_REIT = {
    "REIT - Diversified", "REIT - Healthcare Facilities", "REIT - Hotel & Motel",
    "REIT - Industrial", "REIT - Mortgage", "REIT - Office", "REIT - Residential",
    "REIT - Retail", "REIT - Specialty",
}

# ETF sectorial para la fuerza relativa (SPDR Select Sector) y benchmark.
ETF_SECTORIAL = {
    "Technology": "XLK", "Communication Services": "XLC",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Healthcare": "XLV",
    "Financial Services": "XLF", "Industrials": "XLI", "Energy": "XLE",
    "Basic Materials": "XLB", "Utilities": "XLU", "Real Estate": "XLRE",
}

# Tabla semilla por clave de múltiplo/margen (mismas claves que la tabla
# `multiplos` y que core_fundamentales.extraer). core_referencias la usa
# como último escalón.
REFERENCIAS_SEMILLA = {
    "per_forward": PER_FORWARD_SECTOR,
    "ev_ebitda": EV_EBITDA_SECTOR,
    "ev_ventas": EV_VENTAS_SECTOR,
    "precio_valor_contable": PB_SECTOR,
    "peg": PEG_SECTOR,
    "margen_bruto": MARGEN_BRUTO_SECTOR,
    "margen_operativo": MARGEN_OPERATIVO_SECTOR,
    "margen_neto": MARGEN_NETO_SECTOR,
    "roe": ROE_SECTOR,
    "roic": ROIC_SECTOR,
    "deuda_neta_ebitda": DEUDA_NETA_EBITDA_SECTOR,
}
