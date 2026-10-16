# Cloud backend results (Phase 15g, 2026-10-15)

Live runs of the generation eval (`tests/eval/run_eval.py --cloud`) against AWS Bedrock (us-east-1) and
OpenRouter with Nick's own keys. Only the synthetic eval meetings (`tests/eval/meetings/`) and the long
synthetic all-hands were sent; no transcript text is stored here. The local baseline (`baseline.json`,
qwen3:8b) is unchanged. ADR-0041 "Results" summarises this file; `docs/PERFORMANCE.md#cloud-backends` has
the short version.

**How to read it.** *Pass* = the note passed every check in `tests/eval/checker.py` (rescored with the final
checker). *Errors* = the model returned nothing usable (`E_LLM_BAD_RESPONSE`). Times are wall-clock per note
(they depend on the provider's load that day). Tokens are means per note as the provider reported them. Cost
uses Anthropic's list prices, assumed equal on Bedrock and OpenRouter (USD per 1M tokens in/out: Haiku 5.5
0.10/0.50, Sonnet 5.5 2/10, Opus 5.5 4/20); non-Claude runs were not priced.

## Claude, every template on every eval meeting (75 notes)

| Backend · model | Pass | Errors | Mean time | In tokens | Out tokens | Cost | Failed checks |
|---|---|---|---|---|---|---|---|
| Bedrock `us.anthropic.claude-haiku-5-5` | 73/75 | 0 | 17.3 s | 18,669 | 2,581 | $0.24 | actions_captured 1, no_invented_owners 1, nothing_forbidden 1 |
| OpenRouter `anthropic/claude-haiku-5.5` | 74/75 | 0 | 18.0 s | 18,701 | 2,540 | $0.24 | nothing_forbidden 1 |
| Bedrock `us.anthropic.claude-sonnet-5-5` | 71/75 | 0 | 26.0 s | 18,669 | 2,994 | $5.05 | nothing_forbidden 2, actions_captured 1, no_invented_owners 1, detailed_paragraphs 1 |

`nothing_forbidden` is the family detail in the interview and intro-call meetings that the template says to
leave out. The action misses are one launch-video owner (Haiku) and one retrospective action (Sonnet). Sonnet
5.5 ran before the final checkbox fix, so its notes are rescored, not regenerated.

## Opus 5.5 subset (27 notes: 7 templates)

| Backend · model | Pass | Errors | Mean time | In tokens | Out tokens | Cost | Failed checks |
|---|---|---|---|---|---|---|---|
| Bedrock `us.anthropic.claude-opus-5-5` | 9/27 | 0 | 42.4 s | 19,933 | 3,600 | $4.10 | detailed_prose 11, detailed_paragraphs 9, succinct_short 4, plus 1 each actions_captured, no_invented_owners, nothing_forbidden, limit_succinct-short |

Templates: default-notes, executive-summary, board-governance-minutes, job-interview-notes, retrospective,
sales-client-call, agile-standup. Opus writes the content well but ignores the summary style rules most
(lists or too many paragraphs in Summary Detailed, a long Summary Succinct). Opus 5.5 rejects "thinking off" and
runs at low effort, with 4 096 extra output tokens of room.

## Other model families (7 notes: Default Notes and Executive Summary)

Meetings: launch-sync, budget-checkin, cache-design-review, intro-call-platform-lead.

