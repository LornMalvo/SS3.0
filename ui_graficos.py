"""Gráficos Plotly. Solo dibujan: no piden datos.

Diseño del gráfico de cotización:
- Velas y línea son dos trazas con entrada en la leyenda; la línea arranca
  oculta (`legendonly`). Pulsar en la leyenda activa/desactiva cualquiera.
- MM50/MM100/MM200 se calculan sobre el histórico COMPLETO y luego se recorta
  al rango visible: si se calcularan sobre el recorte, los primeros 200 días
  de cualquier rango saldrían vacíos.
- Un solo tooltip para precio, volumen y MACD: `hovermode="x unified"` +
  `hoversubplots="axis"` funde en una caja las trazas de todos los subgráficos
  que comparten eje x (Plotly >= 5.21).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config_settings import (
    C_AZUL,
    C_PRIMARIO,
    C_ROJO,
    C_TEXTO_TENUE,
    C_VERDE,
    COLORES_MEDIAS,
    GRAFICO_ALTO,
    GRAFICO_PROPORCION_FILAS,
    INDICADOR_VENTANAS,
    PLAN_COLOR_STOP,
    PLAN_COLORES_ENTRADA,
    PLAN_COLORES_SALIDA,
)
from core_indicadores import macd, media_movil


def grafico_precio_macd(df_completo: pd.DataFrame, inicio: pd.Timestamp | None = None,
                        con_medias: bool = True, plan: dict | None = None,
                        mostrar_plan: bool = False, divisa: str = "") -> go.Figure:
    """`df_completo` es la serie entera; `inicio` recorta lo que se muestra
    una vez calculados los indicadores."""
    m = macd(df_completo)
    medias = {}
    if con_medias:
        for nombre, clave in (("MM50", "mm50"), ("MM100", "mm100"), ("MM200", "mm200")):
            medias[nombre] = media_movil(df_completo, INDICADOR_VENTANAS[clave])

    df = df_completo.loc[inicio:] if inicio is not None else df_completo
    m = m.loc[df.index]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=list(GRAFICO_PROPORCION_FILAS))

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Velas", increasing_line_color=C_VERDE, decreasing_line_color=C_ROJO,
        legendgroup="precio", legendrank=1,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"], mode="lines", name="Línea", visible="legendonly",
        line=dict(color=C_PRIMARIO, width=1.6), legendrank=2,
        hovertemplate="Cierre: %{y:,.2f}<extra></extra>",
    ), row=1, col=1)
    # Volumen: traza invisible que solo aporta su línea al tooltip unificado.
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"], mode="lines", line=dict(width=0), opacity=0,
        customdata=df["Volume"], name="Volumen", showlegend=False,
        hovertemplate="Volumen: %{customdata:,.0f}<extra></extra>",
    ), row=1, col=1)
    for i, (nombre, serie) in enumerate(medias.items(), start=3):
        fig.add_trace(go.Scatter(
            x=df.index, y=serie.loc[df.index], mode="lines", name=nombre, legendrank=i,
            line=dict(color=COLORES_MEDIAS[nombre], width=1.2),
            hovertemplate=nombre + ": %{y:,.2f}<extra></extra>",
        ), row=1, col=1)

    colores_hist = [C_VERDE if v >= 0 else C_ROJO for v in m["hist"].fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=m["hist"], marker_color=colores_hist, name="Histograma",
                         legendrank=10, hovertemplate="Hist: %{y:.3f}<extra></extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=m["macd"], line=dict(color=C_AZUL, width=1.4), name="MACD",
                             legendrank=11, hovertemplate="MACD: %{y:.3f}<extra></extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=m["senal"], line=dict(color=C_PRIMARIO, width=1.1, dash="dot"),
                             name="Señal", legendrank=12, hovertemplate="Señal: %{y:.3f}<extra></extra>"),
                  row=2, col=1)

    if mostrar_plan and plan:
        _capa_plan(fig, plan)

    fig.update_layout(
        height=GRAFICO_ALTO, margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified", hoversubplots="axis", xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom", font=dict(size=10),
                    itemclick="toggle", itemdoubleclick="toggleothers"),
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", color=C_TEXTO_TENUE, size=11),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor="#e2e8f0", font=dict(size=11, color="#0f172a")),
    )
    fig.update_yaxes(title_text=divisa, row=1, col=1, gridcolor="#e2e8f0", zeroline=False)
    fig.update_yaxes(title_text="MACD", row=2, col=1, gridcolor="#e2e8f0", zeroline=True, zerolinecolor="#cbd5e1")
    fig.update_xaxes(gridcolor="#e2e8f0", showspikes=True, spikemode="across", spikethickness=1,
                     spikecolor="#94a3b8", spikedash="dot")
    return fig


def _capa_plan(fig: go.Figure, plan: dict) -> None:
    """Líneas horizontales del plan DCA sobre la fila de precio."""
    def linea(precio, color, etiqueta):
        fig.add_hline(y=precio, line=dict(color=color, width=1.3), row=1, col=1,
                      annotation_text=etiqueta, annotation_position="top left",
                      annotation_font=dict(size=10, color=color))

    for i, nivel in enumerate(plan.get("entradas", [])[:3]):
        linea(nivel["precio"], PLAN_COLORES_ENTRADA[i], f"E{i + 1}")
    for i, nivel in enumerate(plan.get("salidas", [])[:3]):
        linea(nivel["precio"], PLAN_COLORES_SALIDA[i], f"S{i + 1}")
    if plan.get("stop"):
        linea(plan["stop"], PLAN_COLOR_STOP, "STOP")
