"""Template library: built-ins, vault overrides, invalid files, and non-clobbering install."""

from __future__ import annotations

from pathlib import Path

import pytest

from meetingmaster3.errors import MM3Error
from meetingmaster3.templates.loader import (
    builtin_dir,
    ensure_installed,
    install_builtins,
    load_library,
)

SUB = "MeetingMaster3/templates/"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


def builtin_text(name: str = "executive-summary") -> str:
    return (builtin_dir() / f"{name}.md").read_text(encoding="utf-8")


def test_builtins_only_without_vault() -> None:
    lib = load_library()
    assert set(lib.by_id()) == {
        "executive-summary",
        "technical-deep-dive",
        "decision-log",
        "action-focused",
        "just-the-facts",
    }
    assert lib.get("decision-log").name == "Decision Log"
    with pytest.raises(MM3Error) as err:
        lib.get("nope")
    assert err.value.code == "E_TEMPLATE_NOT_FOUND" and err.value.status_code == 404


def test_vault_template_overrides_builtin_by_id(vault: Path) -> None:
    folder = vault / SUB
    folder.mkdir(parents=True)
    custom = builtin_text().replace("name: Executive Summary", "name: My Exec Brief")
    (folder / "my-brief.md").write_text(custom, encoding="utf-8")
    lib = load_library(vault, SUB)
    entry = lib.by_id()["executive-summary"]
    assert entry.source == "vault" and entry.overrides_builtin
    assert lib.get("executive-summary").name == "My Exec Brief"
    listed = [e.to_dict() for e in lib.listing()]
    assert sum(d["id"] == "executive-summary" for d in listed) == 1  # the override only


def test_invalid_templates_are_listed_not_raised(vault: Path) -> None:
    folder = vault / SUB
    folder.mkdir(parents=True)
    (folder / "broken.md").write_text("---\nid: broken\nname: Broken\n---\n", encoding="utf-8")
    (folder / "_README.md").write_text("ignored", encoding="utf-8")
    (folder / ".hidden.md").write_text("ignored", encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    lib = load_library(vault, SUB)
    broken = [e for e in lib.listing() if not e.valid]
    assert [e.path.name for e in broken] == ["broken.md"]
    data = broken[0].to_dict()
    assert data["valid"] is False and data["issues"][0]["code"] == "schema_error"
    assert lib.listing()[-1].path.name == "broken.md"  # invalid ones sort last
    with pytest.raises(MM3Error) as err:
        lib.get("broken")
    assert err.value.code == "E_TEMPLATE_INVALID"


def test_invalid_override_keeps_the_builtin(vault: Path) -> None:
    folder = vault / SUB
    folder.mkdir(parents=True)
    broken = builtin_text().replace("kind: narrative}", "kind: poetry}", 1)
    (folder / "executive-summary.md").write_text(broken, encoding="utf-8")
    lib = load_library(vault, SUB)
    assert lib.by_id()["executive-summary"].source == "builtin"


def test_duplicate_vault_ids_are_both_invalid(vault: Path) -> None:
    folder = vault / SUB
    folder.mkdir(parents=True)
    text = builtin_text("decision-log").replace("id: decision-log", "id: shared")
    (folder / "a.md").write_text(text, encoding="utf-8")
    (folder / "b.md").write_text(text, encoding="utf-8")
    lib = load_library(vault, SUB)
    assert "shared" not in lib.by_id()
    codes = {i.code for e in lib.entries if e.path.parent == folder for i in e.all_issues}
    assert codes == {"duplicate_template_id"}


def test_symlink_out_of_the_vault_is_ignored(vault: Path, tmp_path: Path) -> None:
    folder = vault / SUB
    folder.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text(builtin_text().replace("id: executive-summary", "id: evil"), "utf-8")
    (folder / "evil.md").symlink_to(outside)
    assert "evil" not in load_library(vault, SUB).by_id()


def test_templates_folder_cannot_escape(vault: Path) -> None:
    lib = load_library(vault, "../elsewhere/")  # logged, built-ins still load
    assert "executive-summary" in lib.by_id()
    with pytest.raises(MM3Error):
        install_builtins(vault, "../elsewhere/", vault / "m.json")


def test_install_never_overwrites_user_edits(vault: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "data" / "templates.installed.json"
    first = install_builtins(vault, SUB, manifest)
    assert {r.action for r in first} == {"installed"} and len(first) == 5
    folder = vault / SUB
    assert (folder / "executive-summary.md").read_text("utf-8") == builtin_text()

    again = install_builtins(vault, SUB, manifest)
    assert {r.action for r in again} == {"unchanged"}

    edited = folder / "decision-log.md"
    edited.write_text(edited.read_text("utf-8") + "\n<!-- my note -->\n", encoding="utf-8")
    third = {r.file: r.action for r in install_builtins(vault, SUB, manifest)}
    assert third["decision-log.md"] == "kept"
    assert edited.read_text("utf-8").endswith("<!-- my note -->\n")

    (folder / "just-the-facts.md").unlink()  # deleted by the user: installed again on demand
    fourth = {r.file: r.action for r in install_builtins(vault, SUB, manifest)}
    assert fourth["just-the-facts.md"] == "installed"


def test_install_updates_untouched_old_versions(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "m.json"
    install_builtins(vault, SUB, manifest)
    target = vault / SUB / "action-focused.md"
    # Simulate an older shipped version that MM3 itself installed: the vault copy matches the
    # manifest hash, so a newer built-in may replace it.
    old = target.read_text("utf-8").replace("Action-Focused", "Action Focused (old)")
    target.write_text(old, encoding="utf-8")
    import hashlib
    import json

    data = json.loads(manifest.read_text("utf-8"))
    data["files"]["action-focused.md"] = hashlib.sha256(old.encode()).hexdigest()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    results = {r.file: r.action for r in install_builtins(vault, SUB, manifest)}
    assert results["action-focused.md"] == "updated"
    assert target.read_text("utf-8") == builtin_text("action-focused")


def test_ensure_installed_runs_once(vault: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    assert ensure_installed(vault, SUB, manifest) is True
    (vault / SUB / "executive-summary.md").unlink()
    assert ensure_installed(vault, SUB, manifest) is False  # folder exists: no re-install
    assert not (vault / SUB / "executive-summary.md").exists()
