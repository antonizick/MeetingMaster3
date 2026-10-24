"""Grok share links (Phase 15l): link parsing, the confined fetch and the share-JSON parser."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from meetingmaster3.errors import MM3Error
from meetingmaster3.importing import detect_and_parse
from meetingmaster3.importing import fetch as fetch_mod
from meetingmaster3.importing.convert import to_transcript
from meetingmaster3.importing.fetch import ENDPOINT, USER_AGENT, fetch_share
from meetingmaster3.importing.grok_share import (
    looks_like_share_url,
    parse_share,
    parse_share_data,
    parse_share_url,
    title_from,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "imports"
SID = "c3ludGhldGlj_0f8b5c3e-1111-4222-8333-944445555666"
API = ENDPOINT.format(id=SID)


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"grok-share-{name}.json").read_text("utf-8"))
    return data


# -- links -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        f"https://x.com/i/grok/share/{SID}",
        f"https://twitter.com/i/grok/share/{SID}",
        f"https://grok.com/share/{SID}",
        f"https://www.x.com/i/grok/share/{SID}/",
        f"  <https://X.COM/i/grok/share/{SID}?s=09&t=abc#frag>  ",
        f"x.com/i/grok/share/{SID}",
        f"HTTPS://grok.com/share/{SID}?rid=1",
    ],
)
def test_accepted_links(link: str) -> None:
    assert parse_share_url(link) == SID


@pytest.mark.parametrize(
    "link",
    [
        f"http://x.com/i/grok/share/{SID}",
        f"ftp://grok.com/share/{SID}",
        f"https://grok.com.evil.com/share/{SID}",
        f"https://evil.com/grok.com/share/{SID}",
        f"https://x.com@evil.com/i/grok/share/{SID}",
        f"https://user:pw@grok.com/share/{SID}",
        f"https://grok.com:8443/share/{SID}",
        f"https://gr\u043ek.com/share/{SID}",  # Cyrillic o look-alike
        f"https://xn--grk-qdd.com/share/{SID}",
        f"https://x.com/i/grok/share/../../../rest/{SID}",
        f"https://x.com/i/grok/share/{SID}%2F..%2Fadmin",
        f"https://grok.com/share/{SID}/extra",
        f"https://grok.com/rest/app-chat/share_links/{SID}",
        f"https://x.com/i/grok/{SID}",
        "https://x.com/i/grok/share/short",
        "https://x.com/i/grok/share/" + "a" * 201,
        "https://chatgpt.com/share/6702c0de-aaaa-bbbb-cccc-1234567890ab",
        "https://claude.ai/share/0f8b5c3e-1111-4222-8333-944445555666",
        "https://example.com/",
        "",
        "   ",
        f"https://grok.com/share/{SID} trailing",
        f"https://grok.com\\share\\{SID}",
        "javascript:alert(1)",
    ],
)
def test_refused_links(link: str) -> None:
    with pytest.raises(MM3Error) as err:
        parse_share_url(link)
    assert err.value.code == "E_IMPORT_URL_UNSUPPORTED"
    assert "Markdown" in err.value.hint


def test_looks_like_share_url() -> None:
    assert looks_like_share_url(f"https://grok.com/share/{SID}")
    assert looks_like_share_url(f"x.com/i/grok/share/{SID}")
    assert not looks_like_share_url("notes/chat.md")


# -- fetch -----------------------------------------------------------------------------------

BODY = json.dumps(fixture("linear")).encode()


@respx.mock
def test_fetch_sends_one_plain_request() -> None:
    route = respx.get(API).mock(
        return_value=httpx.Response(200, content=BODY, headers={"content-type": "application/json"})
    )
    assert fetch_share(SID, max_bytes=1 << 20) == BODY
    assert route.call_count == 1
    req = route.calls[0].request
    assert req.url.scheme == "https" and req.url.host == "grok.com"
    assert req.headers["user-agent"] == USER_AGENT
    assert req.headers["accept"] == "application/json"
    assert "cookie" not in req.headers and "authorization" not in req.headers


@respx.mock
@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_refused(status: int) -> None:
    respx.get(API).mock(
        return_value=httpx.Response(status, headers={"location": "http://169.254.169.254/"})
    )
    other = respx.get(url__startswith="http://169.254.169.254").mock(httpx.Response(200))
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1 << 20)
    assert err.value.code == "E_IMPORT_SHARE_UNAVAILABLE" and not other.called


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_not_shared_is_not_retried(status: int) -> None:
    route = respx.get(API).mock(return_value=httpx.Response(status))
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1 << 20, sleep=lambda s: None)
    assert err.value.code == "E_IMPORT_SHARE_NOT_FOUND" and route.call_count == 1
    assert "not shared publicly" in err.value.message and "Markdown" in err.value.hint


@respx.mock
def test_5xx_is_retried_once() -> None:
    route = respx.get(API).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=BODY)]
    )
    slept: list[float] = []
    assert fetch_share(SID, max_bytes=1 << 20, sleep=slept.append) == BODY
    assert route.call_count == 2 and slept == [fetch_mod.RETRY_DELAY_SECONDS]
    route.side_effect = [httpx.Response(502), httpx.Response(500)]
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1 << 20, sleep=lambda s: None)
    assert err.value.code == "E_IMPORT_SHARE_UNAVAILABLE" and route.call_count == 4


@respx.mock
def test_timeout_is_retried_once_then_reported() -> None:
    route = respx.get(API).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1 << 20, sleep=lambda s: None)
    assert err.value.code == "E_IMPORT_OFFLINE" and route.call_count == 2


@respx.mock
def test_offline_says_so() -> None:
    route = respx.get(API).mock(side_effect=httpx.ConnectError("Name or service not known"))
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1 << 20, sleep=lambda s: None)
    assert err.value.code == "E_IMPORT_OFFLINE" and "offline" in err.value.message
    assert route.call_count == 1


@respx.mock
def test_oversize_is_refused_while_streaming() -> None:
    respx.get(API).mock(return_value=httpx.Response(200, content=b"{" + b" " * 5000 + b"}"))
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1000)
    assert err.value.code == "E_IMPORT_TOO_LARGE"
    respx.get(API).mock(return_value=httpx.Response(200, headers={"content-length": "999999"}))
    with pytest.raises(MM3Error):
        fetch_share(SID, max_bytes=1000)


@respx.mock
def test_html_answer_is_unavailable() -> None:
    respx.get(API).mock(
        return_value=httpx.Response(
            200, content=b"<html>login</html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(MM3Error) as err:
        fetch_share(SID, max_bytes=1 << 20)
    assert err.value.code == "E_IMPORT_SHARE_UNAVAILABLE"


@respx.mock
def test_cancel_during_the_download() -> None:
    respx.get(API).mock(return_value=httpx.Response(200, content=BODY))

    class Stop(Exception):
        pass

    def check() -> None:
        raise Stop

    with pytest.raises(Stop):
        fetch_share(SID, max_bytes=1 << 20, check=check)


def test_share_url_is_built_from_a_valid_id_only() -> None:
    with pytest.raises(ValueError):
        fetch_mod.share_url("../admin")


# -- parser ----------------------------------------------------------------------------------


def test_linear_voice_chat() -> None:
    conv = detect_and_parse(json.dumps(fixture("linear")).encode(), "source.json")
    assert conv.source_format == "grok-share" and conv.timed
    assert [t.role for t in conv.turns] == ["user", "assistant"] * 4
    assert all(t.speaker == "Grok" for t in conv.turns if t.role == "assistant")
    assert all(t.speaker == "" for t in conv.turns if t.role == "user")
    # Growing prefixes merge into the full text at the time of the first copy.
    assert conv.turns[0].text.endswith("Where do I even start?") and conv.turns[0].start == 0.0
    assert conv.turns[2].start == pytest.approx(41.2)
    assert [t.start for t in conv.turns[1::2]] == pytest.approx([12.0, 48.3, 72.4, 97.9])
    assert conv.turns[0].end == pytest.approx(12.0)
    assert "**Find the land**" in conv.turns[1].text and "```text" in conv.turns[-1].text
    assert any("Merged 3" in w for w in conv.warnings)
    # "Discussion Request" is generic: the first user sentence names it.
    assert conv.title == "I want to plan a community garden for our street"
    assert conv.started_at is not None and conv.started_at.tzinfo is not None
    assert conv.started_at.utcoffset() == conv.started_at.astimezone().utcoffset()
    transcript, speakers = to_transcript(conv, user_name="Nick", assistant_name="AI")
    assert [s.default_name for s in speakers] == ["Nick", "Grok"]
    assert transcript.timed and transcript.duration == pytest.approx(97.9)


def test_branches_follow_the_latest_child() -> None:
    conv = parse_share_data(fixture("branched"))
    texts = [t.text for t in conv.turns]
    assert not any(t.startswith("OLD") for t in texts) and texts[-1] == "**Knead**."
    assert any("Skipped 2 alternative replies" in w for w in conv.warnings)
    assert conv.title == "Bakery Name Ideas"


def test_partial_empty_and_unknown_messages_are_dropped() -> None:
    conv = parse_share_data(fixture("partial"))
    assert [t.text for t in conv.turns] == [
        "Summarise the meeting rules for me.",
        "Rules: start on time, one speaker at a time, end with owners for every task.",
        "Thanks.",
    ]
    assert conv.turns[1].start == 3.0
    assert any("unfinished" in w for w in conv.warnings)
    assert any("unknown sender" in w for w in conv.warnings)


def test_unicode_is_kept() -> None:
    conv = parse_share((FIXTURES / "grok-share-unicode.json").read_text("utf-8"), "source.json")
    assert conv.title == "Mots pour « réunion »"
    assert "会議" in conv.turns[1].text and "اجتماع" in conv.turns[1].text
    assert conv.turns[3].start == pytest.approx(13.25)


def test_times_are_relative_to_the_first_kept_message() -> None:
    data = fixture("partial")
    data["responses"][0]["partial"] = True  # the first message no longer counts
    conv = parse_share_data(data)
    assert conv.turns[0].start == 0.0 and conv.turns[1].start == 17.0


def test_a_message_without_a_time_makes_it_untimed() -> None:
    data = fixture("unicode")
    del data["responses"][2]["createTime"]
    conv = parse_share_data(data)
    assert not conv.timed and all(t.start is None for t in conv.turns)
    assert any("no timestamps" in w for w in conv.warnings)


def test_no_parent_links_reads_in_time_order() -> None:
    data = fixture("unicode")
    for r in data["responses"]:
        r.pop("parentResponseId")
    data["responses"].reverse()
    conv = parse_share_data(data)
    assert conv.turns[0].text.startswith("Comment dit-on") and not conv.warnings


def test_cycles_and_unknown_keys_are_harmless() -> None:
    data = fixture("unicode")
    data["responses"][0]["parentResponseId"] = data["responses"][-1]["responseId"]
    data["responses"].append(dict(data["responses"][1], responseId="extra", futureField={"a": 1}))
    conv = parse_share_data(data)  # every message has a parent: read in time order
    assert conv.turns


@pytest.mark.parametrize(
    "data",
    [[], {"responses": "x"}, {"responses": [{"sender": "human"}]}, {"conversation": {}}],
)
def test_wrong_shape_is_unavailable(data: Any) -> None:
    with pytest.raises(MM3Error) as err:
        parse_share_data(data)
    assert err.value.code == "E_IMPORT_SHARE_UNAVAILABLE"


def test_not_json() -> None:
    with pytest.raises(MM3Error) as err:
        parse_share("<html></html>", "source.json")
    assert err.value.code == "E_IMPORT_SHARE_UNAVAILABLE"


def test_title_from_first_sentence() -> None:
    assert title_from("Um, hey Grok, so what should I eat tonight? Something quick.") == (
        "What should I eat tonight"
    )
    assert title_from("um uh") is None
    long = title_from("one two three four five six seven eight nine ten eleven twelve")
    assert long == "One two three four five six seven eight nine ten…"


def test_markdown_chat_is_not_detected_as_a_share() -> None:
    conv = detect_and_parse(b'{"note": "not a share"}\n\nUser: hi\n\nAssistant: hello', "x.md")
    assert conv.source_format != "grok-share"


@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("MM3_TEST_GROK_SHARE"), reason="MM3_TEST_GROK_SHARE unset")
def test_live_synthetic_share() -> None:
    """A synthetic conversation Nick shared for testing (never a real one)."""
    share_id = parse_share_url(os.environ["MM3_TEST_GROK_SHARE"])
    conv = parse_share(fetch_share(share_id, max_bytes=10 << 20).decode(), "source.json")
    assert conv.timed and {t.role for t in conv.turns} == {"user", "assistant"}
