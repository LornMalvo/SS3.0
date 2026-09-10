"""Gráficos Plotly. Solo dibujan: no piden datos ni calculan nada que no sea
derivado directo de la serie que reciben."""

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
    GRAFICO_ALTO,
    GRAFICO_PROPORCION_FILAS,
    PLAN_COLOR_STOP,
    PLAN_COLORES_ENTRADA,
    PLAN_COLORES_SALIDA,
)
from core_indicadores import macd


def grafico_precio_macd(df: pd.DataFrame, plan: dict | None = None, mostrar_plan: bool = False,
                        divisa: str = "") -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=list(GRAFICO_PROPORCION_FILAS))

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Precio", increasing_line_color=C_VERDE, decreasing_line_color=C_ROJO,
        showlegend=False,
    ), row=1, col=1)

    # Tooltip único: el volumen viaja como traza invisible en el mismo eje x,
    # y `hovermode="x unified"` lo funde con el OHLC en una sola caja.
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"], mode="lines", line=dict(width=0), opacity=0,
        customdata=df["Volume"], name="Volumen", showlegend=False,
        hovertemplate="Volumen: %{customdata:,.0f}<extra></extra>",
    ), row=1, col=1)

    m = macd(df)
    colores_hist = [C_VERDE if v >= 0 else C_ROJO for v in m["hist"].fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=m["hist"], marker_color=colores_hist, name="Histograma",
                         showlegend=False, hovertemplate="Hist: %{y:.3f}<extra></extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=m["macd"], line=dict(color=C_AZUL, width=1.4), name="MACD",
                             hovertemplate="MACD: %{y:.3f}<extra></extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=m["senal"], line=dict(color=C_PRIMARIO, width=1.1, dash="dot"),
                             name="Señal", hovertemplate="Señal: %{y:.3f}<extra></extra>"), row=2, col=1)

    if mostrar_plan and plan:
        _capa_plan(fig, plan)

    fig.update_layout(
        height=GRAFICO_ALTO, margin=dict(l=10, r=10, t=10, b=10),
        hovermode="x unified", xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.08, font=dict(size=10)),
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", color=C_TEXTO_TENUE, size=11),
    )
    fig.update_yaxes(title_text=divisa, row=1, col=1, gridcolor="#e2e8f0", zeroline=False)
    fig.update_yaxes(title_text="MACD", row=2, col=1, gridcolor="#e2e8f0", zeroline=True, zerolinecolor="#cbd5e1")
    fig.update_xaxes(gridcolor="#e2e8f0", showspikes=True, spikemode="across", spikethickness=1)
    return fig


def _capa_plan(fig: go.Figure, plan: dict) -> None:
    """Líneas horizontales del plan DCA sobre la fila de precio. Se dibujan
    en la propia figura (no como shapes globales) para que respeten el rango
    seleccionado sin recalcular nada."""
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
