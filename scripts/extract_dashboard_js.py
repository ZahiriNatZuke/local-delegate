"""Extrae el <script> inline del dashboard y lo escribe a un archivo, para `node --check`.

Uso:  uv run python scripts/extract_dashboard_js.py dashboard.js && node --check dashboard.js

Escribe en UTF-8 explícito (el JS contiene caracteres como '→'), robusto en Windows y Linux.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from local_delegate.web import metrics

# El <script> inline es el que NO tiene atributo src= (el otro carga Chart.js del paquete).
# IGNORECASE: hoy el HTML va todo en minúsculas, pero una etiqueta <SCRIPT> o un SRC= colado más
# adelante haría que este script extrajera el bloque equivocado —o ninguno— en silencio.
scripts = re.findall(
    r"<script(?![^>]*src=)[^>]*>(.*?)</script>", metrics.HTML, re.DOTALL | re.IGNORECASE
)
if not scripts:
    raise SystemExit("no se encontró el <script> inline del dashboard")

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dashboard.js")
out.write_text(scripts[-1], encoding="utf-8")
print(f"escrito {out} ({len(scripts[-1])} chars)")