| Backend · model | Pass | Errors | Mean time | In tokens | Out tokens | Notes |
|---|---|---|---|---|---|---|
| Bedrock `us.meta.llama4-maverick-17b-instruct-v1:0` | 6/7 | 0 | 9.1 s | 14,060 | 1,466 | fastest |
| Bedrock `qwen.qwen3-32b-v1:0` | 6/7 | 0 | 15.1 s | 14,741 | 1,700 | |
| Bedrock `zai.glm-5` | 6/7 | 0 | 42.7 s | 14,033 | 2,407 | window not in the table (8 192 fallback) |
| Bedrock `mistral.mistral-large-2402-v1:0` | 6/7 | 0 | 43.5 s | 16,354 | 2,020 | |
| Bedrock `us.openai.gpt-5.5` | 6/7 | 0 | 53.3 s | 10,134 | 5,321 | rejects temperature; window unknown |
| Bedrock `amazon.nova-lite-v1:0` | 4/7 | 0 | 10.5 s | 15,001 | 1,724 | summary style |
| Bedrock `amazon.nova-micro-v1:0` | 2/7 | 0 | 9.2 s | 16,370 | 1,828 | summary style |
| Bedrock `us.deepseek.r1-v1:0` | 2/7 | 5 | 28.4 s | 14,512 | 4,182 | reasoning-only: empty answers |
| Bedrock `openai.gpt-oss-20b-1:0` | 1/7 | 6 | 22.2 s | 8,724 | 4,084 | reasoning-only: empty answers |
<!-- OPENROUTER-BATCH -->

## Long meeting (map-reduce)

Synthetic all-hands of about 151 800 tokens, Action-Focused template.

| Backend · model | Planned window | Parts | Calls | Time | Tokens in / out | Found (decisions, actions, questions) |
|---|---|---|---|---|---|---|
| Bedrock `us.anthropic.claude-haiku-5-5` | 200 000 (table) | 2 | 9 | 40 s | 263,543 / 6,521 | 6/6, 16/16, 4/5 |
| OpenRouter `anthropic/claude-haiku-5.5` | 200 000 (capped from 1M) | 2 | 9 | 38 s | 263,739 / 6,381 | 6/6, 16/16, 4/5 |

At the flat price this is about $0.03; Haiku 5.5 bills prompts above 100k tokens at the long-context rate
(0.50/2.50), which makes it about $0.09. Without the window table Bedrock would have planned 8 192 tokens and
about 25 parts.

## Live checks (`tests/integration/test_live_cloud.py`, 9 checks per model)

9/9 on Bedrock Haiku 5.5, Sonnet 5.5 and Opus 5.5, and on OpenRouter Haiku 5.5, Sonnet 5.5 and Opus 5.5:
connection and model list, a known window above 8 192, finish reason and token usage, streaming, a cut-off
answer, declined consent sends nothing (zero tokens metered), a whole note on a synthetic meeting, a bad model
id and wrong keys are clear errors.

## Quirks found

- Bedrock lists 188 ids in one account: 95 text foundation models (39 only through an inference profile, 45
  on demand, 4 both, 7 Provisioned-only; 6 legacy excluded) and 99 inference profiles (67 `us.`, 32 `global.`).
- Claude 5.x and GPT-5.x/6 on Bedrock reject `temperature`; the backend drops it after the first refusal.
- Turning thinking off differs per model on Bedrock (Haiku 5.5 and Claude 4.x `disabled`, Sonnet 5.5
  `between_tools`, Opus 5.5 effort `low`); on OpenRouter Haiku 5.5 accepts `reasoning: {enabled: false}`,
  Sonnet and Opus 5.5 say "Reasoning is mandatory" and run at effort `low`.
- OpenRouter routes `qwen/qwen3-32b` to a provider (DeepInfra on the test day) that ignores the reasoning
  switch, so it reasoned through the allowance; Bedrock's Qwen3 32B is fine.
- Fable 5.1 on Bedrock refuses the default data-retention mode ("data retention mode 'default' is not available
  for this model"); not supported by the app.
- Nova rejects an unknown `thinking` field; Mistral 7B and Mixtral on Bedrock reject system prompts.
- Windows unknown to the Bedrock table: GLM, Gemma, Nemotron, OpenAI GPT-5.x/6 (8 192 fallback; set the
  backend's context window).

## Spend

About $13 in total, estimated from the reported token counts (check the AWS bill and the OpenRouter activity
page for the real figure): Bedrock about $12 (Sonnet 5.5 full eval $5.05, Opus subset $4.10, Haiku runs $0.48,
real-meeting comparison about $0.73, long meeting, non-Claude batch and probes about $1.5), OpenRouter about $1
(Haiku eval $0.24, live checks on three Claude models, long meeting, batch). Nick lifted ADR-0041's $5-per-provider
ceiling for Bedrock during the phase.
