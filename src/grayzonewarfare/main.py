from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _decode_reference_payload(refs: list[Any]) -> Any:
    cache: dict[int, Any] = {}
    resolving: set[int] = set()

    def resolve_index(index: int) -> Any:
        if index in cache:
            return cache[index]
        if index in resolving:
            return None
        resolving.add(index)

        value = refs[index]
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            cache[index] = output
            for key, item in value.items():
                output[key] = resolve_value(item)
        elif isinstance(value, list):
            output = []
            cache[index] = output
            output.extend(resolve_value(item) for item in value)
        else:
            output = value
            cache[index] = output

        resolving.remove(index)
        return output

    def resolve_value(value: Any) -> Any:
        if isinstance(value, int) and 0 <= value < len(refs):
            return resolve_index(value)
        return value

    return resolve_index(0)


def load_map_data(markers_path: Path) -> dict[str, Any]:
    with markers_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and isinstance(raw.get("result"), str):
        payload = json.loads(raw["result"])
        if not isinstance(payload, list):
            raise ValueError("markers.json result payload must be a list")
        decoded = _decode_reference_payload(payload)
        if not isinstance(decoded, dict):
            raise ValueError("decoded markers payload must be an object")
        return decoded

    if isinstance(raw, dict):
        return raw

    raise ValueError("markers.json has an unsupported format")


def iter_markers(map_data: dict[str, Any], source: str = "all") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_keys = ["markers", "taskMarkers"] if source == "all" else [source]

    for src in source_keys:
        groups = map_data.get(src, {})
        if not isinstance(groups, dict):
            continue
        for group_id, group in groups.items():
            if not isinstance(group, dict):
                continue
            markers_array = group.get("markersArray", [])
            if not isinstance(markers_array, list):
                continue
            for marker in markers_array:
                if not isinstance(marker, dict):
                    continue
                row = dict(marker)
                row["_source"] = src
                row["_group_id"] = str(group_id)
                rows.append(row)

    return rows


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _name_from_object(value: Any) -> str:
    if isinstance(value, dict):
        return _as_text(value.get("name"))
    return _as_text(value)


def _format_float(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return _as_text(value)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def print_table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("No rows to display.")
        return

    max_width = {
        "name": 36,
        "tooltip": 30,
        "icon": 18,
        "poi": 20,
    }

    widths: dict[str, int] = {}
    for key, header in columns:
        width = len(header)
        for row in rows:
            value = row.get(key, "")
            width = max(width, len(value))
        width = min(width, max_width.get(key, width))
        widths[key] = width

    header_line = " | ".join(header.ljust(widths[key]) for key, header in columns)
    separator = "-+-".join("-" * widths[key] for key, _ in columns)
    print(header_line)
    print(separator)

    for row in rows:
        line = " | ".join(
            _truncate(row.get(key, ""), widths[key]).ljust(widths[key])
            for key, _ in columns
        )
        print(line)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Gray Zone Warfare map data.")
    parser.add_argument(
        "--file",
        default="markers.json",
        help="Path to markers file (default: markers.json)",
    )

    subparsers = parser.add_subparsers(dest="command")

    summary = subparsers.add_parser("summary", help="Show high-level marker summary.")
    summary.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top values to show (default: 10)",
    )

    groups = subparsers.add_parser("groups", help="Show marker group counts.")
    groups.add_argument(
        "--source",
        choices=["markers", "taskMarkers", "all"],
        default="all",
        help="Which source groups to show",
    )
    groups.add_argument(
        "--limit",
        type=int,
        default=30,
        help="How many groups to show (default: 30)",
    )

    list_cmd = subparsers.add_parser("list", help="List marker rows.")
    list_cmd.add_argument(
        "--source",
        choices=["markers", "taskMarkers", "all"],
        default="all",
        help="Which marker source to include",
    )
    list_cmd.add_argument("--group", dest="group_id", help="Filter by group id")
    list_cmd.add_argument("--icon", help="Filter by icon name")
    list_cmd.add_argument("--faction", help="Filter by faction value")
    list_cmd.add_argument("--search", help="Case-insensitive search in name/tooltip")
    list_cmd.add_argument("--limit", type=int, default=25, help="Rows to print")
    list_cmd.add_argument("--offset", type=int, default=0, help="Row offset")

    show = subparsers.add_parser("show", help="Show full marker JSON by marker id.")
    show.add_argument("--id", required=True, help="Marker id")

    return parser


