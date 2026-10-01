"""Local command: score the five Evaluation cases with a scripted turn and judge."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api.evaluation import main

raise SystemExit(main())
