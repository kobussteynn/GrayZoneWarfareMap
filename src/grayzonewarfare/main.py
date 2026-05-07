from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    markers_path = Path.cwd() / "markers.json"
    if not markers_path.exists():
        print(f"markers.json not found at: {markers_path}")
        return

    with markers_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        print(f"Loaded {len(data)} markers from markers.json")
    elif isinstance(data, dict):
        print(f"Loaded markers.json with {len(data)} top-level keys")
    else:
        print("Loaded markers.json")


if __name__ == "__main__":
    main()

