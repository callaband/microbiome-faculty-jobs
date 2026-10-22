"""Daily collector for the Microbiome Faculty Jobs tracker."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "data"          # caches, not published
SITE_DATA_DIR = ROOT / "docs" / "data"  # published with the website
