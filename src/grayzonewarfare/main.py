from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

DEFAULT_TILE_URL_TEMPLATE = "https://cdn.gzwtacmap.com/{map_version}/{code_name}/{z}/{x}/{y}.png"
DEFAULT_MAP_VERSION = "0.4"
DEFAULT_MAP_CODE_NAME = "lamang"
DEFAULT_RED_ZONE_IMAGE_URL = "https://gzwtacmap.com/_app/immutable/assets/ground-zero.D-6UoFn_.png"
MAP_WIDTH_UNITS = 14000
MAP_HEIGHT_UNITS = 8000
MAP_TILE_MIN_ZOOM = 11
MAP_TILE_MAX_ZOOM = 19
MAP_VIEW_MIN_ZOOM = 14
MAP_VIEW_MAX_ZOOM = 21


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

    map_cmd = subparsers.add_parser(
        "map",
        help="Render markers on an interactive HTML map.",
    )
    map_cmd.add_argument(
        "--source",
        choices=["markers", "taskMarkers", "all"],
        default="all",
        help="Which marker source to include",
    )
    map_cmd.add_argument("--group", dest="group_id", help="Filter by group id")
    map_cmd.add_argument("--icon", help="Filter by icon name")
    map_cmd.add_argument("--faction", help="Filter by faction value")
    map_cmd.add_argument("--search", help="Case-insensitive search in name/tooltip")
    map_cmd.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum markers to draw (0 means all)",
    )
    map_cmd.add_argument(
        "--output",
        default="map_view.html",
        help="Output HTML path (default: map_view.html)",
    )
    map_cmd.add_argument(
        "--tile-url-template",
        default=DEFAULT_TILE_URL_TEMPLATE,
        help="Background tile URL template",
    )
    map_cmd.add_argument(
        "--map-version",
        default=DEFAULT_MAP_VERSION,
        help="Map tile version (default: 0.4)",
    )
    map_cmd.add_argument(
        "--map-code-name",
        default=DEFAULT_MAP_CODE_NAME,
        help="Map code name (default: lamang)",
    )
    map_cmd.add_argument(
        "--red-zone-image",
        "--map-image",
        dest="red_zone_image",
        default=DEFAULT_RED_ZONE_IMAGE_URL,
        help="Optional red-zone overlay image URL",
    )
    map_cmd.add_argument(
        "--no-red-zone",
        action="store_true",
        help="Disable the red-zone overlay image",
    )
    map_cmd.add_argument(
        "--flip-y",
        action="store_true",
        help="Flip marker Y axis (use if points appear vertically inverted)",
    )
    map_cmd.add_argument(
        "--open",
        action="store_true",
        help="Open the generated HTML map in your default browser",
    )

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


