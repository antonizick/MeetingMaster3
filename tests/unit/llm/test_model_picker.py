"""The cloud model picker (Phase 15h, ADR-0042): prices, the capable-model filter, the cost
estimate, the measured recommendations and the grouped picker data."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.llm import recommendations
from meetingmaster3.llm.base import ModelInfo
from meetingmaster3.llm.bedrock import BedrockBackend, collect_models, region_geo
from meetingmaster3.llm.cost import (
    estimate_cost,
    estimate_tokens_for_note,
    transcript_tokens_for,
)
from meetingmaster3.llm.openai_compat import OpenAICompatBackend, parse_pricing
from meetingmaster3.llm.pricing import (
    PriceTable,
    bedrock_price,
    cost_usd,
    format_price,
    format_usd,
    is_stale,
    with_table_price,
)
from meetingmaster3.templates.model_check import assess, suggest
from meetingmaster3.templates.picker import build_picker, meeting_shape

KEY = "sk-or-v1-supersecretvalue1234567890"

OPENROUTER_MODELS: dict[str, Any] = {
    "data": [
        {
            "id": "anthropic/claude-haiku-5.5",
            "name": "Anthropic: Claude Haiku 5.5",
            "context_length": 1_000_000,
            "pricing": {"prompt": "0.0000001", "completion": "0.0000005"},
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        },
        {
            "id": "anthropic/claude-sonnet-5.5",
            "name": "Anthropic: Claude Sonnet 5.5",
            "context_length": 1_000_000,
            "pricing": {"prompt": "0.000002", "completion": "0.00001"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {
            "id": "meta-llama/llama-4-maverick:free",
            "name": "Llama 4 Maverick (free)",
            "context_length": 128_000,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {
            "id": "openrouter/auto",
            "name": "Auto Router",
            "context_length": 2_000_000,
            "pricing": {"prompt": "-1", "completion": "-1"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {
            "id": "google/imagen-x",
            "name": "Imagen X",
            "context_length": 8000,
            "pricing": {"prompt": "0.000001", "completion": "0.000001"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
        },
        {
            "id": "deepseek/deepseek-r1-0528",
            "name": "DeepSeek R1",
            "context_length": 128_000,
            "pricing": {"prompt": "0.0000005", "completion": "0.000002"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {"id": "plain/model", "context_length": 32_000},
    ]
}


def openrouter(default_model: str | None = None) -> OpenAICompatBackend:
    return OpenAICompatBackend(
        "or_",
        base_url="https://openrouter.ai/api/v1",
        api_key=KEY,
        default_model=default_model,
        kind="openrouter",
    )


# -- OpenRouter listing -------------------------------------------------------------------------


def test_parse_pricing_converts_per_token_strings_to_per_million() -> None:
    assert parse_pricing({"prompt": "0.0000001", "completion": "0.0000005"}) == pytest.approx(
        (0.1, 0.5)
    )
    for bad in (None, {}, {"prompt": "x", "completion": "1"}, {"prompt": "-1", "completion": "-1"}):
        assert parse_pricing(bad) == (None, None)


@respx.mock
async def test_openrouter_list_keeps_prices_and_modalities() -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(json=OPENROUTER_MODELS)
    models = {m.id: m for m in await openrouter().list_models()}
    haiku = models["anthropic/claude-haiku-5.5"]
    assert haiku.price_in == pytest.approx(0.1)
    assert haiku.price_out == pytest.approx(0.5)
    assert haiku.price_source == "live"
    assert haiku.text_only is True
    assert models["meta-llama/llama-4-maverick:free"].free is True
    assert models["openrouter/auto"].price_in is None  # variable price: shown without one
    assert models["google/imagen-x"].text_only is False
    plain = models["plain/model"]
    assert plain.price_in is None and plain.text_only is None and not plain.free


# -- Bedrock listing ----------------------------------------------------------------------------


def summary(
    model_id: str, types: list[str], status: str = "ACTIVE", **extra: Any
) -> dict[str, Any]:
    return {
        "modelId": model_id,
        "modelName": model_id,
        "outputModalities": ["TEXT"],
        "inferenceTypesSupported": types,
        "modelLifecycle": {"status": status},
        **extra,
    }


def profile(profile_id: str) -> dict[str, Any]:
    return {"inferenceProfileId": profile_id, "inferenceProfileName": profile_id}


def test_bedrock_collapses_base_and_profile_into_the_callable_id() -> None:
    summaries = [
        summary("anthropic.claude-haiku-5-5", ["INFERENCE_PROFILE"]),
        summary("amazon.nova-lite-v1:0", ["ON_DEMAND"]),
        summary("both.model-v1", ["ON_DEMAND", "INFERENCE_PROFILE"]),
        summary("prov.only-v1", ["PROVISIONED"]),
        summary("anthropic.claude-old-v1", ["ON_DEMAND"], status="LEGACY"),
        summary("noprofile.model-v1", ["INFERENCE_PROFILE"]),
        {"modelId": "img", "outputModalities": ["IMAGE"]},
    ]
    profiles = [
        profile("global.anthropic.claude-haiku-5-5"),
        profile("us.anthropic.claude-haiku-5-5"),
        profile("us.both.model-v1"),
        profile("us.anthropic.claude-old-v1"),
        profile("us.brandnew.model-v1"),
    ]
    found = {m.id: m for m in collect_models(summaries, profiles, "us-east-1")}
    assert set(found) == {
        "us.anthropic.claude-haiku-5-5",  # the Region's own profile beats global.
        "amazon.nova-lite-v1:0",
        "both.model-v1",  # on demand: listed by its own id, not its us. twin
        "prov.only-v1",
        "noprofile.model-v1",
        "us.brandnew.model-v1",  # a profile of a model the list does not describe
    }
    assert found["prov.only-v1"].callable is False
    assert found["noprofile.model-v1"].callable is False
    assert found["amazon.nova-lite-v1:0"].callable is True
    assert "us.anthropic.claude-old-v1" not in found  # its base model is LEGACY


def test_bedrock_falls_back_to_global_profile_and_attaches_table_prices() -> None:
    found = collect_models(
        [summary("anthropic.claude-sonnet-5-5", ["INFERENCE_PROFILE"])],
        [profile("global.anthropic.claude-sonnet-5-5")],
        "eu-west-1",
    )
    (model,) = found
    assert model.id == "global.anthropic.claude-sonnet-5-5"
    assert (model.price_in, model.price_out, model.price_source) == (2.0, 10.0, "table")
    assert model.price_as_of and model.context_window == 200_000


def test_region_geo() -> None:
    assert [region_geo(r) for r in ("us-east-1", "eu-west-1", "ap-southeast-2")] == [
        "us",
        "eu",
        "apac",
    ]


async def test_bedrock_list_models_uses_the_stubbed_listing() -> None:
    from botocore.stub import Stubber

    from tests.unit.llm.test_bedrock import backend, clients

    runtime, control = clients()
    with Stubber(control) as stub:
        stub.add_response(
            "list_foundation_models",
            {
                "modelSummaries": [
                    {
                        "modelId": "anthropic.claude-haiku-5-5",
                        "modelArn": "arn:a",
                        "outputModalities": ["TEXT"],
                        "inferenceTypesSupported": ["INFERENCE_PROFILE"],
                        "modelLifecycle": {"status": "ACTIVE"},
                    }
                ]
            },
            {"byOutputModality": "TEXT"},
        )
        stub.add_response(
            "list_inference_profiles",
            {
                "inferenceProfileSummaries": [
                    {
                        "inferenceProfileName": "H",
                        "inferenceProfileArn": "arn:p",
                        "inferenceProfileId": "us.anthropic.claude-haiku-5-5",
                        "status": "ACTIVE",
                        "type": "SYSTEM_DEFINED",
                        "models": [{"modelArn": "arn:a"}],
                    }
                ]
            },
        )
        models = await backend(runtime, control).list_models()
    assert [(m.id, m.price_in) for m in models] == [("us.anthropic.claude-haiku-5-5", 0.1)]


# -- prices -------------------------------------------------------------------------------------


def test_bedrock_price_uses_longest_prefix_and_ignores_geography() -> None:
    table = PriceTable("2026-01-01", {"anthropic.claude": (1.0, 5.0), "anthropic.claude-x": (2, 9)})
    assert bedrock_price("us.anthropic.claude-x-v1", table) == (2, 9)
    assert bedrock_price("anthropic.claude-y", table) == (1.0, 5.0)
    assert bedrock_price("meta.llama", table) is None
    model = with_table_price(ModelInfo(id="meta.llama"), table)
    assert model.price_in is None  # unlisted family: no price, never a guess


def test_staleness_and_formatting() -> None:
    today = dt.date(2026, 10, 16)
    assert not is_stale("2026-10-15", today)
    assert is_stale("2026-04-01", today)  # 198 days
    assert is_stale("", today) and is_stale("garbage", today)
    assert [format_price(v) for v in (0, 0.1, 2, 0.035, 10.5)] == [
        "free",
        "$0.10",
        "$2.00",
        "$0.035",
        "$10.50",
    ]
    assert [format_usd(v) for v in (0.0001, 0.003, 0.07, 1.2)] == [
        "less than $0.001",
        "$0.003",
        "$0.07",
        "$1.20",
    ]
    assert cost_usd(ModelInfo(id="x"), 1000, 1000) is None
    priced = ModelInfo(id="x", price_in=2.0, price_out=10.0)
    assert cost_usd(priced, 500_000, 100_000) == pytest.approx(2.0)


# -- cost estimate ------------------------------------------------------------------------------


def test_estimate_full_mode_matches_the_measured_real_meeting() -> None:
    est = estimate_tokens_for_note(transcript_tokens_for(31), 200_000, sections=8)
    # 8 section calls x (31 min x 300 + 700 overhead) = 80 000: the 15g real-meeting figure.
    assert (est.input_tokens, est.output_tokens, est.calls, est.map_reduce) == (
        80_000,
        8 * 350,
        8,
        False,
    )


def test_estimate_switches_to_map_reduce_when_the_window_is_small() -> None:
    est = estimate_tokens_for_note(transcript_tokens_for(60), 16_384, sections=8)
    assert est.map_reduce and est.calls > 8
    full = estimate_tokens_for_note(transcript_tokens_for(60), 200_000, sections=8)
    assert est.input_tokens < full.input_tokens  # parts send the transcript once


def test_estimate_respects_a_section_output_cap_and_unknown_window() -> None:
    capped = estimate_tokens_for_note(3000, 200_000, sections=2, section_max_tokens=100)
    assert capped.output_tokens == 200
    unknown = estimate_tokens_for_note(3000, None, sections=1)
    assert unknown.input_tokens == 3700 and not unknown.map_reduce


def test_estimate_cost_for_an_hour_with_haiku_and_sonnet() -> None:
    haiku = ModelInfo(id="h", price_in=0.1, price_out=0.5, context_window=200_000)
    sonnet = ModelInfo(id="s", price_in=2.0, price_out=10.0, context_window=200_000)
    tokens = transcript_tokens_for(60)  # 18 000
    in_tokens, out_tokens = 8 * (18_000 + 700), 8 * 350
    assert estimate_cost(haiku, tokens) == pytest.approx((in_tokens * 0.1 + out_tokens * 0.5) / 1e6)
    assert estimate_cost(sonnet, tokens) == pytest.approx(
        (in_tokens * 2.0 + out_tokens * 10.0) / 1e6
    )
    assert estimate_cost(ModelInfo(id="free-of-price"), tokens) is None


def test_meeting_shape_reads_the_template() -> None:
    assert meeting_shape(None, None).minutes == 60
    shaped = meeting_shape(30, "default-notes")
    assert shaped.minutes == 30 and shaped.sections == 8
    assert meeting_shape(0, "no-such-template").sections == 8


# -- recommendations ----------------------------------------------------------------------------


def test_picks_and_unsuitable_load_from_the_shipped_file() -> None:
    for kind in ("bedrock", "openrouter"):
        picks = {p.badge: p for p in recommendations.load_picks(kind)}
        assert set(picks) == {"best-value", "best-quality"}
        assert picks["best-value"].label == "Best value" and picks["best-value"].measured
        assert "haiku" in picks["best-value"].model and "sonnet" in picks["best-quality"].model
    assert recommendations.load_picks("openai") == []
    rules = recommendations.load_unsuitable("bedrock")
    assert (
        recommendations.unsuitable_reason("us.deepseek.r1-v1:0", [(p, r) for p, r in rules]) is None
    )
    assert recommendations.unsuitable_reason("deepseek.r1-v1:0", rules)


def test_an_unknown_data_file_version_degrades_to_no_picks(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text("version: 99\npicks: {bedrock: [{badge: best-value, model: x}]}\n")
    assert recommendations.load_picks("bedrock", path) == []
    assert recommendations.load_unsuitable("bedrock", path) == []
    assert recommendations.load_cloud(path) == []


# -- the filter and the picker data ---------------------------------------------------------------


@respx.mock
async def priced_picker() -> dict[str, Any]:
    respx.get("https://openrouter.ai/api/v1/models").respond(json=OPENROUTER_MODELS)
    backend = openrouter()
    return build_picker(backend, await backend.list_models(), None)


async def test_openrouter_picker_filters_groups_and_prices() -> None:
    p = await priced_picker()
    assert [(m["id"], m["badge"]) for m in p["recommended"]] == [
        ("anthropic/claude-haiku-5.5", "best-value"),
        ("anthropic/claude-sonnet-5.5", "best-quality"),
    ]
    assert {m["id"] for m in p["other"]} == {
        "meta-llama/llama-4-maverick:free",
        "openrouter/auto",
        "plain/model",
    }
    # cheapest first; unpriced models after the priced ones
    assert p["other"][0]["id"] == "meta-llama/llama-4-maverick:free"
    assert p["other"][0]["free"] and p["other"][0]["estimate_text"].startswith("about less than")
    hidden = {m["id"]: m["reason"] for m in p["hidden"]}
    assert set(hidden) == {"google/imagen-x", "deepseek/deepseek-r1-0528"}
    assert (
        "text" in hidden["google/imagen-x"]
        and "Measured as unsuitable" in hidden["deepseek/deepseek-r1-0528"]
    )
    assert (
        p["hidden_count"] == 2
        and p["has_prices"]
        and p["suggested"] == "anthropic/claude-haiku-5.5"
    )
    haiku = p["recommended"][0]
    assert haiku["price_text"] == "$0.10 in / $0.50 out per 1M tokens"
    assert haiku["estimate_text"] == "about $0.016 for 60 minutes of meeting (estimate)"
    assert "Best value" in haiku["summary"] or haiku["badge_label"] == "Best value"


async def test_a_recommended_model_the_provider_does_not_list_is_dropped() -> None:
    backend = openrouter()
    models = [
        ModelInfo(
            id="anthropic/claude-sonnet-5.5",
            context_window=200_000,
            price_in=2,
            price_out=10,
            price_source="live",
        )
    ]
    p = build_picker(backend, models, None)
    assert [m["badge"] for m in p["recommended"]] == ["best-quality"]
    assert p["suggested"] == "anthropic/claude-sonnet-5.5"  # falls back to the first capable one


def test_bedrock_pick_matches_whichever_profile_the_account_lists() -> None:
    backend = BedrockBackend("aws", region="eu-west-1")
    models = collect_models(
        [summary("anthropic.claude-haiku-5-5", ["INFERENCE_PROFILE"])],
        [profile("eu.anthropic.claude-haiku-5-5")],
        "eu-west-1",
    )
    p = build_picker(backend, models, None)
    assert p["recommended"][0]["id"] == "eu.anthropic.claude-haiku-5-5"
    assert p["prices_as_of"] and p["pricing_url"].startswith("https://aws.amazon.com")


def test_assess_reasons() -> None:
    backend = openrouter()
    cases = [
        (ModelInfo(id="e", can_generate=False), "embedding"),
        (ModelInfo(id="i", text_only=False), "text"),
        (ModelInfo(id="p", callable=False), "Provisioned"),
        (ModelInfo(id="d", access="denied"), "no access"),
        (ModelInfo(id="deepseek/deepseek-r1", context_window=128_000), "unsuitable"),
    ]
    for model, word in cases:
        verdict = assess(model, backend, None)
        assert not verdict.capable and word in verdict.reason
    assert assess(ModelInfo(id="ok", context_window=128_000), backend, None).capable
    assert assess(ModelInfo(id="unknown-window"), backend, None).capable
    assert not assess(ModelInfo(id="tiny", context_window=2048), backend, None).capable


def test_suggest_prefers_best_value_for_cloud_only() -> None:
    backend = openrouter()
    models = [
        ModelInfo(id="a/first", context_window=128_000),
        ModelInfo(id="anthropic/claude-haiku-5.5", context_window=200_000),
    ]
    assert suggest(models, backend, None) == "anthropic/claude-haiku-5.5"
    assert suggest(models[:1], backend, None) == "a/first"


# -- the two endpoints agree ----------------------------------------------------------------------


@pytest.fixture
def api() -> TestClient:
    s = Settings()
    s.llm.backends = {
        "or_": BackendConfig(
            kind="openrouter",
            api_key=KEY,
            default_model="anthropic/claude-haiku-5.5",
        )
    }
    s.register_secrets()
    return TestClient(create_app(s), base_url="http://localhost")


@respx.mock
def test_settings_and_new_meeting_show_the_same_capable_set(api: TestClient) -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(json=OPENROUTER_MODELS)
    body = api.get("/api/llm/backends/or_/models").json()
    capable = {m["id"] for m in body["models"] if m["usable"]}
    html = api.get("/settings/llm/or_/models?target=b-model").text
    shown = {m["id"] for m in body["models"] if f'value="{m["id"]}"' in html}
    assert shown == capable
    assert 'value="google/imagen-x"' not in html and "Show all models (2 hidden)" in html
    assert "Best value: " in html and "Best quality: " in html
    assert 'data-model-target="b-model"' in html
    assert "$0.10 in / $0.50 out per 1M tokens" in html and "(estimate)" in html
    assert "Live prices" in html


@respx.mock
def test_show_all_lists_hidden_models_with_their_reason(api: TestClient) -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(json=OPENROUTER_MODELS)
    html = api.get("/settings/llm/or_/models?show_all=1&target=model&minutes=30").text
    assert 'value="google/imagen-x"' in html and "Does not take text in" in html
    assert "for 30 minutes" in html
    assert "hx-get" not in html  # no second "Show all" button


@respx.mock
def test_a_failed_listing_still_names_the_configured_model(api: TestClient) -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(status_code=401)
    html = api.get("/settings/llm/or_/models").text
    assert "Could not list models" in html and "Prices are unavailable" in html
    assert "anthropic/claude-haiku-5.5" in html


def test_local_backend_shows_no_prices() -> None:
    from meetingmaster3.llm.ollama import OllamaBackend

    backend = OllamaBackend("ollama", base_url="http://127.0.0.1:11434")
    models = [ModelInfo(id="qwen3:8b", context_window=32_000, price_in=1.0, price_out=2.0)]
    p = build_picker(backend, models, None)
    assert p["recommended"] == [] and not p["has_prices"]
    assert p["other"][0]["price_text"] == "" and p["other"][0]["estimate_text"] == ""


@respx.mock
def test_review_page_form_endpoint_uses_the_forms_own_backend(api: TestClient) -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(json=OPENROUTER_MODELS)
    html = api.get(
        "/settings/llm/models?target=switch-model&backend=or_&template=default-notes"
    ).text
    assert 'data-model-target="switch-model"' in html and "Best value: " in html
