from __future__ import annotations

import streamlit as st


CSS_THEME = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&display=swap');

:root {
  --bg-soft: #f7f3e9;
  --ink: #1f2937;
  --teal: #0f766e;
  --teal-soft: #ccfbf1;
  --amber: #f59e0b;
}

html, body, [class*="css"]  {
  font-family: "Space Grotesk", "Avenir Next", sans-serif;
}

.main .block-container {
  padding-top: 1.25rem;
  max-width: 1240px;
}

[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 15% 20%, #111827 0%, var(--bg-soft) 60%);
}

[data-testid="stSidebar"] {
  background: linear-gradient(170deg, #111827 0%, #115e59 100%);
}

[data-testid="stSidebar"] * {
  color: #f8fafc !important;
}

div[data-baseweb="tab"] {
  border-radius: 999px;
  background: #e5e7eb;
  border: 1px solid #d1d5db;
  padding: 0.35rem 0.85rem;
}

div[data-baseweb="tab"][aria-selected="true"] {
  background: var(--teal);
  color: white;
}

.stButton > button {
  border-radius: 999px;
  border: 1px solid var(--teal);
  background: var(--teal-soft);
  color: #0f172a;
}

.stButton > button:hover {
  border-color: #0d9488;
  background: #99f6e4;
  color: #022c22;
}
</style>
"""


def configure_page() -> None:
    st.set_page_config(
        page_title="BOM Manager Demo",
        page_icon=":triangular_ruler:",
        layout="wide",
    )
    st.markdown(CSS_THEME, unsafe_allow_html=True)
