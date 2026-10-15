# Phase 15h: Cloud model picker with prices and recommendations

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 15g · **Branch:** `phase-15h-cloud-model-picker` · **Worktree:** `../MeetingMaster3-phase-15h`

Inserted with `/phase-add` after 15g (ADR-0030, ADR-0034, ADR-0042). When Nick planned the live cloud test (15g) he
asked for more than "it works". For each provider he wants a drop-down that lists only the models that can do
MeetingMaster3's job, what they cost, and a recommendation (the cheapest model that still writes decent notes, and
the best one even if it costs more). Today the pickers list everything the provider returns: Bedrock gives dozens of
models, some you have no access to and some you can only call through an inference profile, and OpenRouter gives
hundreds. The app shows no prices. This phase builds the filter, the prices and the recommendations on top of
15g's measured results.

## Read first
- `CLAUDE.md`, `prompts/_shared-instructions.md`, `docs/SPECIFICATION.md` §6 ("UI suggests … cloud models by
  capability, with clear cost/privacy notes") and §15.
- **The Phase 15g Phase Log entry and ADR-0041 "Results"**: which models were callable, measured eval quality, time,
  tokens and cost per note, model-list quirks. This phase's recommendations come from those numbers, not from
  guesses. If 15g recorded OpenRouter as untested, build its filter and prices from the documented `/models` format,
  test them with recorded responses, and give no "measured" OpenRouter recommendation (say so in the UI text).
- ADR-0029 (model checks, `usable`/`suggest`), ADR-0041, **ADR-0042** (this phase's decisions).
- `src/meetingmaster3/llm/cloud_recommendations.yaml`, `llm/recommendations.py`, the Bedrock model data file 15g
  added (`bedrock_models.yaml` or whatever 15g named it; check the 15g log), `docs/user-guide/llm-backends.md`.

## Nick's request (verbatim intent, 2026-10-15)
"With each model provider, there should be a drop-down where they can select the model they want to use, where
Meeting Master will filter and list the models that are appropriate and capable for what the program is doing for
our user. There should also be guidance if this is practical to what the costs of those models are. And ideally even
a recommendation of what model or program recommends based off of performance and price. It would also be very
acceptable if there was more than one recommendation to say this is the least expensive model with decent
performance or this is the top performing model but it is expensive."

## Decisions already made (ADR-0042)
- **Prices (option A):** OpenRouter prices are read live from its `/models` response (`pricing.prompt` /
  `pricing.completion`, USD per token), so they are always current. Bedrock prices come from a small, dated data file
  (on-demand price per 1M input and output tokens per model family and region, with an `as_of` date and the AWS
  pricing link), shown with "as of DATE; check AWS pricing". No AWS Price List API, no extra IAM permission. This
  replaces the Phase 08 rule "deliberately contains NO prices" (a YAML comment, not an ADR).
- **Recommendations:** at least two per provider, **Best value** (cheapest model that passed 15g's eval at an
  acceptable level) and **Best quality** (highest measured quality, whatever the cost). They are stored as dated data
  with the measurement they come from, never computed from price alone. A recommended id that the provider no longer
  lists is silently dropped (the picker still works).
- Split from 15g (ADR-0042): this phase does not repeat the live verification; it uses 15g's numbers.

## Goal
In Settings and on New meeting (and wherever else a model is chosen, such as the review page's template switch),
choosing a cloud model shows only models that can write MeetingMaster3 notes, each with its context size, price per
1M tokens and an estimated cost for a typical meeting, with Best value and Best quality marked and explained. A
"Show all models" option is still there for experts, and a typed custom id still works.

## What exists (verified 2026-10-15; re-check before relying on it, and after 15g)
- `src/meetingmaster3/llm/base.py:ModelInfo`: `id`, `name`, `context_window`, `size_bytes`, `can_generate`. No price,
  access or streaming fields.
- `src/meetingmaster3/templates/model_check.py`: `usable(model, backend, max_context)` (generates text and the window
  is workable after the local cap), `suggest()` prefers `TESTED_MODELS = ("qwen3:8b",)`, else the first usable model.
- `src/meetingmaster3/web/llm.py:backend_models` (`GET /api/llm/backends/{name}/models`) returns `usable` and
  `suggested`; used by the New meeting picker (`web/static/app.js` around the `suggestedModel` code, `templates/new.html`
  `<input id="model" list="model-list">`), which hides unusable models.
- `src/meetingmaster3/web/settings_ui.py:backend_models` (`GET /settings/llm/{name}/models`) renders
  `settings/_model_options.html` as a `<datalist>` for `_backend_form.html`'s `default_model` input; it filters only
  `can_generate is False`, **not** the context check, so Settings and New meeting disagree.
- `src/meetingmaster3/llm/bedrock.py:list_models` returns ACTIVE text-output foundation models plus every inference
  profile, with no access, on-demand or context check (15g may have changed this; see its log).
  `llm/openai_compat.py:_list_models` keeps `context_length` and drops the rest of OpenRouter's model object
  (pricing, `architecture`, `supported_parameters`).
- `src/meetingmaster3/llm/cloud_recommendations.yaml` and `llm/recommendations.py`: generic per-provider suggestions
  with `cost_tier` and `pricing_url`, served by `GET /api/llm/recommendations` (merged with the hardware
  recommendations for local models); the header comment says "Deliberately contains NO prices" and "Model ids are not
  pinned here".

## Tasks
1. **Model metadata.** Extend `ModelInfo` with optional fields (keep the dataclass frozen and backwards compatible):
   price per 1M input and output tokens plus its source (`live`, or `table` with `as_of`), whether it can be called
   on demand, and access status where known. Fill them in `OpenAICompatBackend._list_models` for OpenRouter (pricing,
   text output from `architecture`, ignore models whose pricing is missing or negative, mark `:free` variants) and in
   `BedrockBackend.list_models` (from the dated data file, plus on-demand / inference-profile and access status;
   collapse a base model and its `us.`/`eu.` profile into one entry that calls the one that works).
2. **One filter for every picker.** A single function (in `templates/model_check.py`, next to `usable`) decides
   "capable for MeetingMaster3": generates text, workable context (same rule as today), callable on demand or via a
   profile, access not denied, and for OpenRouter text-in/text-out. Use it in both `/api/llm/backends/{name}/models`
   and `/settings/llm/{name}/models` so they agree. Return the hidden count, and a reason per hidden model when
   "Show all" is on.
3. **Cost estimate.** A helper that estimates input and output tokens for a meeting from its transcript (review page,
   reprocess) or, before transcription, from the audio duration using a tokens-per-minute figure measured in 15g
   (put the figure and its source in the data file), for the chosen template (full vs map-reduce call count and
   output reserves, using the generator's own budget functions). Show "about $X for this meeting" or "about $X per
   hour of audio", rounded, with "estimate" in the text. Never show a price for a local backend.
4. **Recommendations.** Rewrite `cloud_recommendations.yaml` (with a version bump that `recommendations.py` handles)
   to hold, per provider, the dated **Best value** and **Best quality** entries from 15g's measurements: model id,
   why (quality score and cost per meeting from ADR-0041), measured date. Keep the privacy notes and pricing links.
   `suggest()` pre-selects Best value for a cloud backend when no `default_model` is set.
5. **Picker UI.** On New meeting, in Settings (backend form) and on the review page's template switch if it has a
   model choice: group the list as *Recommended* (badges "Best value" / "Best quality" with a one-line reason) then
   *Other capable models* (sorted by price), each showing name, context, price per 1M in/out and the meeting estimate;
   "Show all models (N hidden)" reveals the rest with the reason; a custom id can still be typed. Keep it accessible
   (label, keyboard, screen-reader text for badges and prices, no colour-only meaning), within the CSP (no inline
   scripts) and fast with OpenRouter's few hundred models (filter on the server).
6. **Staleness and errors.** Bedrock table prices show their `as_of` date; older than 180 days adds a "may be out of
   date" note. If OpenRouter's live call fails, the picker still lists the configured `default_model` and says that
   prices are unavailable. Prices are informational: never block a job on them.
7. **Docs.** `docs/user-guide/llm-backends.md` (how the list is filtered, what the badges mean and where the numbers
   come from, how to update the Bedrock price table), `settings.md`, `docs/dev-guide/adding-a-backend.md` (the new
   `ModelInfo` fields and the filter), README backends section, and a screenshot of the picker
   (`docs/assets/`, captured with the e2e screenshot mechanism and a fake backend that returns priced models).

## Out of scope
- New live verification runs (15g did them); re-measuring quality (unless a recommended model has disappeared, then
  record it and ask Nick).
- The AWS Price List API, currency conversion, spend tracking or budgets per job.
- Local Ollama recommendations (hardware-based, unchanged).

## Tests
- Unit: OpenRouter `/models` parsing with a recorded, trimmed response (pricing, free models, missing pricing,
  non-text models); Bedrock listing with a Stubber (on-demand vs profile-only, access denied, collapse of base and
  profile ids, table prices and `as_of`); the shared filter; the cost estimate (full and map-reduce, from transcript
  and from duration) against hand-computed numbers; recommendations loading and the dropped-id case; both model
  endpoints return the same capable set.
- Web: the picker partials render groups, badges, prices and "Show all"; no price for local backends; error path
  with prices unavailable.
- e2e (Chromium): choose a recommended cloud model on New meeting with a fake priced backend.
- `uv run pytest`, `ruff check`, `ruff format --check`, `mypy src`; `mypy src tests` no worse than `main`.

## Acceptance criteria
- In the real app with Nick's Bedrock backend, "Load models" lists only models his account can call that are capable
  of writing notes; Best value and Best quality are marked with their reason; each shows a price with its `as_of`
  date and an estimated cost for a 60-minute meeting.
- With an OpenRouter key, the list is filtered from hundreds to the capable set, with live prices.
- Settings and New meeting show the same capable set for the same backend.
- "Show all models" and a typed custom id still work; a local Ollama backend shows no prices.

## Phase-specific docs
- ADR-0042 (planning decisions, already written): append the filter rules, the data-file format and the
  tokens-per-minute source; a new ADR for any further choice.
- `CHANGELOG.md`, the docs in Task 7, `THIRD_PARTY_NOTICES.md` only if a dependency is added (none expected),
  `docs/THREAT_MODEL.md` if the picker sends anything new to a provider (it should not: listing models is the only call).

Then the standard close-out checklist.