def _filter_markers(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = rows

    if getattr(args, "group_id", None):
        filtered = [row for row in filtered if row.get("_group_id") == str(args.group_id)]
    if getattr(args, "icon", None):
        icon = args.icon.lower()
        filtered = [row for row in filtered if _as_text(row.get("icon")).lower() == icon]
    if getattr(args, "faction", None):
        faction = args.faction.lower()
        filtered = [row for row in filtered if _as_text(row.get("faction")).lower() == faction]
    if getattr(args, "search", None):
        needle = args.search.lower()
        filtered = [
            row
            for row in filtered
            if needle in _as_text(row.get("name")).lower()
            or needle in _as_text(row.get("tooltip")).lower()
        ]

    return filtered


def _run_summary(map_data: dict[str, Any], rows: list[dict[str, Any]], top: int) -> None:
    groups = {
        "markers": map_data.get("markers", {}),
        "taskMarkers": map_data.get("taskMarkers", {}),
    }
    total_groups = {
        key: len(value) if isinstance(value, dict) else 0 for key, value in groups.items()
    }
    total_rows = {
        "markers": sum(1 for row in rows if row.get("_source") == "markers"),
        "taskMarkers": sum(1 for row in rows if row.get("_source") == "taskMarkers"),
    }

    print(f"Total marker rows: {len(rows)}")
    print(f"  markers: {total_rows['markers']} in {total_groups['markers']} groups")
    print(f"  taskMarkers: {total_rows['taskMarkers']} in {total_groups['taskMarkers']} groups")

    icon_counts = Counter(_as_text(row.get("icon")) for row in rows)
    group_counts = Counter(_as_text(row.get("_group_id")) for row in rows)
    poi_counts = Counter(
        _name_from_object(row.get("poi")) for row in rows if row.get("poi") is not None
    )

    print("")
    print(f"Top {top} icons:")
    for value, count in icon_counts.most_common(top):
        print(f"  {value}: {count}")

    print("")
    print(f"Top {top} groups by row count:")
    for value, count in group_counts.most_common(top):
        print(f"  {value}: {count}")

    print("")
    print(f"Top {top} POIs:")
    for value, count in poi_counts.most_common(top):
        print(f"  {value}: {count}")


def _run_groups(map_data: dict[str, Any], source: str, limit: int) -> None:
    rows: list[dict[str, str]] = []
    source_keys = ["markers", "taskMarkers"] if source == "all" else [source]

    for src in source_keys:
        groups = map_data.get(src, {})
        if not isinstance(groups, dict):
            continue
        for group_id, group in groups.items():
            if not isinstance(group, dict):
                continue
            markers_array = group.get("markersArray", [])
            count = len(markers_array) if isinstance(markers_array, list) else 0
            rows.append(
                {
                    "source": src,
                    "group": _as_text(group_id),
                    "count": _as_text(count),
                    "visible": _as_text(group.get("visible")),
                    "minZoom": _as_text(group.get("minZoom")),
                    "maxZoom": _as_text(group.get("maxZoom")),
                }
            )

    rows.sort(key=lambda row: int(row["count"]), reverse=True)
    print_table(
        rows[:limit],
        [
            ("source", "source"),
            ("group", "group"),
            ("count", "count"),
            ("visible", "visible"),
            ("minZoom", "minZoom"),
            ("maxZoom", "maxZoom"),
        ],
    )


def _run_list(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    filtered = _filter_markers(rows, args)
    filtered.sort(key=lambda row: (_as_text(row.get("name")).lower(), _as_text(row.get("id"))))

    start = max(args.offset, 0)
    end = start + max(args.limit, 0)
    page = filtered[start:end]

    display_rows = []
    for row in page:
        display_rows.append(
            {
                "id": _as_text(row.get("id")),
                "name": _as_text(row.get("name")),
                "icon": _as_text(row.get("icon")),
                "source": _as_text(row.get("_source")),
                "group": _as_text(row.get("_group_id")),
                "poi": _name_from_object(row.get("poi")),
                "faction": _as_text(row.get("faction")),
                "lat": _format_float(row.get("lat")),
                "lng": _format_float(row.get("lng")),
            }
        )

    print(f"Rows: {len(filtered)} total, showing {len(page)} (offset {start})")
    print("")
    print_table(
        display_rows,
        [
            ("id", "id"),
            ("name", "name"),
            ("icon", "icon"),
            ("source", "source"),
            ("group", "group"),
            ("poi", "poi"),
            ("faction", "faction"),
            ("lat", "lat"),
            ("lng", "lng"),
        ],
    )


def _run_show(rows: list[dict[str, Any]], marker_id: str) -> int:
    matches = [row for row in rows if _as_text(row.get("id")) == marker_id]
    if not matches:
        print(f"No marker found with id: {marker_id}")
        return 1
    if len(matches) > 1:
        print(f"Found {len(matches)} markers with id {marker_id}. Showing all.")
    for idx, marker in enumerate(matches, start=1):
        if len(matches) > 1:
            print(f"\n--- Match {idx} ---")
        print(json.dumps(marker, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    markers_path = Path(args.file)
    if not markers_path.is_absolute():
        markers_path = Path.cwd() / markers_path

    if not markers_path.exists():
        print(f"markers.json not found at: {markers_path}")
        return 1

    try:
        map_data = load_map_data(markers_path)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to parse markers file: {exc}")
        return 1

    if not isinstance(map_data, dict):
        print("Map data must be a JSON object.")
        return 1

    rows = iter_markers(map_data, source="all")

    command = args.command or "summary"
    if command == "summary":
        _run_summary(map_data, rows, top=args.top)
        return 0
    if command == "groups":
        _run_groups(map_data, source=args.source, limit=args.limit)
        return 0
    if command == "list":
        list_rows = iter_markers(map_data, source=args.source)
        _run_list(list_rows, args)
        return 0
    if command == "show":
        return _run_show(rows, args.id)

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
