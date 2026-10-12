"""Summary Succinct + Summary Detailed (Phase 15a, R25): templates, paragraph floor, upgrades."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from meetingmaster3.llm.base import GenerateRequest
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.templates.loader import (
    builtin_dir,
    ensure_installed,
    install_builtins,
    load_library,
    newer_builtins,
)
from meetingmaster3.templates.postprocess import count_paragraphs
from tests.unit.templates.builtin_ids import BUILTIN_IDS
from tests.unit.templates.test_generator import generator, meta, transcript

SUB = "MeetingMaster3/templates/"
DETAILED = "Summary Detailed"


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
def test_every_builtin_has_both_summaries(template_id: str) -> None:
    t = load_library().get(template_id)
    ids = [s.id for s in t.sections]
    i = ids.index("summary")
    assert ids[i + 1] == "summary-detailed"
    assert t.sections[i].title == "Summary Succinct"
    assert t.sections[i + 1].title == DETAILED and t.sections[i + 1].kind == "narrative"
    assert t.max_tokens(t.sections[i + 1]) >= 1200
    prompt = t.prompts["summary-detailed"]
    assert "never fewer than two" in prompt and "No bullet points" in prompt
    expected_first = 1 if template_id == "board-governance-minutes" else 0
    assert i == expected_first  # board minutes: after Attendance & Quorum


@pytest.mark.parametrize(
    ("body", "n"),
    [
        ("One paragraph only.", 1),
        ("First.\n\nSecond.", 2),
        ("First.\n\nSecond.\n\nThird.", 3),
        ("First.\r\n\r\nSecond.", 2),
        ("First line\nsame paragraph.", 1),
        ("- a bullet\n- another", 0),
        ("Intro.\n\n- a\n- b\n\nOutro.", 2),
        ("## Heading\n\nText.", 1),
        ("_Nothing to report._", 0),
        ("", 0),
        ("First.\n   \nSecond.", 2),
    ],
)
def test_count_paragraphs(body: str, n: int) -> None:
    assert count_paragraphs(body) == n


def _responder(detailed: list[str]) -> object:
    answers = iter(detailed)

    def respond(req: GenerateRequest) -> str:
        if f'Now write the section "{DETAILED}"' in req.messages[0].content:
            return next(answers)
        return "Fine."

    return respond


async def test_short_detailed_summary_is_retried_with_a_firmer_instruction() -> None:
    backend = FakeLLMBackend(responder=_responder(["Too short.", "Context.\n\nThreads.\n\nEnd."]))  # type: ignore[arg-type]
    warnings: list[str] = []
    result = await generator(backend, warn=warnings.append).generate(meta(), transcript())
    detailed = next(s for s in result.sections if s.id == "summary-detailed")
    assert detailed.body_markdown == "Context.\n\nThreads.\n\nEnd."
    retry = [c for c in backend.calls if len(c.messages) == 3]
    assert len(retry) == 1
    assert retry[0].messages[1].content == "Too short."
    assert "at least two paragraphs" in retry[0].messages[2].content
    assert warnings == []


async def test_still_short_after_the_retry_is_kept_and_warned() -> None:
    backend = FakeLLMBackend(responder=_responder(["Short.", "Still one paragraph, longer."]))  # type: ignore[arg-type]
    warnings: list[str] = []
    result = await generator(backend, warn=warnings.append).generate(meta(), transcript())
    detailed = next(s for s in result.sections if s.id == "summary-detailed")
    assert detailed.body_markdown in ("Short.", "Still one paragraph, longer.")
    assert "\n\n" not in detailed.body_markdown  # never padded
    assert len(warnings) == 1 and "fewer than 2 paragraphs" in warnings[0]


async def test_two_paragraphs_need_no_retry() -> None:
    backend = FakeLLMBackend(responder=_responder(["One.\n\nTwo."]))  # type: ignore[arg-type]
    await generator(backend).generate(meta(), transcript())
    assert all(len(c.messages) == 1 for c in backend.calls)


async def test_the_floor_applies_to_regeneration_too() -> None:
    backend = FakeLLMBackend(responder=_responder(["Short.", "A.\n\nB."]))  # type: ignore[arg-type]
    body = await generator(backend).regenerate_section(meta(), transcript(), "summary-detailed")
    assert body == "A.\n\nB."


async def test_offline_fake_model_meets_the_floor() -> None:
    warnings: list[str] = []
    result = await generator(FakeLLMBackend(), warn=warnings.append).generate(meta(), transcript())
    detailed = next(s for s in result.sections if s.id == "summary-detailed")
    assert count_paragraphs(detailed.body_markdown) >= 2 and warnings == []


# -- upgrading vault copies of the built-ins ----------------------------------------------------


def _install_old_version(vault: Path, manifest: Path, name: str) -> str:
    """Make the vault copy of ``name`` look like an older shipped version MM3 installed."""
    target = vault / SUB / name
    old = (
        target.read_text("utf-8")
        .replace("Summary Succinct", "Summary")
        .split("<!-- mm3:prompt:summary-detailed -->")[0]
    )
    target.write_text(old, encoding="utf-8")
    data = json.loads(manifest.read_text("utf-8"))
    data["files"][name] = hashlib.sha256(old.encode()).hexdigest()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return old


def test_startup_upgrades_unchanged_copies_and_keeps_edited_ones(
    vault: Path, tmp_path: Path
) -> None:
    manifest = tmp_path / "m.json"
    install_builtins(vault, SUB, manifest)
    _install_old_version(vault, manifest, "executive-summary.md")
    edited_old = _install_old_version(vault, manifest, "decision-log.md")
    edited = vault / SUB / "decision-log.md"
    edited.write_text(edited_old + "\n<!-- my tweak -->\n", encoding="utf-8")
    (vault / SUB / "retrospective.md").unlink()  # deleted by the user

    assert newer_builtins(vault, SUB, manifest) == {"decision-log.md"}
    assert ensure_installed(vault, SUB, manifest) is True  # the app starts
    shipped = (builtin_dir() / "executive-summary.md").read_text("utf-8")
    assert (vault / SUB / "executive-summary.md").read_text("utf-8") == shipped
    assert edited.read_text("utf-8").endswith("<!-- my tweak -->\n")  # the user's edit wins
    assert not (vault / SUB / "retrospective.md").exists()  # not brought back
    assert newer_builtins(vault, SUB, manifest) == {"decision-log.md"}
    assert ensure_installed(vault, SUB, manifest) is False  # nothing more to do


def test_library_page_shows_a_newer_builtin(ui: object, vault: Path, app_settings: object) -> None:
    from fastapi.testclient import TestClient

    from meetingmaster3.templates.loader import MANIFEST_NAME

    assert isinstance(ui, TestClient)
    manifest = ui.app.state.paths.data_dir / MANIFEST_NAME  # type: ignore[attr-defined]
    install_builtins(vault, SUB, manifest)
    page = ui.get("/templates").text
    assert "A newer version of this built-in is available" not in page
    old = _install_old_version(vault, manifest, "decision-log.md")
    (vault / SUB / "decision-log.md").write_text(old + "\n<!-- edit -->\n", encoding="utf-8")
    page = ui.get("/templates").text
    assert page.count("A newer version of this built-in is available") == 1
