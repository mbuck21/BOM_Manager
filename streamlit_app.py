# Mass Allocation Tracking Tool — Streamlit entry point.
# This codebase was written with the use of AI (Anthropic Claude), guided and reviewed by
# the maintainer. POC for bugs, features, or setup help: Matt Buckley
# (matthew.p.buckley@lmco.com). See README.md for usage and ARCHITECTURE.md for design.

from __future__ import annotations

import os
import sys

import streamlit as st

from streamlit_ui.context import build_app_context
from streamlit_ui.helpers import data_dir_from_args, resolve_data_dir
from streamlit_ui.sidebar import render_root_sidebar
from streamlit_ui.state import (
    ACTIVE_SNAPSHOT_ID_KEY,
    DATA_DIR_INPUT_KEY,
    DATA_DIR_KEY,
    POC_LINE,
    SNAPSHOT_SELECTION_DATA_DIR_KEY,
    SNAPSHOT_SELECTION_INITIALIZED_KEY,
    UNIVERSAL_ROOT_PART_KEY,
)
from streamlit_ui.tabs import (
    render_data_tab,
    render_edit_tab,
    render_history_tab,
    render_weight_tab,
)

_PAGE_STYLE = """
    <style>
    .main .block-container {
        max-width: 1600px;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    [data-testid="stSidebar"] {
        min-width: 420px;
    }
    </style>
"""


def main() -> None:
    st.set_page_config(page_title="Mass Allocation Tracking Tool", layout="wide")
    st.markdown(_PAGE_STYLE, unsafe_allow_html=True)

    st.title("Mass Allocation Tracking Tool")
    st.caption(
        "Edit your BOM like a spreadsheet, watch the weight roll up, and report what "
        "changed. Hover any ⓘ for help."
    )

    if DATA_DIR_KEY not in st.session_state:
        # Startup data folder: `streamlit run streamlit_app.py -- --data-dir <path>`
        # wins, then the BOM_DATA_DIR environment variable, then the bundled demo.
        st.session_state[DATA_DIR_KEY] = (
            data_dir_from_args(sys.argv[1:])
            or os.environ.get("BOM_DATA_DIR", "").strip()
            or "demo_data"
        )
    if DATA_DIR_INPUT_KEY not in st.session_state:
        st.session_state[DATA_DIR_INPUT_KEY] = st.session_state[DATA_DIR_KEY]

    # Reset the version selection whenever the data folder changes.
    data_dir = resolve_data_dir(st.session_state[DATA_DIR_KEY])
    data_dir_marker = str(data_dir.resolve())
    if st.session_state.get(SNAPSHOT_SELECTION_DATA_DIR_KEY) != data_dir_marker:
        st.session_state[SNAPSHOT_SELECTION_DATA_DIR_KEY] = data_dir_marker
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = False
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = None

    selection_initialized = bool(st.session_state.get(SNAPSHOT_SELECTION_INITIALIZED_KEY, False))
    selected_snapshot_id = st.session_state.get(ACTIVE_SNAPSHOT_ID_KEY)
    # Always open on live (editable) data; saved versions are opt-in via the History tab.
    ctx = build_app_context(
        data_dir,
        selected_snapshot_id=selected_snapshot_id,
        default_to_latest=False,
    )

    if not selection_initialized:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = ctx.loaded_snapshot_id
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = True
    elif selected_snapshot_id != ctx.loaded_snapshot_id:
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = ctx.loaded_snapshot_id

    universal_root = render_root_sidebar(ctx)

    tab_edit, tab_weight, tab_history, tab_data = st.tabs(
        ["Edit", "Weight & Rollup", "History", "Data"]
    )

    with tab_edit:
        render_edit_tab(ctx, root_part_number=universal_root)

    with tab_weight:
        render_weight_tab(
            ctx, root_part_number=universal_root, root_state_key=UNIVERSAL_ROOT_PART_KEY
        )

    with tab_history:
        render_history_tab(ctx)

    with tab_data:
        render_data_tab(ctx)

    st.divider()
    st.caption(
        f"Questions, bugs, or feature ideas? Contact {POC_LINE}. "
        "Built with AI assistance (Anthropic Claude)."
    )


if __name__ == "__main__":
    main()
