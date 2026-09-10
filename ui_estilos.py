"""Hoja de estilos de la app (referencia visual del proyecto, con añadidos mínimos). Fondo claro, tarjetas de borde redondeado y la
paleta corporativa expuesta como variables CSS."""

import streamlit as st

from config_settings import (
    C_NAVBAR_FONDO,
    C_AMBAR,
    C_AZUL,
    C_BORDE,
    C_FONDO,
    C_PRIMARIO,
    C_SUPERFICIE,
    C_TEAL,
    C_TEXTO,
    C_TEXTO_TENUE,
    C_VERDE,
)

CSS = f"""
<style>
:root {{
  --ss-primario: {C_PRIMARIO};
  --ss-azul: {C_AZUL};
  --ss-verde: {C_VERDE};
  --ss-teal: {C_TEAL};
  --ss-ambar: {C_AMBAR};
  --ss-fondo: {C_FONDO};
  --ss-superficie: {C_SUPERFICIE};
  --ss-texto: {C_TEXTO};
  --ss-tenue: {C_TEXTO_TENUE};
  --ss-borde: {C_BORDE};
}}

.stApp {{ background: var(--ss-fondo); }}
html, body, [class*="css"] {{
  font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
  color: var(--ss-texto);
}}
.block-container {{ padding-top: 3.5rem; max-width: 1500px; }}

/* --- cabecera --- */
.ss-logo {{
  display: block;
  margin: .25rem auto 1.4rem auto;
  width: 340px;
  max-width: 68%;
  height: auto;
}}

/* --- navbar: píldoras segmentadas --- */
.st-key-navbar_pildoras > div[data-testid="stHorizontalBlock"] {{
  background: {C_NAVBAR_FONDO};
  border-radius: 999px;
  padding: 5px;
  gap: 6px !important;
}}
.st-key-navbar_pildoras button {{
  width: 100% !important;
  border: none !important;
  border-radius: 999px !important;
  box-shadow: none !important;
  font-size: .8rem !important;
  font-weight: 500 !important;
  padding: .6rem .4rem !important;
}}
.st-key-navbar_pildoras button[kind="secondary"] {{
  background: transparent !important;
  color: var(--ss-tenue) !important;
}}
.st-key-navbar_pildoras button[kind="secondary"]:hover {{
  background: #e2e8f0 !important;
  color: var(--ss-primario) !important;
}}
.st-key-navbar_pildoras button[kind="primary"] {{
  background: var(--ss-azul) !important;
  color: #ffffff !important;
}}
.st-key-navbar_pildoras button[kind="primary"]:hover {{
  background: var(--ss-primario) !important;
}}
.st-key-navbar_pildoras button svg {{
  fill: currentColor !important;
}}

/* --- tarjetas de bloque --- */
.ss-card {{
  background: var(--ss-superficie);
  border: 1.5px solid var(--ss-borde);
  border-radius: 18px;
  padding: 1.1rem 1.25rem;
  height: 100%;
}}
.ss-card h4 {{
  margin: 0 0 .8rem 0; font-size: .95rem; font-weight: 700;
  color: var(--ss-primario); letter-spacing: .01em;
}}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 18px; }}

/* --- etiquetas de cabecera de análisis --- */
.ss-etiqueta {{
  font-size: .72rem; text-transform: uppercase; letter-spacing: .12em;
  color: var(--ss-tenue); font-weight: 700; margin-bottom: .15rem;
}}
.ss-ticker {{ font-size: 1.9rem; font-weight: 800; color: var(--ss-primario); line-height: 1.1; }}
.ss-empresa {{ font-size: 1rem; color: var(--ss-texto); }}
.ss-sector {{ font-size: .88rem; color: var(--ss-tenue); }}
.ss-precio {{ font-size: 1.7rem; font-weight: 800; color: var(--ss-azul); line-height: 1.1; }}
.ss-precio-eur {{ font-size: .95rem; color: var(--ss-tenue); }}

/* --- variación diaria junto al precio (Bloque 1) --- */
.ss-var {{ font-size: 1rem; font-weight: 700; margin-left: .4rem; }}
.ss-var-pos {{ color: var(--ss-verde); }}
.ss-var-neg {{ color: #dc2626; }}

/* --- título de tarjeta cuando la tarjeta es un st.container(border=True):
   misma tipografía que .ss-card h4 pero fuera de un div propio, para poder
   meter widgets de Streamlit dentro de la tarjeta --- */
.ss-card-titulo {{
  margin: 0 0 .6rem 0; font-size: .95rem; font-weight: 700;
  color: var(--ss-primario); letter-spacing: .01em;
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{ border-radius: 18px; }}

/* --- indicador de frescura de dato --- */
.ss-frescura {{ font-size: .68rem; color: var(--ss-tenue); }}
.ss-frescura-aviso {{ color: #f97316; font-weight: 600; }}

/* --- placeholder de bloque pendiente --- */
.ss-pendiente {{
  color: var(--ss-tenue); font-size: .84rem; padding: .6rem .2rem; line-height: 1.5;
}}

/* --- alertas y badges --- */
.ss-alerta {{
  border-radius: 12px; padding: .65rem .85rem; color: #fff;
  font-weight: 700; font-size: .88rem; text-align: center;
}}
.ss-badge {{
  display: inline-block; border-radius: 999px; padding: .18rem .6rem;
  font-size: .72rem; font-weight: 700; color: #fff;
}}
.ss-nd {{ color: var(--ss-tenue); font-style: italic; }}

/* --- métricas en rejilla --- */
.ss-metrica {{
  display: flex; justify-content: space-between; gap: .5rem;
  padding: .3rem 0; border-bottom: 1px dashed var(--ss-borde); font-size: .86rem;
}}
.ss-metrica span:first-child {{ color: var(--ss-tenue); }}
.ss-metrica span:last-child {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
/* Frase de interpretación bajo una métrica (RSI, ADX, short interest). */
.ss-lectura {{
  font-size: .76rem; line-height: 1.35; margin: .25rem 0 .45rem;
  padding: .3rem .55rem; border-left: 3px solid var(--ss-tenue);
  background: #f1f5f9; border-radius: 0 6px 6px 0;
}}
.ss-media-sector {{
  color: var(--ss-tenue); font-weight: 400; font-size: .74rem; margin-left: .5rem;
}}

/* --- ficha compacta de posición (rejilla de Cartera y Paper Trading) --- */
.ss-mini-cab {{
  display: flex; justify-content: space-between; align-items: baseline; gap: .5rem;
}}
.ss-mini-tk {{ font-size: 1.05rem; font-weight: 700; }}
.ss-mini-aparte {{ color: var(--ss-tenue); font-size: .76rem; text-align: right; }}
.ss-mini-dest {{
  font-size: 1.25rem; font-weight: 700; font-variant-numeric: tabular-nums;
  margin: .3rem 0 .05rem;
}}
.ss-mini-sub {{ color: var(--ss-tenue); font-size: .76rem; margin-bottom: .35rem; }}
/* Filas de apoyo más apretadas y sin la línea de separación: dentro de una
   tarjeta pequeña, el punteado de .ss-metrica satura. */
.ss-mini .ss-metrica {{ padding: .12rem 0; border-bottom: 0; font-size: .8rem; }}
.ss-mini-pie {{
  font-size: .76rem; font-weight: 600; margin-top: .3rem;
  padding-top: .3rem; border-top: 1px dashed var(--ss-borde);
}}

/* --- racha de sorpresas de resultados (Bloque 2) --- */
.ss-racha-tit {{ font-size: .82rem; font-weight: 700; margin: .1rem 0 .3rem; }}
.ss-racha {{ font-size: .76rem; font-variant-numeric: tabular-nums; }}
.ss-racha-fila {{
  display: grid; grid-template-columns: 1.5fr 1fr 1fr 1.2fr;
  gap: .3rem; padding: .16rem 0; border-bottom: 1px solid var(--ss-borde);
}}
.ss-racha-fila > span:not(:first-child) {{ text-align: right; }}
.ss-racha-cab {{ color: var(--ss-tenue); font-weight: 600; border-bottom-width: 2px; }}
.ss-racha-fila:last-child {{ border-bottom: 0; }}

/* Título de los minigráficos de barras cuando no hay dato que dibujar. */
.ss-mini-tit {{ font-size: .75rem; font-weight: 600; margin: .35rem 0 .1rem; }}

/* Lectura en una línea de la comparativa de PER (cara / barata). */
.ss-per-mensaje {{
  font-size: .8rem; font-weight: 600; margin-top: -.4rem;
  padding: .35rem .5rem; border-left: 3px solid var(--ss-primario);
  background: rgba(255,255,255,.03); border-radius: 0 4px 4px 0;
}}

/* --- anotaciones al pie (p. ej. tipo de cambio aplicado) --- */
.ss-anotacion {{
  color: var(--ss-tenue); font-size: .68rem; font-style: italic; margin-top: .2rem;
}}

/* --- noticias --- */
.ss-noticia {{ padding: .35rem 0; border-bottom: 1px solid var(--ss-borde); font-size: .85rem; }}
.ss-noticia a {{ color: var(--ss-azul); text-decoration: none; font-weight: 600; }}
.ss-noticia a:hover {{ text-decoration: underline; }}
.ss-noticia small {{ color: var(--ss-tenue); }}

/* --- barra de puntuación --- */
.ss-barra {{ background: var(--ss-borde); border-radius: 999px; height: 10px; overflow: hidden; }}
.ss-barra > div {{ height: 100%; border-radius: 999px; }}
.ss-nota {{ font-size: 2.1rem; font-weight: 800; line-height: 1; }}

/* --- niveles del plan DCA --- */
.ss-nivel {{
  display: flex; justify-content: space-between; align-items: baseline;
  padding: .32rem .55rem; border-radius: 9px; margin-bottom: .28rem;
  background: #f1f5f9; font-size: .84rem;
}}
.ss-nivel b {{ font-variant-numeric: tabular-nums; }}
.ss-motivos {{ font-size: .72rem; color: var(--ss-tenue); margin: -.15rem 0 .45rem .55rem; }}

/* --- botones --- */
.stButton > button {{ border-radius: 10px; font-weight: 600; }}
.stButton > button[kind="primary"] {{ background: var(--ss-azul); border-color: var(--ss-azul); }}

/* --- botón de favorito (estrella) --- */
.st-key-btn_favorito_on button, .st-key-btn_favorito_off button {{
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  font-size: 2.15rem !important;
  line-height: 1 !important;
  padding: 0 .25rem !important;
  transition: transform .12s ease;
}}
.st-key-btn_favorito_on button p, .st-key-btn_favorito_off button p,
.st-key-btn_favorito_on button div, .st-key-btn_favorito_off button div {{
  font-size: inherit !important;
  color: inherit !important;
}}
.st-key-btn_favorito_on button {{ color: #f5b400 !important; }}
.st-key-btn_favorito_off button {{ color: #94a3b8 !important; }}
.st-key-btn_favorito_on button:hover, .st-key-btn_favorito_off button:hover {{
  color: #f5b400 !important;
  transform: scale(1.1);
}}
</style>
"""


def aplicar() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
