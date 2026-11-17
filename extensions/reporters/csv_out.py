import csv
import io
from pathlib import Path

from extensions.registry import REGISTRY


@REGISTRY.reporter("csv_out")
def render(result: dict, path=None, **_) -> str:
    rows = result.get("rows")
    if not rows:
        return "(no rows)"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    text = buf.getvalue()
    if path:
        Path(path).write_text(text, encoding="utf-8")
        return f"wrote {path}"
    return text