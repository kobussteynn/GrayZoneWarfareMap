# GrayZoneWarfareMap

Python project scaffold for working with `markers.json`.

## Quick start (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .[dev]
pytest
```

## Run the CLI

```powershell
grayzonewarfare
```

## CLI examples

```powershell
# Overview
grayzonewarfare summary

# Show biggest groups
grayzonewarfare groups --limit 20

# Browse markers
grayzonewarfare list --source markers --limit 15

# Search markers by text
grayzonewarfare list --search "Landing Zone" --limit 10

# Show one marker as JSON
grayzonewarfare show --id 923
```
