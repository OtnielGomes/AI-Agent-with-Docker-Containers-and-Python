"""Local command: score the five Evaluation cases and publish them to LangSmith.

``--scripted-judge`` scores the chat turn with the scripted judge and does not
call LangSmith or the judge model.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from api.evaluation import local_command

if __name__ == "__main__":
    raise SystemExit(local_command())
