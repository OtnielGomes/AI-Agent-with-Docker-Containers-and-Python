"""Local command: score the five Evaluation cases with a scripted turn and the model judge."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api.evaluation import score_with_model_judge

if __name__ == "__main__":
    raise SystemExit(score_with_model_judge())
