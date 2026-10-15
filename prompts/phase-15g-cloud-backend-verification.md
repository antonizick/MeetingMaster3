# Phase 15g: Live cloud backend verification (AWS Bedrock, OpenRouter)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15d, 15e · **Branch:** `phase-15g-cloud-backend-verification` · **Worktree:** `../MeetingMaster3-phase-15g`

Inserted with `/phase-add` after 15e (ADR-0030, ADR-0034, ADR-0041). The MVP promises "Bedrock and OpenRouter work
with BYOK", but no one has ever sent a real request to either: Phase 08 tested them with a botocore Stubber and
respx only, and Phase 15 deferred the live run because no keys were available. Before release Nick wants them proven
with real accounts, and a user who has never set up AWS must be able to follow the docs to a working Bedrock
backend. This phase sets up the credentials path (docs plus a way to enter AWS keys in Settings), runs both backends
live through the real app and the eval, fixes what breaks, and records what it measured. The filtered cloud model
picker, prices and recommendations follow in **15h**, which uses this phase's measurements. It touches
`llm/bedrock.py`, `llm/openai_compat.py`, the Settings backend form and docs, not the Ollama `num_ctx` path, so it
**can run in parallel with 15f** (expect `CHANGELOG.md` / `docs/PERFORMANCE.md` merge conflicts; keep both sides).

