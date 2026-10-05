"""Expose the existing FastAPI app to Vercel's Python runtime."""

import sys
from importlib import import_module
from pathlib import Path

# Docker supplies PYTHONPATH=/work/src; hosted imports start at this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

app = import_module("app.api").app
