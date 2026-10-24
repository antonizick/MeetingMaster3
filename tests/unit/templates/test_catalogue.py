"""The generated template catalogue must match the built-in template files."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).parents[3] / "scripts" / "gen_template_catalogue.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_template_catalogue", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogue_is_up_to_date() -> None:
    module = load_script()
    expected = module.render(module.load_templates())
    assert module.TARGET.read_text(encoding="utf-8") == expected, (
        "docs/user-guide/template-catalogue.md is stale; "
        "run `uv run python scripts/gen_template_catalogue.py`"
    )


def test_catalogue_lists_every_template() -> None:
    module = load_script()
    text = module.TARGET.read_text(encoding="utf-8")
    templates = module.load_templates()
    assert len(templates) == 24
    for t in templates:
        assert f"`{t.id}`" in text and f"## {t.name}" in text
