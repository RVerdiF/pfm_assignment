"""Walkthrough page sections for the PFM Streamlit app.

Each module exposes a ``render()`` callable registered as an ``st.Page`` in
``app.py``. Sections stay thin: they read the published consumer relations
(the marts plus the single ADR-8 diagnostic intermediate view) through
``warehouse_bootstrap`` and never re-implement attribution or business joins.
"""
