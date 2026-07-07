# streamlit_ui — the Streamlit GUI layer over bom_backend.
# This codebase was written with the use of AI (Anthropic Claude), guided and reviewed by
# the maintainer. POC: Matt Buckley (matthew.p.buckley@lmco.com). See ARCHITECTURE.md.

from streamlit_ui.context import AppContext, build_app_context

__all__ = ["AppContext", "build_app_context"]
