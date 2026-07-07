"""Data tab: choose the data folder and see where the project file lives."""

from __future__ import annotations

import shutil
from pathlib import Path

import streamlit as st

from bom_backend.store import PROJECT_FILENAME
from streamlit_ui.context import AppContext
from streamlit_ui.helpers import resolve_data_dir
from streamlit_ui.state import (
    ACTIVE_SNAPSHOT_ID_KEY,
    DATA_DIR_INPUT_KEY,
    DATA_DIR_KEY,
    SNAPSHOT_SELECTION_INITIALIZED_KEY,
)


def render_data_tab(ctx: AppContext) -> None:
    st.subheader("Data File")

    if DATA_DIR_INPUT_KEY not in st.session_state:
        st.session_state[DATA_DIR_INPUT_KEY] = st.session_state.get(DATA_DIR_KEY, "demo_data")

    entered_data_dir = st.text_input(
        "Data folder",
        key=DATA_DIR_INPUT_KEY,
        help=(
            "Folder holding this project's data file. Point at a new or empty folder to "
            "start a fresh project; back up by copying the file below."
        ),
    )
    if entered_data_dir != st.session_state.get(DATA_DIR_KEY, "demo_data"):
        st.session_state[DATA_DIR_KEY] = entered_data_dir
        st.session_state[ACTIVE_SNAPSHOT_ID_KEY] = None
        st.session_state[SNAPSHOT_SELECTION_INITIALIZED_KEY] = False
        st.rerun()

    data_dir = resolve_data_dir(st.session_state.get(DATA_DIR_KEY, "demo_data"))
    repo_root = Path.cwd().resolve()
    st.caption("Everything (current BOM + saved versions + your column setup) lives in one file:")
    st.code(f"{data_dir / PROJECT_FILENAME}")

    if st.button(
        "Reset Data Folder",
        key="reset_data_dir_btn",
        help="Deletes the whole data folder, including all saved versions. There is no undo.",
    ):
        if data_dir == repo_root:
            st.error("Refusing to delete repository root.")
        elif repo_root not in data_dir.parents:
            st.error("Reset is only allowed for directories inside this repository.")
        else:
            if data_dir.exists():
                shutil.rmtree(data_dir)
            st.success(f"Cleared {data_dir}")
            st.rerun()
