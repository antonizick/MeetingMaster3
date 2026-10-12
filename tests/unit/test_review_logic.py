"""Review workspace logic without the web layer: picker, store, save, rename, template switch."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.markdown.editing import Edits, edits_of, split_document
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.review.rename import plan_rename, replace_names
from meetingmaster3.review.save import SaveConflict, save_note
from meetingmaster3.review.store import KEEP_BASES, ReviewStore, text_sha
from meetingmaster3.review.switch import PRESERVED_HEADING, preserved_text, switch_template
from meetingmaster3.review.workspace import transcript_view
from meetingmaster3.templates.loader import load_library
from meetingmaster3.vault import picker
from meetingmaster3.vault.io import read_text

FIXTURES = Path(__file__).parents[1] / "fixtures" / "notes"
NOTE = "2026-10-11 - Product Sync.md"
COMPANION = "2026-10-11 - Product Sync.transcript.md"
MM3_ID = "3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = (tmp_path / "vault").resolve()
    folder = root / "Meetings" / "2026"
    folder.mkdir(parents=True)
    (root / ".obsidian").mkdir()
    for name in (NOTE, COMPANION):
        shutil.copyfile(FIXTURES / name, folder / name)
    return root


# -- picker ----------------------------------------------------------------------------------------


def test_browse_lists_folders_and_mm3_notes_only(vault: Path, tmp_path: Path) -> None:
    folder = vault / "Meetings" / "2026"
    (folder / "plain.md").write_text("# just a note\n", encoding="utf-8")
    (folder / "Archive").mkdir()
    archived = folder / "Archive" / "old.md"
    archived.write_text(f"---\nmm3-id: {MM3_ID}\nmm3-archived: 2026-10-11\n---\n", "utf-8")
    shutil.copyfile(archived, folder / "copy-archived.md")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "gone.md").write_text(f"---\nmm3-id: {MM3_ID}\n---\n", "utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(f"---\nmm3-id: {MM3_ID}\n---\n", "utf-8")
    os.symlink(outside, vault / "escape")
    os.symlink(outside / "secret.md", folder / "linked.md")

    top = picker.browse(vault)
    assert [e.name for e in top.entries] == ["Meetings"] and top.parent is None
    listing = picker.browse(vault, "Meetings/2026")
    assert listing.parent == "Meetings"
    assert [(e.kind, e.name) for e in listing.entries] == [("dir", "Archive"), ("note", NOTE)]
    note = listing.entries[1]
    assert note.mm3_id == MM3_ID and note.title == "Product Sync" and note.date == "2026-10-11"
    assert note.path == f"Meetings/2026/{NOTE}"


@pytest.mark.parametrize("bad", ["../", "/etc", "~/x", "Meetings/../../", "escape"])
def test_browse_cannot_escape_the_vault(vault: Path, tmp_path: Path, bad: str) -> None:
    os.symlink(tmp_path, vault / "escape")
    with pytest.raises(MM3Error) as exc:
        picker.browse(vault, bad)
    assert exc.value.code == "vault_path_escape"


def test_browse_missing_folder_and_truncation(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(MM3Error) as exc:
        picker.browse(vault, "nope")
    assert exc.value.status_code == 404
    folder = vault / "many"
    folder.mkdir()
    for i in range(5):
        (folder / f"{i}.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(picker, "MAX_FILES", 3)
    assert picker.browse(vault, "many").truncated


def test_find_companions_anywhere_in_the_vault(vault: Path) -> None:
    moved = vault / "Elsewhere"
    moved.mkdir()
    shutil.move(vault / "Meetings" / "2026" / COMPANION, moved / "renamed.md")
    assert picker.find_companions(vault, MM3_ID) == [moved / "renamed.md"]
    assert picker.find_companions(vault, str(uuid.uuid4())) == []


# -- store -----------------------------------------------------------------------------------------


def test_store_bases_drafts_and_pending(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path, MM3_ID)
    shas = [store.put_base(f"version {i}") for i in range(KEEP_BASES + 2)]
    assert store.base(shas[-1]) == f"version {KEEP_BASES + 1}"
    assert store.base(shas[0]) is None  # pruned
    assert store.base("../../etc/passwd") is None
    assert oct(store.folder.stat().st_mode & 0o777) == "0o700"

    assert store.draft() is None
    store.save_draft(shas[-1], Edits(["a"], {"s": "b"}, None))
    draft = store.draft()
    assert draft is not None and draft.base_sha == shas[-1] and draft.edits.sections == {"s": "b"}
    (store.folder / "draft.json").write_text("{broken", encoding="utf-8")
    assert store.draft() is None and not (store.folder / "draft.json").exists()

    token = store.put_pending("sha", "new text", {"template": "x"})
    assert store.pending(token) == ("new text", {"base_sha": "sha", "template": "x"})
    assert store.pending("../" * 10 + "x" * 2) is None
    store.clear_pending()
    assert store.pending(token) is None
    with pytest.raises(ValueError):
        ReviewStore(tmp_path, "../escape")


# -- save ------------------------------------------------------------------------------------------


def test_save_writes_only_the_edited_part_and_detects_conflicts(
    vault: Path, tmp_path: Path
) -> None:
    path = vault / "Meetings" / "2026" / NOTE
    text = read_text(path)
    store = ReviewStore(tmp_path / "data", MM3_ID)
    sha = store.put_base(text)
    doc = split_document(text)
    edits = edits_of(doc)
    texts = list(edits.texts)
    texts[2] = texts[2] + "My own line between sections.\n"
    result = save_note(
        vault,
        path,
        MM3_ID,
        store,
        base_sha=sha,
        edits=Edits(texts, edits.sections, edits.frontmatter),
    )
    saved = read_text(path)
    assert result.written and result.sha == text_sha(saved)
    assert saved.replace("My own line between sections.\n", "", 1) == text

    # Another program edits the file: saving the old base again is a conflict.
    path.write_text(saved + "\nEdited in Obsidian.\n", encoding="utf-8")
    with pytest.raises(SaveConflict) as exc:
        save_note(vault, path, MM3_ID, store, base_sha=sha, edits=edits)
    assert "Edited in Obsidian." in exc.value.theirs and exc.value.mine == text
    # "Keep mine": overwrite the version the user saw in the diff.
    save_note(vault, path, MM3_ID, store, base_sha=sha, edits=edits, force_sha=exc.value.theirs_sha)
    assert read_text(path) == text


def test_save_refuses_a_changed_mm3_id(vault: Path, tmp_path: Path) -> None:
    path = vault / "Meetings" / "2026" / NOTE
    text = read_text(path)
    store = ReviewStore(tmp_path, MM3_ID)
    sha = store.put_base(text)
    edits = edits_of(split_document(text))
    fm = (edits.frontmatter or "").replace(MM3_ID, str(uuid.uuid4()))
    with pytest.raises(MM3Error) as exc:
        save_note(vault, path, MM3_ID, store, base_sha=sha, edits=Edits(edits.texts, {}, fm))
    assert exc.value.code == "E_NOTE_ID_CHANGED"
    no_id = (edits.frontmatter or "").replace(f"mm3-id: {MM3_ID}\n", "")
    with pytest.raises(MM3Error) as exc:
        save_note(vault, path, MM3_ID, store, base_sha=sha, edits=Edits(edits.texts, {}, no_id))
    assert exc.value.code == "not_an_mm3_note"
    with pytest.raises(MM3Error) as exc:
        save_note(vault, path, MM3_ID, store, base_sha="0" * 64, edits=edits)
    assert exc.value.code == "E_BASE_GONE"
    assert read_text(path) == text


# -- rename ----------------------------------------------------------------------------------------


def test_replace_names_is_whole_word_and_simultaneous() -> None:
    text = "Alice thanked Bob. Speaker 1 and Speaker 10 spoke. Alicea is someone else."
    out, n = replace_names(text, {"Alice": "Bob", "Bob": "Alice", "Speaker 1": "Carol"})
    assert out == "Bob thanked Alice. Carol and Speaker 10 spoke. Alicea is someone else."
    assert n == 3
    assert replace_names("x", {}) == ("x", 0)


def test_rename_plan_updates_names_but_not_user_text(vault: Path) -> None:
    folder = vault / "Meetings" / "2026"
    text = read_text(folder / NOTE).replace(
        "<!-- mm3:section:summary -->",
        "Alice Chen wrote this herself.\n\n<!-- mm3:section:summary -->",
    )
    companion_text = read_text(folder / COMPANION)
    plan = plan_rename(
        text, parse_transcript(companion_text), companion_text, {"SPEAKER_00": "Alice Wong"}
    )
    assert [(c.label, c.old, c.new) for c in plan.changes] == [
        ("SPEAKER_00", "Alice Chen", "Alice Wong")
    ]
    meta = parse_note(plan.note_text).note.meta
    assert meta.speakers.names["SPEAKER_00"] == "Alice Wong"
    assert meta.participants[0] == "Alice Wong" and "Charlie Diaz" in meta.participants
    assert "Alice Chen wrote this herself." in plan.note_text  # outside markers: untouched
    assert "- **Participants:** Alice Wong, Bob Okafor, Charlie Diaz" in plan.note_text
    assert plan.header_updated
    assert plan.section_hits and "(Alice Wong)" in plan.note_text
    assert "Alice Wong:**" in plan.companion_text and "Alice Chen:**" not in plan.companion_text
    with pytest.raises(MM3Error):
        plan_rename(text, parse_transcript(companion_text), companion_text, {"SPEAKER_99": "X"})
    with pytest.raises(MM3Error):
        plan_rename(text, parse_transcript(companion_text), companion_text, {"SPEAKER_00": "[[x]]"})


def test_rename_leaves_an_edited_header_line_alone(vault: Path) -> None:
    folder = vault / "Meetings" / "2026"
    text = read_text(folder / NOTE).replace(
        "- **Participants:** Alice Chen, Bob Okafor, Charlie Diaz",
        "- **Participants:** Alice, Bob and Charlie (edited)",
    )
    companion_text = read_text(folder / COMPANION)
    plan = plan_rename(
        text, parse_transcript(companion_text), companion_text, {"SPEAKER_01": "Robert Okafor"}
    )
    assert not plan.header_updated
    assert "- **Participants:** Alice, Bob and Charlie (edited)" in plan.note_text


def test_transcript_view_groups_turns_with_colours(vault: Path) -> None:
    doc = parse_transcript(read_text(vault / "Meetings" / "2026" / COMPANION)).doc
    view = transcript_view(doc)
    assert view.segment_count == len(doc.transcript.segments)
    assert [s.label for s in view.speakers] == doc.transcript.speaker_labels
    assert {t.colour for t in view.turns} <= {0, 1, 2}
    assert all(t.segments for t in view.turns)
    assert view.turns[0].name == "Alice Chen"


# -- switch template -------------------------------------------------------------------------------


def test_preserved_text_drops_mm3_header_and_keeps_user_text(vault: Path) -> None:
    text = read_text(vault / "Meetings" / "2026" / NOTE)
    assert preserved_text(parse_note(text).note) == ""
    edited = (
        text.replace(
            "<!-- mm3:section:decisions -->", "A thought of mine.\n\n<!-- mm3:section:decisions -->"
        )
        + "\nTrailing remark.\n"
    )
    out = preserved_text(parse_note(edited).note)
    assert out == "A thought of mine.\n\nTrailing remark."
    again = preserved_text(parse_note(edited + f"\n{PRESERVED_HEADING}\n\nOld kept.\n").note)
    assert PRESERVED_HEADING not in again and "Old kept." in again


def test_switch_template_regenerates_and_preserves(vault: Path) -> None:
    path = vault / "Meetings" / "2026" / NOTE
    text = read_text(path).replace(
        "<!-- mm3:section:decisions -->", "A thought of mine.\n\n<!-- mm3:section:decisions -->"
    )
    settings = Settings()
    settings.vault.path = vault
    library = load_library(vault, "MeetingMaster3/templates")
    result = asyncio.run(
        switch_template(
            settings,
            library,
            lambda name: FakeLLMBackend(id=name),
            path=path,
            text=text,
            template_id="decision-log",
        )
    )
    parsed = parse_note(result.text)
    assert parsed.ok and parsed.note.meta.template_id == "decision-log"
    assert parsed.note.meta.id == uuid.UUID(MM3_ID)
    assert parsed.note.meta.transcript_ref == "2026-10-11 - Product Sync.transcript"
    assert parsed.note.extra_properties == {"aliases": ["Product Sync"]}
    assert result.preserved and result.text.endswith(f"{PRESERVED_HEADING}\n\nA thought of mine.\n")
    assert [s.id for s in parsed.note.sections][-1] == "ai-recommendations"
    with pytest.raises(MM3Error):
        asyncio.run(
            switch_template(
                settings,
                library,
                lambda n: FakeLLMBackend(id=n),
                path=path,
                text=text,
                template_id="no-such-template",
            )
        )
