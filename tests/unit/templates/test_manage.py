"""Template library management against a temporary vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from meetingmaster3.errors import MM3Error
from meetingmaster3.templates import manage
from meetingmaster3.templates.loader import (
    _read_manifest,
    builtin_dir,
    install_builtins,
    load_library,
)
from meetingmaster3.templates.manage import TemplateManager, set_favorite_text
from meetingmaster3.templates.schema import parse_template

SUB = "MeetingMaster3/templates/"
FILE = "executive-summary.md"


@pytest.fixture
def mgr(tmp_path: Path) -> TemplateManager:
    root = (tmp_path / "vault").resolve()
    root.mkdir()
    manifest = tmp_path / "data" / "templates.installed.json"
    install_builtins(root, SUB, manifest)
    return TemplateManager(root, SUB, manifest)


def vault_file(mgr: TemplateManager, name: str = FILE) -> Path:
    return mgr.folder() / name


def test_favorite_changes_only_its_own_line(mgr: TemplateManager) -> None:
    path = vault_file(mgr)
    before = path.read_text()
    mgr.set_favorite(FILE, True)
    after = path.read_text()
    diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert diff == [("favorite: false", "favorite: true")]
    assert len(before.splitlines()) == len(after.splitlines())
    first = mgr.library().listing()[0]
    assert first.id == "executive-summary" and first.template.favorite  # type: ignore[union-attr]
    mgr.set_favorite(FILE, False)
    assert path.read_text() == before  # byte-identical again


def test_favorite_adds_the_key_when_missing_and_keeps_crlf() -> None:
    text = "---\r\nmm3-template: 1\r\nid: a\r\nname: A\r\n---\r\nbody\r\n"
    out = set_favorite_text(text, True)
    assert out == "---\r\nmm3-template: 1\r\nid: a\r\nname: A\r\nfavorite: true\r\n---\r\nbody\r\n"


def test_duplicate_gets_new_id_and_name(mgr: TemplateManager) -> None:
    mgr.set_favorite(FILE, True)
    new = mgr.duplicate(FILE)
    report = parse_template(vault_file(mgr, new).read_text())
    assert report.template is not None
    assert report.template.id == "executive-summary-copy"
    assert report.template.name == "Executive Summary (copy)"
    assert report.template.favorite is False
    assert report.template.sections == parse_template(vault_file(mgr).read_text()).template.sections  # type: ignore[union-attr]
    again = mgr.duplicate(FILE)
    assert again != new
    ids = [e.id for e in mgr.library().listing()]
    assert len(ids) == len(set(ids))


def test_create_from_skeleton_is_valid(mgr: TemplateManager) -> None:
    file = mgr.create("Weekly: Review / Plan")
    report = parse_template(vault_file(mgr, file).read_text())
    assert report.ok and report.template is not None
    assert report.template.name == "Weekly: Review / Plan"
    with pytest.raises(MM3Error):
        mgr.create("   ")
    assert mgr.create("Weekly: Review / Plan") != file


def test_save_valid_and_invalid(mgr: TemplateManager) -> None:
    file = mgr.create("Mine")
    path = vault_file(mgr, file)
    good = path.read_text().replace("Describe what", "Describes what")
    assert mgr.save(file, good).ok and path.read_text() == good

    broken = good.replace("kind: narrative", "kind: poetry", 1)
    result = mgr.save(file, broken)
    assert not result.ok
    assert any(i.line > 0 and i.severity == "error" for i in result.issues)
    assert path.read_text() == good  # nothing written

    other = mgr.create("Other")
    clash = vault_file(mgr, other).read_text().replace("id: other", "id: mine")
    assert not mgr.save(other, clash).ok  # another vault file already has that id


def test_save_validates_prompt_marker_problems(mgr: TemplateManager) -> None:
    file = mgr.create("Mine")
    text = vault_file(mgr, file).read_text().replace("mm3:prompt:summary", "mm3:prompt:nonexistent")
    result = mgr.save(file, text)
    assert not result.ok and any(i.line for i in result.issues)


def test_delete_custom_archives_and_builtin_is_refused(mgr: TemplateManager) -> None:
    file = mgr.create("Disposable")
    archived = mgr.delete(file)
    assert not vault_file(mgr, file).exists() and archived.is_file()
    assert archived.parent.name == manage.ARCHIVE_FOLDER
    assert "Disposable" not in [e.to_dict()["name"] for e in mgr.library().listing()]
    with pytest.raises(MM3Error) as err:
        mgr.delete(FILE)
    assert err.value.code == "E_TEMPLATE_BUILTIN"


def test_reset_builtin_archives_the_users_copy(mgr: TemplateManager) -> None:
    path = vault_file(mgr)
    shipped = (builtin_dir() / FILE).read_text()
    edited = shipped.replace("Executive Summary", "My Summary", 1)
    path.write_text(edited)
    archived = mgr.reset_builtin(FILE)
    assert archived is not None and archived.read_text() == edited
    assert path.read_text() == shipped
    assert _read_manifest(mgr.manifest_path)[FILE]  # a later app update may refresh it again
    assert mgr.reset_builtin(FILE) is None  # unchanged: nothing to archive
    with pytest.raises(MM3Error):
        mgr.reset_builtin("custom.md")


def test_reset_restores_a_deleted_builtin(mgr: TemplateManager) -> None:
    vault_file(mgr).unlink()
    mgr.reset_builtin(FILE)
    assert vault_file(mgr).read_text() == (builtin_dir() / FILE).read_text()


def test_invalid_template_is_listed_with_line_numbers(mgr: TemplateManager) -> None:
    (mgr.folder() / "broken.md").write_text("---\nmm3-template: 1\nid: BAD ID\nname: B\n---\n")
    entry = next(e for e in mgr.library().listing() if e.path.name == "broken.md")
    assert not entry.valid and any(i.line for i in entry.all_issues)


def test_edits_made_in_obsidian_show_up(mgr: TemplateManager) -> None:
    path = vault_file(mgr)
    path.write_text(path.read_text().replace("name: Executive Summary", "name: Edited Elsewhere"))
    names = [e.to_dict()["name"] for e in load_library(mgr.vault_root, SUB).listing()]
    assert "Edited Elsewhere" in names


def test_file_names_cannot_escape_the_folder(mgr: TemplateManager) -> None:
    for name in ("../x.md", "a/b.md", "_hidden.md", ".x.md", "x.txt"):
        with pytest.raises(MM3Error):
            mgr.read(name)
        with pytest.raises(MM3Error):
            mgr.set_favorite(name, True)


def test_builtin_missing_from_the_vault_is_installed_on_first_change(tmp_path: Path) -> None:
    root = (tmp_path / "vault").resolve()
    root.mkdir()
    mgr = TemplateManager(root, SUB, tmp_path / "m.json")
    mgr.set_favorite(FILE, True)
    assert (root / SUB / FILE).is_file()
