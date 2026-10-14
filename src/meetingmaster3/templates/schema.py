"""Template files: schema, parser and validation (normative: ``docs/dev-guide/template-format.md``).

:func:`parse_template` never raises for a bad file. It returns a :class:`TemplateReport` with
line-numbered :class:`TemplateIssue` items, so the library can list invalid templates next to
valid ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from meetingmaster3.domain.note import AI_RECOMMENDATIONS_ID, SECTION_ID_RE
from meetingmaster3.markdown.frontmatter import compose_untrusted, load_untrusted

SCHEMA_VERSION = 1
SYSTEM_PROMPT_ID = "_system"
MAX_TEMPLATE_BYTES = 256 * 1024
DEFAULT_TEMPERATURES = {"extraction": 0.2, "narrative": 0.4}
"""R6: factual extraction runs cooler than narrative prose."""

PROMPT_MARKER_RE = re.compile(r"^[ \t]*<!--[ \t]*mm3:prompt:(?P<id>[^\s>]+)[ \t]*-->[ \t]*\r?$")
LOOSE_PROMPT_RE = re.compile(r"^[ \t]*<!--.*mm3[ \t]*:[ \t]*prompt", re.I)
_FENCE_RE = re.compile(r"^---[ \t]*\r?$")

SectionKind = Literal["narrative", "extraction"]
SectionFormat = Literal["markdown", "tasks", "bullets"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TemplateSection(_Model):
    id: str
    title: str = Field(min_length=1, max_length=200)
    kind: SectionKind
    format: SectionFormat = "markdown"
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64, le=32_000)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if v == SYSTEM_PROMPT_ID:
            return v  # reported as reserved_section_id with its line
        if not SECTION_ID_RE.match(v):
            raise ValueError("use lowercase letters, digits and hyphens (at most 64)")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return " ".join(v.split())


class TemplateParams(_Model):
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens_per_section: int = Field(default=800, ge=64, le=32_000)
    ai_recommendations: bool = True
    detail: Literal["standard", "high"] = "standard"
    """How much of a long meeting the map-reduce notes keep (ADR-0039). ``high`` keeps about three
    times as many points per part, with their figures and names and a topic label, for
    templates that write dense, topic-by-topic notes; it costs a longer map step."""


class _Frontmatter(BaseModel):
    """What the YAML must contain. Unknown keys are allowed (reported as warnings)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: int = Field(alias="mm3-template")
    id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    sections: list[TemplateSection] = Field(min_length=1)
    params: TemplateParams = Field(default_factory=TemplateParams)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not SECTION_ID_RE.match(v):
            raise ValueError("use lowercase letters, digits and hyphens (at most 64)")
        return v

    @field_validator("description", mode="before")
    @classmethod
    def _none_is_empty(cls, v: Any) -> Any:
        return "" if v is None else v


KNOWN_KEYS = frozenset(
    {"mm3-template", "id", "name", "description", "tags", "favorite", "sections", "params"}
)


class Template(_Model):
    """A valid template."""

    id: str
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    favorite: bool = False
    sections: tuple[TemplateSection, ...]
    params: TemplateParams = Field(default_factory=TemplateParams)
    system_prompt: str
    prompts: dict[str, str]
    """Section id → prompt block text."""

    def section(self, section_id: str) -> TemplateSection | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def temperature(self, section: TemplateSection) -> float:
        if section.temperature is not None:
            return section.temperature
        if self.params.temperature is not None:
            return self.params.temperature
        return DEFAULT_TEMPERATURES[section.kind]

    def max_tokens(self, section: TemplateSection) -> int:
        return section.max_tokens or self.params.max_tokens_per_section


@dataclass(frozen=True)
class TemplateIssue:
    code: str
    message: str
    line: int = 0  # 1-based; 0 = the whole file
    severity: Literal["error", "warning"] = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "severity": self.severity,
        }

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{where}{self.message} [{self.code}]"


