from __future__ import annotations

import streamlit as st


CSS_THEME = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');

:root {
  --bg-base: #e9eff5;
  --bg-panel: #f8fafc;
  --ink-strong: #0f172a;
  --ink-muted: #334155;
  --line: #cbd5e1;
  --line-strong: #94a3b8;
  --accent: #0f766e;
  --accent-strong: #0b4f49;
  --accent-soft: #d7f3ef;
  --info: #0a4d8c;
  --warn: #9a3412;
}

html, body, [class*="css"] {
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  color: var(--ink-strong);
}

.main .block-container {
  padding-top: 1rem;
  padding-bottom: 2rem;
  max-width: 1240px;
}

[data-testid="stAppViewContainer"] {
  background-color: var(--bg-base);
  background-image:
    linear-gradient(rgba(100, 116, 139, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(100, 116, 139, 0.08) 1px, transparent 1px);
  background-size: 26px 26px;
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0b1f34 0%, #12385a 100%);
  border-right: 1px solid rgba(148, 163, 184, 0.35);
}

[data-testid="stSidebar"] * {
  color: #f1f5f9 !important;
}

h1, h2, h3 {
  color: var(--ink-strong);
  letter-spacing: 0.01em;
}

small, .stCaption, [data-testid="stCaptionContainer"] {
  color: var(--ink-muted);
}

[data-testid="stHorizontalBlock"] > div,
[data-testid="column"] > div {
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  padding: 0.75rem;
}

div[data-baseweb="tab"] {
  border-radius: 0.5rem;
  background: #edf2f7;
  border: 1px solid var(--line);
  color: #1e293b;
  font-weight: 600;
  padding: 0.45rem 0.95rem;
}

div[data-baseweb="tab"][aria-selected="true"] {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent-strong);
}

[data-testid="stMetric"] {
  background: var(--bg-panel);
  border: 1px solid var(--line-strong);
  border-left: 4px solid var(--accent);
  border-radius: 0.75rem;
  padding: 0.55rem 0.8rem;
}

[data-testid="stMetricLabel"] {
  color: var(--ink-muted);
}

[data-testid="stMetricValue"] {
  color: var(--ink-strong);
  font-family: "JetBrains Mono", monospace;
}

div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
textarea {
  background: #ffffff;
  border-color: var(--line-strong) !important;
}

div[data-baseweb="input"] input,
textarea {
  color: var(--ink-strong);
}

div[data-baseweb="input"] > div:focus-within,
div[data-baseweb="select"] > div:focus-within {
  border-color: var(--info) !important;
  box-shadow: 0 0 0 1px var(--info);
}

.stButton > button {
  border-radius: 0.5rem;
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-weight: 600;
  transition: all 0.15s ease-in-out;
}

.stButton > button:hover {
  border-color: var(--accent-strong);
  background: #bde9e2;
  color: #082f2d;
}

[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
  border-radius: 0.6rem;
  overflow: hidden;
}

[data-testid="stAlertContainer"] {
  border-radius: 0.6rem;
  border: 1px solid var(--line);
}

hr {
  border-top: 1px solid var(--line-strong);
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
