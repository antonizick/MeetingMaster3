"""Check that docs/user-guide/configuration.md documents every setting in the Settings model.

Walks the pydantic model for leaf paths (``section.field``) and compares them with the
backticked YAML paths in the settings reference table. Exits 1 on any difference.
Run: ``uv run python scripts/check_config_docs.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from meetingmaster3.config.settings import Settings

DOC = Path(__file__).resolve().parents[1] / "docs" / "user-guide" / "configuration.md"
# Free-form containers documented as one row (their children are user-defined).
OPAQUE_PREFIXES = ("llm.backends",)


def model_of(field: FieldInfo) -> type[BaseModel] | None:
    ann = field.annotation
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann
    return None


def leaf_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    out: set[str] = set()
    for name, field in model.model_fields.items():
        path = f"{prefix}{name}"
        if path in OPAQUE_PREFIXES:
            out.add(path)
            continue
        sub = model_of(field)
        if sub is not None:
            out |= leaf_paths(sub, path + ".")
        else:
            out.add(path)
    return out


def documented_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        first = line.split("|")[1]
        for token in re.findall(r"`([a-z_][a-z0-9_.<>]*)`", first):
            token = token.replace(".<name>", "")
            if "." in token:
                paths.add(token)
    return paths


def main() -> int:
    model = leaf_paths(Settings)
    doc = documented_paths(DOC.read_text(encoding="utf-8"))
    missing = sorted(p for p in model if p not in doc)
    extra = sorted(p for p in doc if p not in model and not p.startswith(OPAQUE_PREFIXES[0] + "."))
    for p in missing:
        print(f"undocumented setting: {p}")
    for p in extra:
        print(f"documented but not in Settings: {p}")
    if not missing and not extra:
        print(f"configuration.md matches Settings ({len(model)} settings)")
    return 1 if missing or extra else 0


if __name__ == "__main__":
    sys.exit(main())
