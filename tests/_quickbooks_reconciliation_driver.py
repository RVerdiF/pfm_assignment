"""AppTest driver: renders the "QuickBooks reconciliation" design page.

Not a pytest test itself; AppTest.from_file executes this file as a Streamlit
script in a sandbox, so importing the section module here gives the render()
function its real module globals (including ``st``).
"""
from __future__ import annotations

import sys
from pathlib import Path

STREAMLIT_DIR = Path(__file__).resolve().parents[1] / "streamlit"
if str(STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(STREAMLIT_DIR))

from sections import quickbooks_reconciliation  # noqa: E402

quickbooks_reconciliation.render()
