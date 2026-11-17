import json
from pathlib import Path

from extensions.registry import REGISTRY


@REGISTRY.reporter("json_out")
def render(result: dict, path=None, **_) -> str:
    text = json.dumps(result, indent=2, default=str, sort_keys=True)
    if path:
        Path(path).write_text(text, encoding="utf-8")
        return f"wrote {path}"
    return text