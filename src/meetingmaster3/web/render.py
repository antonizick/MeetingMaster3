"""Sanitised Markdown rendering for the read-only note preview (SPEC §15.3 S3).

Raw HTML in the Markdown is never passed through (markdown-it ``html: False`` escapes it), images
are not rendered (no request to a third-party host), and links are limited to ``http``, ``https``
and ``mailto``. The page's CSP forbids inline script as a second layer.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from markupsafe import Markup

from meetingmaster3.markdown.frontmatter import FrontmatterError, split_frontmatter

_ALLOWED_SCHEMES = ("http://", "https://", "mailto:")
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
        token.attrSet("rel", "noopener noreferrer")
        token.attrSet("target", "_blank")
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("link_open", link_open)
    return md


_MD = _build()


def render_markdown(text: str) -> Markup:
    """Render a note (frontmatter and section-marker comments hidden) to safe HTML."""
    try:
        _, body = split_frontmatter(text)
    except FrontmatterError:
        body = text
    body = _COMMENT_LINE.sub("", body)
    return Markup(_MD.render(body))  # noqa: S704 - html is disabled in the parser; see module doc
