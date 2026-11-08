"""Imprime el OpenAPI de la API (JSON) para generar el cliente del POS: `uv run python -m scripts.volcar_openapi`."""

import json
import sys

from app.main import create_app

sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False))
