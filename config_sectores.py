"""Tablas de referencia por sector (clasificación de yfinance).

SEMILLA orientativa: valores de orden de magnitud para arrancar los motores
sin bloquear el desarrollo. Cada motor las trata como "referencia local" y
las usa solo cuando no puede calcular la mediana con comparables reales.
PENDIENTE (sesión 5): `tarea_tablas_sector.py` que las regenere a partir de
comparables descargados por lote y las persista en Supabase con fecha.

Ningún valor de aquí se toma como verdad: al mostrarse en la interfaz se
etiqueta como "ref. sector (semilla)" y cuenta como fuente de baja frescura.
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
