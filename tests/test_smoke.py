from pathlib import Path


def test_markers_file_exists() -> None:
    assert Path("markers.json").exists()