## Read first
- `CLAUDE.md`, `prompts/_shared-instructions.md`, `docs/SPECIFICATION.md` §6 (LLM backends, "clear cost/privacy
  notes") and §15 (§15.3 security baseline: masked secrets, cloud egress consent).
- Phase Log entries for Phase 08 (adapters, "a live Bedrock/OpenRouter check needs Nick's keys"), Phase 12 (Settings
  backends UI), Phase 14 (Docker), Phase 15 (consent-bypass fix, "Deferred to the roadmap") and the 2026-10-12
  pre-release fix (ADR-0029, model checks).
- ADR-0004 (backends), ADR-0009 (adapter choices), ADR-0029 (model checks), **ADR-0041** (this phase's decisions).
- `docs/user-guide/llm-backends.md`, `docs/user-guide/settings.md`, `docs/user-guide/install-docker.md`,
  `docs/THREAT_MODEL.md` T-EGRESS, `docs/PRIVACY.md`, `src/meetingmaster3/llm/cloud_recommendations.yaml`.

## Nick's request (verbatim intent, 2026-10-15)
1. "Before release and publication, we need to test the integrations with AWS Bedrock at a minimum, And ideally test
   the open router integrations."
2. On credentials: "I'm flexible here and willing to do what is best practiced but in the past I have used access
   keys and secret access keys so all things being equal it would be ideal to do that. Whatever the methodology is,
   there should be some guidance to the user instructing them in basic terms, how and where they should assert these
   credentials with AWS."
3. (For 15h, recorded here for context) a per-provider model drop-down filtered to capable models, cost guidance, and
   recommendations ("the least expensive model with decent performance" and "the top performing model but it is
   expensive").

## Decisions already made (ADR-0041)
- **Credentials:** a dedicated, least-privilege IAM user with an access key and secret access key, which is what Nick
  has used before. The policy allows only `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`,
  `bedrock:ListFoundationModels`, `bedrock:ListInferenceProfiles` and, if the installed boto3 has the call,
  `bedrock:GetFoundationModelAvailability` (verify; 15h may use it to hide models without access) (add `aws-marketplace:ViewSubscriptions`/`Subscribe` only if the model's first-use access flow needs it, and say
  so). The AWS profile chain keeps working and is documented as the alternative. Nick revokes or rotates the test key
  after the phase.
- **Test data:** the synthetic eval meetings (`tests/eval/meetings`) and the committed CC fixture, **plus one of
  Nick's real meetings**, which he chose to allow. Ask him which one at run time. Its transcript goes to AWS and,
  if OpenRouter is tested, to OpenRouter. Its notes and comparisons stay in
  `~/.local/share/meetingmaster3/private-eval-15g/` (never in the repo; delete at close-out); only numbers and
  non-identifying observations go into docs.
- **Scope and spend:** Bedrock is required. OpenRouter is tested if Nick provides a key; if he does not, record it as
  untested in `docs/user-guide/llm-backends.md`, the README "Known limitations" and the Phase 16 roadmap input, and do
  not block. **Spend ceiling about USD 5 per provider.** Estimate the cost of each run before starting it (input and
  output tokens × the provider's current price); stop and ask before anything that could pass the ceiling.
- **Prices in the app** (ADR-0042) are 15h's job; this phase only records measured token counts and cost per meeting.

## Goal
A user with an AWS account can follow the docs to a working Bedrock backend using access keys entered in Settings
(or the environment), and both cloud backends are shown to work live through the real app: connection test, model
list, consent, streaming and non-streaming generation, map-reduce, section regeneration, errors, and Docker. Every
bug found is fixed or recorded, and the measured quality, time and cost per meeting are written down for 15h.

## What exists (verified 2026-10-15; re-check before relying on it)
- `src/meetingmaster3/llm/bedrock.py:BedrockBackend`: Converse / ConverseStream in threads (lazy boto3, optional
  `bedrock` extra, boto3 1.43.111 in `uv.lock`); `_session()` uses static keys when both are given, else
  `boto3.Session(profile_name=…)`; **no session-token support** for static keys; `list_models()` lists
  `list_foundation_models(byOutputModality="TEXT")` (ACTIVE only) **plus every inference profile**, with no check
  of model access, on-demand support or context size; `test_connection()` reports the model count and whether
  `default_model` is listed; `context_window()` returns only the configured override. `map_boto_error` maps
  auth/throttle/timeout/context/unavailable codes. `params` are passed as `additionalModelRequestFields`.
- `src/meetingmaster3/llm/registry.py:_bedrock` reads the keys from `settings.secrets.aws_access_key_id` /
  `aws_secret_access_key` (`config/settings.py`, `SecretStr`), i.e. `MM3_SECRETS__AWS_*` or `config.yaml`.
  **There is no Settings UI field for them:** `web/settings_fields.py` only has `secrets.hf_token`, and
  `web/templates/settings/_backend_form.html` says the API key is "Not needed for Ollama or Bedrock". A user who
  has access keys today must edit `config.yaml` or the environment by hand.
- `src/meetingmaster3/llm/budget.py:window_for` falls back to `DEFAULT_CONTEXT_WINDOW` 8192 when a backend cannot
  report a window. **Bedrock never reports one**, so unless `context_window` is set, a 200k-context model gets
  8k-sized map-reduce chunks (slow, more calls, lower quality). `templates/model_check.py:effective_window` applies
  `generation.max_context` only to local backends.
- `src/meetingmaster3/llm/openai_compat.py:OpenAICompatBackend` (kind `openrouter`, preset
  `https://openrouter.ai/api/v1`): plain httpx, SSE streaming, `/models` read for `context_length`; key from the
  backend's `api_key` or `MM3_SECRETS__OPENROUTER_API_KEY`; `text = choice["message"]["content"] or ""` (a reasoning
  model that spends its whole `max_tokens` on reasoning gives an **empty** section with no error; check
  `finish_reason == "length"`); OpenRouter's `HTTP-Referer` / `X-Title` headers are optional (`headers:`).
- Consent: `llm/consent.py`, `templates/stages.py:_check_consent` (job pauses before the first cloud request; Phase 15
  fixed a bypass), `consent_remembered` per backend; tests listed under T-EGRESS in `docs/THREAT_MODEL.md`.
- Eval: `tests/eval/run_eval.py --backend <name> --model <id>` runs against any configured backend (it says "Nothing
  is sent anywhere else", so update that line for cloud runs); `tests/eval/baseline.json` holds the qwen3:8b
  baseline (`python -m tests.eval.baseline`).
- Docker: `docker/Dockerfile` installs `--extra ml --extra bedrock`; `docker/compose.yaml` passes no AWS or
  OpenRouter settings and mounts no `~/.aws`; `.env.example` lists `MM3_SECRETS__OPENROUTER_API_KEY` and
  `MM3_SECRETS__AWS_*` (commented); `docs/user-guide/install-docker.md` says nothing about cloud credentials.
- This machine has **no AWS CLI and no `~/.aws`**; none is needed with access keys. Do not install it.
- `cloud_recommendations.yaml` currently says it "Deliberately contains NO prices"; 15h changes that (ADR-0042).

## Tasks
1. **Credentials guide (plain language).** In `docs/user-guide/llm-backends.md` write "Setting up AWS Bedrock, step by
   step" for someone new to AWS: pick a region; open the Bedrock console and request model access (and that some
   providers need a one-time use-case form or Marketplace subscription); create an IAM user for MeetingMaster3 with
   the least-privilege policy from ADR-0041 (give the JSON); create an access key ("Application running outside AWS");
   where to put it (Settings, the environment `MM3_SECRETS__AWS_ACCESS_KEY_ID` / `..._SECRET_ACCESS_KEY`, or
   `.env` for Docker); how to test (Settings "Test connection", `uv run mm3 llm test`); how to rotate or revoke
   it; never use root keys. Also document the profile/SSO alternative and that temporary credentials (session tokens)
   use the standard AWS chain. Same treatment, shorter, for OpenRouter (create an account, add credit, create a key,
   optional per-key credit limit, where to put it). Link the guide from `settings.md`, `install-docker.md` and the
   README backends section.
2. **AWS keys in Settings.** Add write-only, masked fields for `secrets.aws_access_key_id` and
   `secrets.aws_secret_access_key` (same pattern and security as `secrets.hf_token`: never echoed back, "Saved. Type a
   new key to replace it.", clear option, stored in `config.yaml` mode `0600`, redacted from logs, CSRF-protected),
   shown with the Bedrock backend fields or in the secrets card, with a link to the guide. Fix the backend form hint
   ("Not needed for … Bedrock" becomes "Bedrock uses the AWS keys below or an AWS profile"). Invalidate the registry
   after saving (`BackendRegistry.invalidate()`). Environment variables keep overriding the file; say so in the UI
   when they are set. Tests: masking, round-trip, clear, env precedence, no key in logs or rendered HTML.
3. **Bedrock context window by default.** Stop the silent 8192 fallback for Bedrock: give `BedrockBackend.context_window`
   a small, dated lookup of known model families (for example Anthropic Claude, Amazon Nova, Meta Llama, Mistral,
   checked against the AWS model cards and keyed by model-id prefix so inference profiles like `us.<id>` match), with
   the configured `context_window` still winning, and an unknown model falling back to 8192 with a visible hint in the
   connection test. Put the table in a data file that 15h can extend (for example a `bedrock_models.yaml` next to
   `cloud_recommendations.yaml`). Unit-test the prefix matching.
4. **Live connection and models.** With Nick's keys (from the environment or Settings, never pasted into the repo,
   shell history files or logs): `mm3 llm test`, Settings "Test connection" and "Load models" for Bedrock and, if
   given, OpenRouter. Record what the model list contains (counts; models that are listed but not callable, e.g. no
   access or no on-demand support) as input for 15h's filter. Fix any error mapping that is wrong for real responses
   (each real error message gets a unit test with a recorded, sanitised response).
5. **Live generation through the real app.** For one Bedrock model (a Claude-family model Nick has access to; default
   to a mid-price one) and, if given, one OpenRouter model: run a whole job on the committed CC fixture in the web UI
   (consent prompt appears, decline sends nothing, accept works, `consent_remembered` skips it next time), switch
   templates on the review page, regenerate one section, and run one meeting long enough to use map-reduce (force it
   with a small configured `context_window` if needed). Check streaming and non-streaming, `finish_reason`, usage
   tokens, an empty or truncated answer (fix: a `length` finish or empty text becomes a clear `MM3Error`, not an empty
   section), throttling/retry behaviour, and that no request or response body is logged above DEBUG. Use a
   `network`-marked pytest module (`tests/integration/test_live_cloud.py`, skipped unless `MM3_LIVE_BEDROCK=1` /
   `MM3_LIVE_OPENROUTER=1`) for the repeatable part, so the run can be repeated before release.
6. **Eval and the real meeting.** Run `tests/eval/run_eval.py` with the Bedrock model on the synthetic meetings (all 23
   templates if the cost estimate fits the ceiling, otherwise Default Notes, Executive Summary and the five
   type-specific checks, saying which) and the same for OpenRouter if given. Compare with `tests/eval/baseline.json`;
   record pass counts, mean time and **input/output tokens and cost per note**. Then generate Default Notes for Nick's
   chosen real meeting with each cloud model and with `qwen3:8b`, and give Nick a short private comparison (in the
   private-eval folder) to judge. Do not change the qwen3:8b baseline; store the cloud results as a separate, dated
   section (for example `tests/eval/cloud-results.md` or a `cloud` block in the baseline file, without transcript
   text).
7. **Docker.** Document and verify passing the cloud keys to the container (`.env` with `env_file:` or
   `environment:` passthrough in `docker/compose.yaml`; optionally a read-only `~/.aws` mount for profile users,
   commented out), run one Bedrock note from the GPU or CPU container, and confirm nothing else leaves the container
   (consent still applies).
8. **Record for 15h and the release.** In the ADR: which models were tried, which worked, measured quality, time and
   cost per meeting, list quirks (models without on-demand access, inference-profile-only models, reasoning-token
   behaviour on OpenRouter). Update `docs/THREAT_MODEL.md` (AWS keys in Settings: T-SECRETS or a new row with code
   and tests), `docs/PRIVACY.md` if the wording about cloud use changes, and remove "live Bedrock/OpenRouter run" from
   the Phase 16 deferred items (or keep only OpenRouter if it was not tested).

## Out of scope
- The filtered cloud model drop-down, prices and recommendations (15h).
- New backend kinds, Bedrock API-key (bearer token) auth, AWS Price List API, installing the AWS CLI.
- Changing the qwen3:8b baseline, local generation, `num_ctx` (15f), templates or prompts (unless a template
  fails only on cloud models because of a real bug; record and ask).

## Tests
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`; `mypy src tests` error
  count no higher than `main`.
- New unit tests: AWS key fields (masking, clear, env precedence, logs), Bedrock context lookup, empty/length answer
  errors, every newly mapped real error.
- `MM3_LIVE_BEDROCK=1 uv run pytest -m network tests/integration/test_live_cloud.py` (and `MM3_LIVE_OPENROUTER=1`),
  run live and recorded in the Phase Log with the date, models and spend.

## Acceptance criteria
- Following only `docs/user-guide/llm-backends.md`, an IAM user's access keys entered in Settings give a passing
  "Test connection" for Bedrock; keys never appear in the page, the API, logs or `git diff`.
- A whole job on the CC fixture writes a note to the vault through Bedrock in the web UI, after the consent prompt;
  template switch and section regeneration work; a declined consent sends nothing.
- A long meeting runs through map-reduce on Bedrock with the right context window (not 8192) without a manual
  `context_window`.
- The eval results, tokens and cost per note for each tested cloud model are recorded; total spend stayed under the
  ceiling (stated).
- OpenRouter is either verified the same way or explicitly recorded as untested in the docs and roadmap input.
- One Bedrock note was produced from the Docker container.

## Phase-specific docs
- ADR-0041 (planning decisions, already written): append "Results" (models, measurements, spend, quirks); a new ADR
  for any further choice (for example the context-window table, the empty-answer error).
- `docs/user-guide/llm-backends.md` (the step-by-step guides), `settings.md`, `configuration.md` (new secret fields),
  `install-docker.md`, `.env.example`, `docker/compose.yaml`, README (backends, known limitations), `docs/PERFORMANCE.md`
  (a "Cloud backends" section), `docs/THREAT_MODEL.md`, `docs/PRIVACY.md`, `SECURITY.md` if the secret handling text
  changes, `CHANGELOG.md`.
- Prompt for 15h: correct anything this phase changed (data file names, model list findings, measured models).
- No host changes are expected; if any are made, document them in OSMods.
- At close-out remind Nick to revoke or rotate the test access key and OpenRouter key if he does not want to keep them.

Then the standard close-out checklist.
