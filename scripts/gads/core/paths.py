"""The repository root, defined once so modules do not each count parent folders."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # scripts/gads/core/paths.py -> repository root
