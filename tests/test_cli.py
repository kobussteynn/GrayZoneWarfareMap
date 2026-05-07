from pathlib import Path

from grayzonewarfare.main import iter_markers, load_map_data, main


def test_load_map_data_has_expected_sections() -> None:
    data = load_map_data(Path("markers.json"))
    assert "markers" in data
    assert "taskMarkers" in data


def test_iter_markers_returns_rows() -> None:
    data = load_map_data(Path("markers.json"))
    rows = iter_markers(data)
    assert rows
    assert "id" in rows[0]
    assert "_source" in rows[0]
    assert "_group_id" in rows[0]


def test_cli_summary_returns_success() -> None:
    assert main(["summary", "--top", "2"]) == 0


def test_cli_map_writes_output(tmp_path: Path) -> None:
    output = tmp_path / "map.html"
    assert (
        main(
            [
                "map",
                "--limit",
                "50",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Gray Zone Warfare Marker Map" in content
