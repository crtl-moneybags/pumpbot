from extensions.registry import REGISTRY


@REGISTRY.reporter("table")
def render(result: dict, path=None, **_) -> str:
    rows = result.get("rows")
    if rows:
        keys = list(rows[0].keys())
        widths = {
            k: max([len(k)] + [len(str(r.get(k, ""))) for r in rows])
            for k in keys
        }
        lines = [" | ".join(k.ljust(widths[k]) for k in keys)]
        lines.append("-+-".join("-" * widths[k] for k in keys))
        for r in rows:
            lines.append(" | ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys))
        return "\n".join(lines)

    # Fallback: render flat key/value metrics as aligned pairs
    kv = {k: v for k, v in result.items() if not isinstance(v, (dict, list))}
    if not kv:
        return "(no data)"
    width = max(len(k) for k in kv)
    return "\n".join(f"{k.ljust(width)}  {v}" for k, v in kv.items())