@dataclass
class TemplateReport:
    """The result of parsing one template file."""

    template: Template | None
    issues: list[TemplateIssue] = field(default_factory=list)
    template_id: str | None = None
    """The declared id, when it could be read (also for invalid templates)."""
    name: str | None = None

    @property
    def errors(self) -> list[TemplateIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[TemplateIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return self.template is not None and not self.errors


# -- YAML line lookup -------------------------------------------------------------------------


def _node_lines(node: yaml.Node, path: tuple[Any, ...], out: dict[tuple[Any, ...], int]) -> None:
    out[path] = node.start_mark.line
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            k = key.value if isinstance(key, yaml.ScalarNode) else None
            out[(*path, k)] = key.start_mark.line
            _node_lines(value, (*path, k, "__value__"), out)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            _node_lines(item, (*path, i), out)


def _line_for(lines: dict[tuple[Any, ...], int], loc: tuple[Any, ...]) -> int | None:
    """The 0-based YAML line of the deepest node on ``loc`` (a pydantic error location)."""
    path: tuple[Any, ...] = ()
    best: int | None = lines.get(())
    for part in loc:
        candidate = (*path, part)
        if candidate in lines:  # a mapping key
            best = lines[candidate]
            path = (*candidate, "__value__")
        elif isinstance(part, int) and (*path, part) in lines:
            path = (*path, part)
            best = lines[path]
        else:
            break
    return best


# -- parsing ----------------------------------------------------------------------------------


def _err(code: str, message: str, line: int = 0) -> TemplateIssue:
    return TemplateIssue(code, message, line)


def _split(text: str) -> tuple[list[str], int, int] | TemplateIssue:
    """Lines plus the indexes of the opening and closing ``---``."""
    lines = text.split("\n")
    if not lines or not _FENCE_RE.match(lines[0].lstrip("﻿")):
        return _err("no_frontmatter", "A template must start with a '---' frontmatter block.", 1)
    for i in range(1, len(lines)):
        if _FENCE_RE.match(lines[i]):
            return lines, 0, i
    return _err("frontmatter_unclosed", "The frontmatter has no closing '---' line.", 1)


def _prompt_blocks(
    lines: list[str], first: int, issues: list[TemplateIssue]
) -> dict[str, tuple[str, int]]:
    """Prompt id → (text, 1-based marker line), for the body starting at index ``first``."""
    blocks: dict[str, tuple[str, int]] = {}
    current: str | None = None
    current_line = 0
    buf: list[str] = []

    def flush() -> None:
        if current is None:
            return
        body = "\n".join(buf).replace("\r", "").strip()
        if current in blocks:
            issues.append(
                _err("duplicate_prompt", f"A second prompt block for '{current}'.", current_line)
            )
            return
        if not body:
            issues.append(
                _err("empty_prompt", f"The prompt for '{current}' is empty.", current_line)
            )
        blocks[current] = (body, current_line)

    for i in range(first, len(lines)):
        line = lines[i]
        m = PROMPT_MARKER_RE.match(line)
        if m:
            flush()
            current, current_line, buf = m.group("id"), i + 1, []
            continue
        if LOOSE_PROMPT_RE.match(line):
            issues.append(
                _err(
                    "malformed_prompt_marker",
                    "This looks like a prompt marker but is not '<!-- mm3:prompt:<id> -->'.",
                    i + 1,
                )
            )
            continue
        if current is not None:
            buf.append(line)
    flush()
    return blocks


def parse_template(text: str, *, source: str = "") -> TemplateReport:
    """Parse and validate a template file's text."""
    if len(text.encode("utf-8")) > MAX_TEMPLATE_BYTES:
        return TemplateReport(
            None, [_err("file_too_large", f"Templates are limited to {MAX_TEMPLATE_BYTES} bytes.")]
        )
    split = _split(text)
    if isinstance(split, TemplateIssue):
        return TemplateReport(None, [split])
    lines, _, close = split
    yaml_text = "\n".join(lines[1:close])
    offset = 2  # YAML line 0 is file line 2
    issues: list[TemplateIssue] = []
    try:
        node = compose_untrusted(yaml_text)
        data = load_untrusted(yaml_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + offset if mark is not None else 1
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        return TemplateReport(None, [_err("yaml_error", f"Invalid YAML: {problem}.", line)])
    if not isinstance(data, dict) or node is None:
        return TemplateReport(
            None, [_err("schema_error", "The frontmatter must be a set of 'key: value' lines.", 1)]
        )
    node_lines: dict[tuple[Any, ...], int] = {}
    _node_lines(node, (), node_lines)

    def line_of(*loc: Any) -> int:
        found = _line_for(node_lines, loc)
        return found + offset if found is not None else 1

    report = TemplateReport(None)
    if isinstance(data.get("id"), str):
        report.template_id = data["id"]
    if isinstance(data.get("name"), str):
        report.name = data["name"]

    for key in data:
        if key not in KNOWN_KEYS:
            issues.append(
                TemplateIssue(
                    "unknown_key", f"Unknown key '{key}' is ignored.", line_of(key), "warning"
                )
            )
    version = data.get("mm3-template")
    if "mm3-template" in data and version != SCHEMA_VERSION:
        issues.append(
            _err(
                "unsupported_version",
                f"mm3-template: {version!r} is not supported (this app reads version "
                f"{SCHEMA_VERSION}).",
                line_of("mm3-template"),
            )
        )
        report.issues = issues
        return report
    try:
        fm = _Frontmatter.model_validate(data)
    except ValidationError as exc:
        for e in exc.errors():
            loc = tuple(e.get("loc", ()))
            where = ".".join(str(p) for p in loc) or "frontmatter"
            if e.get("type") == "missing":
                message = f"Missing required key '{where}'."
                line = line_of(*loc[:-1]) if len(loc) > 1 else 1
            else:
                message = f"'{where}': {e.get('msg', 'invalid value')}."
                line = line_of(*loc)
            issues.append(_err("schema_error", message, line))
        report.issues = issues
        return report

    sections = fm.sections
    seen: set[str] = set()
    for i, s in enumerate(sections):
        if s.id == SYSTEM_PROMPT_ID:
            issues.append(
                _err(
                    "reserved_section_id",
                    "'_system' is reserved for the template's system prompt.",
                    line_of("sections", i),
                )
            )
        if s.id in seen:
            issues.append(
                _err(
                    "duplicate_section_id",
                    f"Section id '{s.id}' is used twice.",
                    line_of("sections", i),
                )
            )
        seen.add(s.id)
    ids = [s.id for s in sections]
    if fm.params.ai_recommendations:
        if AI_RECOMMENDATIONS_ID not in ids:
            issues.append(
                _err(
                    "ai_recommendations_missing",
                    f"Add an '{AI_RECOMMENDATIONS_ID}' section as the last section, or set "
                    "params.ai_recommendations: false.",
                    line_of("sections"),
                )
            )
        elif ids[-1] != AI_RECOMMENDATIONS_ID:
            issues.append(
                _err(
                    "ai_recommendations_not_last",
                    f"'{AI_RECOMMENDATIONS_ID}' must be the last section (spec §8).",
                    line_of("sections", ids.index(AI_RECOMMENDATIONS_ID)),
                )
            )
    elif AI_RECOMMENDATIONS_ID in ids:
        issues.append(
            _err(
                "ai_recommendations_disabled",
                f"params.ai_recommendations is false, so remove the '{AI_RECOMMENDATIONS_ID}' "
                "section (or set it to true).",
                line_of("sections", ids.index(AI_RECOMMENDATIONS_ID)),
            )
        )

    blocks = _prompt_blocks(lines, close + 1, issues)
    if SYSTEM_PROMPT_ID not in blocks:
        issues.append(
            _err(
                "missing_prompt",
                "Add a '<!-- mm3:prompt:_system -->' block with the template's rules.",
                close + 2,
            )
        )
    for i, s in enumerate(sections):
        if s.id not in blocks and s.id != SYSTEM_PROMPT_ID:
            issues.append(
                _err(
                    "missing_prompt",
                    f"Section '{s.id}' has no '<!-- mm3:prompt:{s.id} -->' block.",
                    line_of("sections", i),
                )
            )
    for pid, (_, line) in blocks.items():
        if pid != SYSTEM_PROMPT_ID and pid not in seen:
            issues.append(_err("unknown_prompt", f"No section has the id '{pid}'.", line))

    report.issues = issues
    if report.errors:
        return report
    report.template = Template(
        id=fm.id,
        name=" ".join(fm.name.split()),
        description=" ".join(fm.description.split()),
        tags=tuple(str(t) for t in fm.tags),
        favorite=fm.favorite,
        sections=tuple(sections),
        params=fm.params,
        system_prompt=blocks[SYSTEM_PROMPT_ID][0],
        prompts={pid: text for pid, (text, _) in blocks.items() if pid != SYSTEM_PROMPT_ID},
    )
    return report


def parse_template_file(path: Path) -> TemplateReport:
    try:
        if path.stat().st_size > MAX_TEMPLATE_BYTES:
            return TemplateReport(
                None,
                [_err("file_too_large", f"Templates are limited to {MAX_TEMPLATE_BYTES} bytes.")],
            )
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return TemplateReport(None, [_err("unreadable", f"Cannot read the file: {exc}.")])
    return parse_template(text, source=str(path))
