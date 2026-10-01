#!/bin/sh
set -u

root=$(git rev-parse --show-toplevel 2>/dev/null) || root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$root" || exit 1

status=0

echo "== pytest =="
if ! (cd api && python -m pytest); then
  status=1
fi

echo "== web lint =="
if ! (cd web && npm run lint); then
  status=1
fi

echo "== readme images =="
if ! python - "$root" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
image = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
missing = []
for name in ("README.md", "README.pt-BR.md"):
    text = (root / name).read_text(encoding="utf-8")
    for match in image.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith("<"):
            dest = raw[1:].split(">", 1)[0].strip()
        else:
            dest = raw.split()[0].strip()
        if dest.startswith(("http://", "https://")):
            continue
        path = (root / name).parent / dest
        if not path.is_file():
            missing.append(f"{name}: {dest}")
if missing:
    print("Missing README images:")
    for item in missing:
        print(f"  {item}")
    sys.exit(1)
print("README images ok")
PY
then
  status=1
fi

exit "$status"
