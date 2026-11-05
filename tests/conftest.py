import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Never download translation models or call translation services from tests.
os.environ.setdefault("MFJ_NO_TRANSLATION", "1")