def _build_map_markers(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = _filter_markers(rows, args)
    filtered.sort(key=lambda row: (_as_text(row.get("name")).lower(), _as_text(row.get("id"))))

    markers: list[dict[str, Any]] = []
    for row in filtered:
        lat = row.get("lat")
        lng = row.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue

        marker_lat = float(lat)
        if args.flip_y:
            marker_lat = MAP_HEIGHT_UNITS - marker_lat

        markers.append(
            {
                "id": _as_text(row.get("id")),
                "name": _as_text(row.get("name")),
                "icon": _as_text(row.get("icon")),
                "source": _as_text(row.get("_source")),
                "group": _as_text(row.get("_group_id")),
                "faction": _as_text(row.get("faction")),
                "tooltip": _as_text(row.get("tooltip")),
                "lat": marker_lat,
                "lng": float(lng),
            }
        )

    if args.limit > 0:
        markers = markers[: args.limit]

    return markers


def _resolve_tile_url(template: str, map_version: str, map_code_name: str) -> str:
    resolved = template.replace("{map_version}", map_version)
    resolved = resolved.replace("{code_name}", map_code_name)
    return resolved


def _render_map_html(
    markers: list[dict[str, Any]],
    tile_url: str,
    red_zone_image: str | None,
    title: str,
) -> str:
    markers_json = json.dumps(markers, ensure_ascii=False)
    tile_url_json = json.dumps(tile_url)
    red_zone_json = "null" if red_zone_image is None else json.dumps(red_zone_image)
    title_text = escape(title)
    marker_count = len(markers)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_text}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@10.6.1/ol.css" />
  <style>
    :root {{
      --bg: #0b1118;
      --panel: rgba(9, 17, 27, 0.86);
      --text: #d7e0ea;
      --muted: #8ea3b8;
      --accent: #ff8a3d;
      --card: rgba(3, 8, 14, 0.92);
    }}
    html, body {{
      height: 100%;
      margin: 0;
      background: radial-gradient(circle at 15% 10%, #111c2b 0%, var(--bg) 60%);
      color: var(--text);
      font-family: "Segoe UI", Tahoma, sans-serif;
    }}
    #app {{
      display: grid;
      grid-template-columns: 320px 1fr;
      height: 100%;
    }}
    #panel {{
      padding: 16px;
      background: var(--panel);
      border-right: 1px solid rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(4px);
      overflow: auto;
    }}
    #map {{
      width: 100%;
      height: 100%;
      background: #04070b;
    }}
    h1 {{
      font-size: 19px;
      margin: 0 0 10px 0;
      letter-spacing: 0.3px;
    }}
    .stat {{
      margin: 8px 0;
      color: var(--muted);
      line-height: 1.4;
      font-size: 14px;
    }}
    .value {{
      color: var(--text);
      font-weight: 600;
    }}
    code {{
      color: var(--accent);
      word-break: break-word;
    }}
    .hint {{
      margin-top: 14px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }}
    #popup {{
      position: relative;
      padding: 10px;
      min-width: 220px;
      max-width: 360px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: var(--card);
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.45);
      font-size: 13px;
      line-height: 1.35;
    }}
    #popup .popup-title {{
      margin-bottom: 6px;
      font-weight: 700;
    }}
    @media (max-width: 900px) {{
      #app {{
        grid-template-columns: 1fr;
        grid-template-rows: 190px 1fr;
      }}
      #panel {{
        border-right: none;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      }}
    }}
  </style>
