"""The synthetic meeting corpus for the search tests (Phase 15i), written to
``tests/fixtures/search_vault/``.

Seven invented meetings. One topic, money spent beyond the plan, comes up in three of them in
different words: "budget overrun" (Q3 Finance Review), "spending more than planned" (Platform
Weekly) and "costs exceeded the forecast" (Vendor Contract Sync, said in the transcript). The
other four are about hiring, a release, an outage and design. The Hiring Plan's AI
Recommendations mention the budget, which must not count: that section is not indexed.

Regenerate with ``MM3_UPDATE_GOLDEN=1 uv run pytest tests/unit/search/test_corpus.py`` and
review the diff. People and companies are invented; CC0.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from pathlib import Path

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Section
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.markdown.note_writer import build_note, render_note
from meetingmaster3.markdown.transcript_format import build_companion, render_transcript

FOLDER = Path(__file__).resolve().parent / "fixtures" / "search_vault"
MEETINGS_DIR = "Meetings/2026"


@dataclass(frozen=True)
class Meeting:
    key: str
    id: uuid.UUID
    title: str
    date: dt.datetime
    speakers: dict[str, str]
    """Label → name."""
    participants: tuple[str, ...]
    sections: tuple[tuple[str, str, str], ...]
    """``(id, title, body)``."""
    lines: tuple[tuple[str, str], ...]
    """``(label, text)``, about 8 s each."""

    @property
    def stem(self) -> str:
        return f"{self.date:%Y-%m-%d} - {self.title}"


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-4000-8000-{n:012d}")


MEETINGS: tuple[Meeting, ...] = (
    Meeting(
        key="finance",
        id=_id(1),
        title="Q3 Finance Review",
        date=dt.datetime(2026, 9, 2, 10, 0),
        speakers={"SPEAKER_00": "Dana Whitfield", "SPEAKER_01": "Raj Patel"},
        participants=("Dana Whitfield", "Raj Patel", "Mei Lin"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "Dana Whitfield reported a budget overrun of 12 percent for the third quarter, "
                "driven by contractor fees.",
            ),
            (
                "discussion",
                "Discussion",
                "- The marketing budget overrun is the largest item [00:01:10].\n"
                "- Raj Patel asked for a weekly variance report until the end of the year.",
            ),
            (
                "action-items",
                "Action Items",
                "- [ ] **Raj Patel:** send the variance report every Friday. Due: not stated",
            ),
        ),
        lines=(
            ("SPEAKER_00", "We are twelve percent over budget this quarter."),
            ("SPEAKER_00", "Most of the budget overrun is contractor fees in marketing."),
            ("SPEAKER_01", "Then I want a variance report every Friday."),
        ),
    ),
    Meeting(
        key="hiring",
        id=_id(2),
        title="Hiring Plan",
        date=dt.datetime(2026, 9, 4, 14, 0),
        speakers={"SPEAKER_00": "Sofia Alvarez", "SPEAKER_01": "Tom Becker"},
        participants=("Sofia Alvarez", "Tom Becker"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "The team agreed to recruit two backend engineers and one designer before "
                "December.",
            ),
            (
                "discussion",
                "Discussion",
                "- Sofia Alvarez will screen candidates from the referral list first.\n"
                "- Tom Becker wants a take-home exercise of at most two hours.",
            ),
            (
                "ai-recommendations",
                "AI Recommendations",
                "- Check the budget overrun risk of the new headcount with finance.",
            ),
        ),
        lines=(
            ("SPEAKER_00", "We need two backend engineers and a designer by December."),
            ("SPEAKER_01", "Keep the exercise under two hours or good candidates drop out."),
        ),
    ),
    Meeting(
        key="platform",
        id=_id(3),
        title="Platform Weekly",
        date=dt.datetime(2026, 9, 9, 9, 30),
        speakers={"SPEAKER_00": "Raj Patel", "SPEAKER_01": "Tom Becker"},
        participants=("Raj Patel", "Tom Becker"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "Hosting is spending more than planned because the staging cluster runs all night.",
            ),
            (
                "discussion",
                "Discussion",
                "- Tom Becker showed that the staging cluster costs almost as much as production "
                "[00:00:16].\n"
                "- Raj Patel proposed shutting staging down outside office hours.",
            ),
            (
                "decisions",
                "Decisions Made",
                "- **Staging scales to zero at night from next Monday.** (Raj Patel)",
            ),
        ),
        lines=(
            ("SPEAKER_01", "Our hosting bill is way above what we planned for September."),
            ("SPEAKER_01", "Staging alone is almost as expensive as production."),
            ("SPEAKER_00", "Then staging scales to zero at night, starting Monday."),
        ),
    ),
    Meeting(
        key="release",
        id=_id(4),
        title="Release Planning",
        date=dt.datetime(2026, 9, 11, 11, 0),
        speakers={"SPEAKER_00": "Mei Lin", "SPEAKER_01": "Sofia Alvarez"},
        participants=("Mei Lin", "Sofia Alvarez"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "The mobile app version 3.2 launch moves to October 6 so the store review "
                "can finish.",
            ),
            (
                "discussion",
                "Discussion",
                "- Mei Lin owns the release checklist.\n"
                "- Sofia Alvarez will prepare the store screenshots.",
            ),
        ),
        lines=(
            ("SPEAKER_00", "The store review takes a week, so we ship on October sixth."),
            ("SPEAKER_01", "I will have the screenshots ready by Friday."),
        ),
    ),
    Meeting(
        key="vendor",
        id=_id(5),
        title="Vendor Contract Sync",
        date=dt.datetime(2026, 9, 16, 15, 0),
        speakers={"SPEAKER_00": "Mei Lin", "SPEAKER_01": "Dana Whitfield"},
        participants=("Mei Lin", "Dana Whitfield"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "The analytics vendor invoices came in higher than agreed; the contract is to "
                "be renegotiated in November.",
            ),
            (
                "discussion",
                "Discussion",
                "- Dana Whitfield wants usage caps written into the new contract.\n"
                "- Mei Lin will collect the last six invoices.",
            ),
        ),
        lines=(
            ("SPEAKER_01", "The vendor costs exceeded the forecast for the third month running."),
            ("SPEAKER_01", "I want usage caps in the next contract."),
            ("SPEAKER_00", "I will pull the last six invoices together."),
        ),
    ),
    Meeting(
        key="incident",
        id=_id(6),
        title="Incident Retro",
        date=dt.datetime(2026, 9, 18, 16, 0),
        speakers={"SPEAKER_00": "Tom Becker", "SPEAKER_01": "Raj Patel"},
        participants=("Tom Becker", "Raj Patel"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "The login outage on September 17 lasted 40 minutes; an expired certificate "
                "was the cause.",
            ),
            (
                "discussion",
                "Discussion",
                "- Tom Becker will add certificate expiry alerts.\n"
                "- Raj Patel asked for a status page update template.",
            ),
        ),
        lines=(
            ("SPEAKER_00", "The certificate expired at two in the morning and nobody was paged."),
            ("SPEAKER_01", "We need an alert thirty days before expiry."),
        ),
    ),
    Meeting(
        key="design",
        id=_id(7),
        title="Design Crit",
        date=dt.datetime(2026, 9, 23, 13, 0),
        speakers={"SPEAKER_00": "Sofia Alvarez", "SPEAKER_01": "Mei Lin"},
        participants=("Sofia Alvarez", "Mei Lin"),
        sections=(
            (
                "summary",
                "Summary Succinct",
                "The new onboarding screens were reviewed; the typography needs more contrast.",
            ),
            (
                "discussion",
                "Discussion",
                "- Mei Lin suggested a larger body font.\n"
                "- Sofia Alvarez will test the screens with three users.",
            ),
        ),
        lines=(
            ("SPEAKER_00", "The grey text is hard to read on the welcome screen."),
            ("SPEAKER_01", "Let's try sixteen point body text."),
        ),
    ),
)

TOPIC = ("finance", "platform", "vendor")
"""The meetings about money spent beyond the plan."""


def note_text(m: Meeting) -> str:
    meta = MeetingMeta(
        id=m.id,
        title=m.title,
        date=m.date,
        participants=list(m.participants),
        tags=["meeting"],
        template_id="default-notes",
        backend="ollama",
        model="qwen3:8b",
        generated_at=m.date + dt.timedelta(hours=1),
        transcript_ref=f"{m.stem}.transcript",
        speakers=SpeakerMap(names=m.speakers),
    )
    sections = [Section(id=i, title=t, body_markdown=b) for i, t, b in m.sections]
    return render_note(build_note(meta, sections))


def transcript_text(m: Meeting) -> str:
    segments = [
        Segment(id=i, start=i * 8.0, end=i * 8.0 + 7.5, speaker_label=label, text=f" {text}")
        for i, (label, text) in enumerate(m.lines)
    ]
    t = Transcript(
        segments=segments,
        language="en",
        duration=len(m.lines) * 8.0,
        model="large-v3-turbo",
        diarized=True,
    )
    companion = build_companion(m.id, m.title, t, SpeakerMap(names=m.speakers), note_ref=m.stem)
    return render_transcript(companion)


def files() -> dict[str, str]:
    """Vault-relative path → text, for every file of the corpus."""
    out = {}
    for m in MEETINGS:
        out[f"{MEETINGS_DIR}/{m.stem}.md"] = note_text(m)
        out[f"{MEETINGS_DIR}/{m.stem}.transcript.md"] = transcript_text(m)
    return out


def write_vault(root: Path) -> Path:
    """Write the corpus into a new vault at ``root`` (with ``.obsidian/``)."""
    (root / ".obsidian").mkdir(parents=True, exist_ok=True)
    for rel, text in files().items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    return root


def by_key(key: str) -> Meeting:
    return next(m for m in MEETINGS if m.key == key)
