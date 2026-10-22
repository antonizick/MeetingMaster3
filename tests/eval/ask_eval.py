"""Evaluate the Ask AI agent on the synthetic corpus (``tests/ask_corpus.py``) with a real model.

    uv run python -m tests.eval.ask_eval --model qwen3:8b
    uv run python -m tests.eval.ask_eval --model qwen3:8b --questions overspend,none --json r.json
    uv run python -m tests.eval.ask_eval --backend bedrock --cloud \\
        --model us.anthropic.claude-haiku-5-5 --price-in 1 --price-out 5 --json bedrock.json

The corpus is written to a temporary vault and indexed with the configured search embedder
(default: the local Ollama ``nomic-embed-text``; ``--fake-embed`` uses the offline toy vectors).
Each question is scored on: recall and precision of the meetings found relevant against the
expected set, whether the count is right, whether every table row matches the files (date and
attendees), whether the expected people are named as taking part (and their roles where the
corpus states them), and whether every ``[[link]]`` in the answer is one of the meetings in the
table. With a local backend nothing leaves this computer; a cloud backend receives excerpts of the
synthetic meetings and is refused unless ``--cloud`` gives consent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from meetingmaster3.ask.pipeline import AskResult
from meetingmaster3.ask.service import AskService
from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings, load_settings
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.search.service import SearchService
from meetingmaster3.storage.db import Database
from tests import ask_corpus as ac

_LINK_RE = re.compile(r"\[\[([^\[\]|#\n]+)")


@dataclass
class QuestionScore:
    key: str
    expected: list[str]
    found: list[str]
    recall: float
    precision: float
    count_ok: bool
    rows_ok: bool
    people_ok: bool
    roles_ok: float | None
    links_ok: bool
    removed_links: int
    seconds: float
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    meetings_read: int
    follow_up: bool
    answer: str = ""
    relevance: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def score(q: ac.Question, result: AskResult, price: tuple[float, float] | None) -> QuestionScore:
    key_of = {str(m.id): m.key for m in ac.MEETINGS}
    found = [key_of.get(r.mm3_id, r.mm3_id) for r in result.rows]
    depth: dict[str, str] = {key_of.get(r.mm3_id, r.mm3_id): r.relevance for r in result.rows}
    expected = set(q.meetings)
    hit = expected & set(found)
    recall = len(hit) / len(expected) if expected else 1.0
    precision = len(hit) / len(found) if found else (1.0 if not expected else 0.0)
    notes: list[str] = []
    rows_ok = True
    for row in result.rows:
        m = next((m for m in ac.MEETINGS if str(m.id) == row.mm3_id), None)
        if m is None:
            rows_ok = False
            continue
        attendees = list(dict.fromkeys([*m.participants, *m.speakers.values()]))
        if row.date != f"{m.date:%Y-%m-%d}" or list(row.attendees) != attendees:
            rows_ok = False
            notes.append(f"row {m.key}: {row.date} {row.attendees} != {attendees}")
    spoke = {name for row in result.rows for name in row.spoke}
    missing = [p for p in q.people if p not in spoke]
    if missing:
        notes.append(f"not named as taking part: {', '.join(missing)}")
    roles = {
        name: role
        for row in result.rows
        if key_of.get(row.mm3_id) in ac.STATED_ROLES
        for name, role in row.roles
    }
    checked = [p for p in q.people if p in ac.ROLES and p in roles]
    roles_ok = (
        sum(1 for p in checked if ac.ROLES[p].casefold() in roles[p].casefold()) / len(checked)
        if checked
        else None
    )
    stems = {r.stem for r in result.rows}
    links = [t.strip() for t in _LINK_RE.findall(result.answer)]
    bad = [t for t in links if t not in stems]
    if bad:
        notes.append(f"links outside the table: {bad}")
    t = result.trace
    cost = None
    if price is not None:
        cost = (t.input_tokens * price[0] + t.output_tokens * price[1]) / 1_000_000
    return QuestionScore(
        key=q.key,
        expected=sorted(expected),
        found=found,
        recall=round(recall, 3),
        precision=round(precision, 3),
        count_ok=result.count == len(expected),
        rows_ok=rows_ok,
        people_ok=not missing,
        roles_ok=None if roles_ok is None else round(roles_ok, 3),
        links_ok=not bad,
        removed_links=len(t.stripped),
        seconds=round(t.seconds, 1),
        calls=t.calls,
        input_tokens=t.input_tokens,
        output_tokens=t.output_tokens,
        cost_usd=None if cost is None else round(cost, 5),
        meetings_read=t.read,
        follow_up=t.follow_up,
        answer=result.answer,
        relevance=depth,
        notes=notes,
    )


def found_text(s: QuestionScore) -> str:
    return ", ".join(f"{k} ({s.relevance.get(k, '?')})" for k in s.found) or "none"


async def run(args: argparse.Namespace) -> list[QuestionScore]:
    settings: Settings = load_settings()
    work = Path(tempfile.mkdtemp(prefix="mm3-ask-eval-"))
    vault = ac.write_vault(work / "vault")
    settings.vault.path = vault
    settings.search.enabled = True
    settings.ask.max_meetings = args.max_meetings
    paths = AppPaths(config_dir=work / "config", data_dir=work / "data", cache_dir=work / "cache")
    paths.ensure()
    registry = BackendRegistry(settings)
    embed_lookup = registry.get
    if args.fake_embed:
        fake = FakeLLMBackend(id="ollama", kind="ollama")

        def embed_lookup(name: str | None = None) -> Any:
            return fake

    search = SearchService(settings, paths, registry.names, embed_lookup)
    db = Database.open(paths.database)
    ask = AskService(settings, db, search, registry.get, registry.names)
    price = (args.price_in, args.price_out) if args.price_in is not None else None
    scores: list[QuestionScore] = []
    try:
        started = time.monotonic()
        report = await search.update_now()
        print(
            f"Indexed {len(ac.MEETINGS)} meetings in {time.monotonic() - started:.1f} s "
            f"({report.embedded if report else 0} passages embedded)",
            file=sys.stderr,
        )
        wanted = set(args.questions.split(",")) if args.questions else None
        for q in ac.QUESTIONS:
            if wanted and q.key not in wanted:
                continue
            print(f"\n== {q.key}: {q.text}", file=sys.stderr)
            result, _ = await ask.ask(
                q.text,
                backend=args.backend,
                model=args.model,
                cloud_consent=args.cloud,
                save=False,
                progress=lambda f, m: print(f"   {m}", file=sys.stderr) if args.verbose else None,
            )
            s = score(q, result, price)
            scores.append(s)
            print(
                f"   found {found_text(s)} (expected {s.expected}) recall {s.recall} precision "
                f"{s.precision} count {'ok' if s.count_ok else 'WRONG'} rows "
                f"{'ok' if s.rows_ok else 'WRONG'} people {'ok' if s.people_ok else 'missing'} "
                f"roles {s.roles_ok} links {'ok' if s.links_ok else 'BAD'} · {s.seconds} s, "
                f"{s.calls} calls" + (f", USD {s.cost_usd}" if s.cost_usd is not None else ""),
                file=sys.stderr,
            )
            for note in s.notes:
                print(f"   - {note}", file=sys.stderr)
    finally:
        await search.stop()
        db.close()
    return scores


def summary(scores: list[QuestionScore]) -> dict[str, Any]:
    n = len(scores) or 1
    return {
        "questions": len(scores),
        "recall": round(sum(s.recall for s in scores) / n, 3),
        "precision": round(sum(s.precision for s in scores) / n, 3),
        "count_ok": sum(s.count_ok for s in scores),
        "rows_ok": sum(s.rows_ok for s in scores),
        "people_ok": sum(s.people_ok for s in scores),
        "links_ok": sum(s.links_ok for s in scores),
        "seconds_mean": round(sum(s.seconds for s in scores) / n, 1),
        "meetings_read_mean": round(sum(s.meetings_read for s in scores) / n, 1),
        "cost_usd": round(sum(s.cost_usd or 0 for s in scores), 4),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--backend", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--cloud", action="store_true", help="consent to a cloud backend")
    p.add_argument("--questions", default="", help="comma-separated question keys")
    p.add_argument("--max-meetings", type=int, default=25)
    p.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens")
    p.add_argument("--price-out", type=float, default=None, help="USD per 1M output tokens")
    p.add_argument("--fake-embed", action="store_true", help="offline toy vectors for search")
    p.add_argument("--json", type=Path, default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    scores = asyncio.run(run(args))
    total = summary(scores)
    print(json.dumps(total, indent=2))
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "backend": args.backend,
                    "model": args.model,
                    "summary": total,
                    "questions": [asdict(s) for s in scores],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