</head>
<body>
  <div id="app">
    <aside id="panel">
      <h1>{title_text}</h1>
      <div class="stat">Loaded markers: <span class="value">{marker_count}</span></div>
      <div class="stat">Map extent: <span class="value">{MAP_WIDTH_UNITS} x {MAP_HEIGHT_UNITS}</span></div>
      <div class="stat">Base tiles: <code>{escape(tile_url)}</code></div>
      <div class="stat">Red zone overlay: <code>{escape(red_zone_image or "disabled")}</code></div>
      <div class="hint">
        Controls: mouse wheel to zoom, drag to pan, click marker for details.
      </div>
    </aside>
    <main id="map"></main>
  </div>

  <div id="popup" hidden></div>

  <script src="https://cdn.jsdelivr.net/npm/ol@10.6.1/dist/ol.js"></script>
  <script>
    const tileUrl = {tile_url_json};
    const redZoneImageUrl = {red_zone_json};
    const markers = {markers_json};

    const mapWidth = {MAP_WIDTH_UNITS};
    const mapHeight = {MAP_HEIGHT_UNITS};
    const extent = [0, 0, mapWidth, mapHeight];
    const viewExtent = [-3000, -3000, mapWidth + 3000, mapHeight + 3000];

    const layers = [];
    const backgroundLayer = new ol.layer.Tile({{
      source: new ol.source.XYZ({{
        url: tileUrl,
        crossOrigin: "anonymous",
        minZoom: {MAP_TILE_MIN_ZOOM},
        maxZoom: {MAP_TILE_MAX_ZOOM},
        useInterimTilesOnError: true
      }}),
      zIndex: 0,
      extent: extent
    }});
    layers.push(backgroundLayer);

    if (redZoneImageUrl) {{
      const redZoneLayer = new ol.layer.Image({{
        source: new ol.source.ImageStatic({{
          url: redZoneImageUrl,
          imageExtent: extent,
          crossOrigin: "anonymous"
        }}),
        zIndex: 1
      }});
      layers.push(redZoneLayer);
    }}

    const features = [];
    for (const item of markers) {{
      if (typeof item.lat !== "number" || typeof item.lng !== "number") {{
        continue;
      }}
      const feature = new ol.Feature({{
        geometry: new ol.geom.Point([item.lng, item.lat]),
        markerData: item
      }});
      features.push(feature);
    }}

    const markerSource = new ol.source.Vector({{
      features: features,
      wrapX: false
    }});

    const markerLayer = new ol.layer.Vector({{
      source: markerSource,
      zIndex: 5,
      style: new ol.style.Style({{
        image: new ol.style.Circle({{
          radius: 4.4,
          fill: new ol.style.Fill({{ color: "rgba(255, 138, 61, 0.86)" }}),
          stroke: new ol.style.Stroke({{ color: "rgba(255, 232, 212, 0.95)", width: 1.1 }})
        }})
      }})
    }});
    layers.push(markerLayer);

    const map = new ol.Map({{
      target: "map",
      layers: layers,
      view: new ol.View({{
        center: [mapWidth / 2, mapHeight / 2],
        zoom: 15,
        minZoom: {MAP_VIEW_MIN_ZOOM},
        maxZoom: {MAP_VIEW_MAX_ZOOM},
        extent: viewExtent
      }}),
      controls: ol.control.defaults.defaults({{ attribution: false }}),
      interactions: ol.interaction.defaults.defaults({{
        altShiftDragRotate: false,
        pinchRotate: false
      }})
    }});

    function esc(text) {{
      const div = document.createElement("div");
      div.textContent = text ?? "";
      return div.innerHTML;
    }}

    const popupEl = document.getElementById("popup");
    const popup = new ol.Overlay({{
      element: popupEl,
      positioning: "bottom-left",
      offset: [10, -10],
      stopEvent: false
    }});
    map.addOverlay(popup);

    map.on("singleclick", (event) => {{
      const feature = map.forEachFeatureAtPixel(event.pixel, (f) => f);
      if (!feature) {{
        popup.setPosition(undefined);
        popupEl.hidden = true;
        return;
      }}
      const item = feature.get("markerData");
      popupEl.innerHTML = `
        <div class="popup-title">${{esc(item.name || "Unnamed Marker")}}</div>
        <div><strong>ID:</strong> ${{esc(item.id)}}</div>
        <div><strong>Icon:</strong> ${{esc(item.icon)}}</div>
        <div><strong>Source:</strong> ${{esc(item.source)}} / group ${{esc(item.group)}}</div>
        <div><strong>Faction:</strong> ${{esc(item.faction || "-")}}</div>
        <div><strong>Position:</strong> lat=${{item.lat.toFixed(2)}}, lng=${{item.lng.toFixed(2)}}</div>
        <div><strong>Tooltip:</strong> ${{esc(item.tooltip || "-")}}</div>
      `;
      popup.setPosition(feature.getGeometry().getCoordinates());
      popupEl.hidden = false;
    }});

    map.on("pointermove", (event) => {{
      if (event.dragging) {{
        return;
      }}
      const hit = map.hasFeatureAtPixel(event.pixel);
      map.getTargetElement().style.cursor = hit ? "pointer" : "";
    }});
  </script>
</body>
</html>
"""


def _run_map(rows: list[dict[str, Any]], args: argparse.Namespace) -> int:
    markers = _build_map_markers(rows, args)
    if not markers:
        print("No marker rows matched the current filters.")
        return 1

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tile_url = _resolve_tile_url(
        args.tile_url_template,
        map_version=args.map_version,
        map_code_name=args.map_code_name,
    )
    red_zone_image = None if args.no_red_zone else args.red_zone_image

    title = "Gray Zone Warfare Marker Map"
    html = _render_map_html(
        markers,
        tile_url=tile_url,
        red_zone_image=red_zone_image,
        title=title,
    )
    output_path.write_text(html, encoding="utf-8")

    print(f"Wrote map HTML with {len(markers)} markers:")
    print(f"  {output_path}")
    print(f"Base tiles: {tile_url}")
    print(f"Red-zone overlay: {red_zone_image or 'disabled'}")

    if args.open:
        webbrowser.open(output_path.resolve().as_uri())
        print("Opened map in your default browser.")

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
        _run_summary(map_data, rows, top=getattr(args, "top", 10))
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
    if command == "map":
        map_rows = iter_markers(map_data, source=args.source)
        return _run_map(map_rows, args)

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
