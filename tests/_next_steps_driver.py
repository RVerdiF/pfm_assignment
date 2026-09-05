"""AppTest driver: renders the "What I'd do next" page for headless testing.

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

from sections import next_steps  # noqa: E402

next_steps.render()
