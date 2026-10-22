"""Sanitised Markdown rendering for the read-only note preview (SPEC §15.3 S3).

Raw HTML in the Markdown is never passed through (markdown-it ``html: False`` escapes it), images
are not rendered (no request to a third-party host), and links are limited to ``http``, ``https``
and ``mailto``. The page's CSP forbids inline script as a second layer.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from markupsafe import Markup

from meetingmaster3.markdown.frontmatter import FrontmatterError, split_frontmatter

_ALLOWED_SCHEMES = ("http://", "https://", "mailto:")
_TIMESTAMP_RE = re.compile(r"\[(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>[0-5]\d)\]")
_COMMENT_LINE = re.compile(r"^[ \t]*<!--.*?-->[ \t]*$", re.MULTILINE)


def _safe_link(url: str) -> bool:
    lowered = url.strip().lower()
    if lowered.startswith(("#", "/")) and not lowered.startswith("//"):
        return True
    return lowered.startswith(_ALLOWED_SCHEMES)


def _build() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])
    md.disable(["image"])
    md.validateLink = _safe_link  # type: ignore[method-assign]

    def link_open(
        self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        token = tokens[idx]
        href = token.attrGet("href")
        internal = isinstance(href, str) and href.startswith(("/", "#")) and href[:2] != "//"
        if not internal:  # links into the app open in place
            token.attrSet("rel", "noopener noreferrer")
            token.attrSet("target", "_blank")
        return self.renderToken(tokens, idx, options, env)

    def text(
        self: RendererHTML, tokens: list[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        content = escapeHtml(tokens[idx].content)
        if not env.get("timestamps"):
            return content
        return _TIMESTAMP_RE.sub(_timestamp_button, content)

    md.add_render_rule("link_open", link_open)
    md.add_render_rule("text", text)
    return md


def _timestamp_button(m: re.Match[str]) -> str:
    seconds = int(m["h"] or 0) * 3600 + int(m["m"]) * 60 + int(m["s"])
    return (
        f'<button type="button" class="ts-link" data-t="{seconds}" '
        f'title="Play from {m.group(0)[1:-1]}">{m.group(0)}</button>'
    )


_MD = _build()


def render_markdown(text: str, *, timestamps: bool = False) -> Markup:
    """Render a note (frontmatter and section-marker comments hidden) to safe HTML. With
    ``timestamps``, ``[mm:ss]`` and ``[h:mm:ss]`` references become buttons carrying the time in
    seconds (``data-t``), which the review workspace uses to seek the audio."""
    try:
        _, body = split_frontmatter(text)
    except FrontmatterError:
        body = text
    body = _COMMENT_LINE.sub("", body)
    return Markup(_MD.render(body, {"timestamps": timestamps}))  # noqa: S704 - html is disabled in the parser; see module doc
