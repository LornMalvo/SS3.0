"""Entrada de StockScanner. Toda la estructura vive en ui_interfaz."""

import streamlit as st

import ui_interfaz
from config_settings import APP_NOMBRE

st.set_page_config(page_title=APP_NOMBRE, page_icon="logo.png", layout="wide",
                   initial_sidebar_state="collapsed")
ui_interfaz.render()
