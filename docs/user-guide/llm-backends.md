# LLM backends

MeetingMaster3 writes notes with a language model. You choose where that model runs. Everything
is configured under `llm:` in `config.yaml` (see [`configuration.md`](configuration.md)).

| Backend | `kind` | Where your transcript goes |
|---|---|---|
| Ollama on this computer (default) | `ollama` | Stays on this machine |
| Ollama on another machine | `ollama` | Treated as **cloud**: it leaves this machine |
| LM Studio, vLLM, llama.cpp on this computer | `openai_compat` | Stays on this machine |
| OpenRouter | `openrouter` | Sent to OpenRouter and the model provider |
| OpenAI | `openai` | Sent to OpenAI |
| AWS Bedrock | `bedrock` | Sent to AWS (your account and region) |

A backend is "local" only when its address is loopback (`127.0.0.1`, `localhost`) or
`host.docker.internal`. Anything else needs your consent before the app sends a transcript
(see [Privacy](#privacy-and-consent)).

## Ollama (recommended, local)
1. Install Ollama from <https://ollama.com/download> and start it (`ollama serve`, or the system service).
2. Pull a model that fits your GPU, e.g. `ollama pull qwen3:8b`. `uv run mm3 doctor` (from Phase 05) suggests sizes for your hardware.
3. Nothing to configure: with no `llm.backends` entry the app uses `http://127.0.0.1:11434`. To pin a model:
```yaml
llm:
  backends:
    ollama:
      kind: ollama
      default_model: qwen3:8b
```
The app sizes Ollama's context window from the prompt, and asks Ollama to unload its models before
transcription so an 8 GB GPU is not out of memory. It also reads each model's capabilities and context length
from Ollama (`/api/show`). Embedding-only models, and models with too little context to summarise a meeting
(below about 4,096 tokens, after the *Largest context for local models* cap), are not offered. A job that names
one is refused when it is submitted, with `E_LLM_MODEL_UNSUITABLE` or `E_LLM_CONTEXT`. Setting
`default_model`, or ticking *Use this model for new meetings too* after a failure, saves you choosing each time.

In Docker, point `base_url` at `http://host.docker.internal:11434`; Ollama must listen on an address the container can reach.

## OpenRouter
OpenRouter is one account and one key for many providers' models, paid from prepaid credit.

### Setting up OpenRouter, step by step
1. **Create an account** at <https://openrouter.ai> and sign in.
2. **Add credit:** *Settings → Credits → Add credits*. A few US dollars is plenty to try it: a
   one-hour meeting costs cents on most models (see [PERFORMANCE.md](../PERFORMANCE.md#cloud-backends)
   for what we measured).
3. **Create a key:** *Settings → API Keys → Create key*. Name it `MeetingMaster3`. Optionally set a
   **credit limit** on the key, so a mistake can never spend more than that. Copy the key (it
   starts with `sk-or-`); OpenRouter shows it only once.
4. **Give it to MeetingMaster3**, one of:
   - *Settings → Language models → Add a backend*: kind `openrouter`, paste the key into **API key**
     (write-only, stored in `config.yaml`, readable only by you);
   - or the environment: `export MM3_SECRETS__OPENROUTER_API_KEY=sk-or-...` (in Docker, the `.env`
     file; see [install-docker.md](install-docker.md#cloud-backends-bedrock-openrouter)).
5. **Choose a model:** open the backend, press **Load models**, pick one, **Save backend**, then
   **Test**. OpenRouter reports each model's context window, so long meetings are split correctly.
6. **When you are done** with a key, delete it in *Settings → API Keys*; nothing else needs undoing.

Reasoning models (for example the `…:thinking` variants) can spend a section's whole length allowance
on hidden reasoning and return nothing; the app then stops with a clear `E_LLM_BAD_RESPONSE` instead of
writing an empty section. Prefer a model without reasoning for notes, or turn reasoning off with the
backend's `params` (for OpenRouter: `params: {reasoning: {enabled: false}}`).

```yaml
llm:
  default_backend: openrouter
  backends:
    openrouter:
      kind: openrouter
      default_model: <a model id from "Load models">
      # headers: {HTTP-Referer: "https://your.site", X-Title: "My notes"}   # optional
```

## OpenAI or any OpenAI-compatible server
```yaml
llm:
  backends:
    lmstudio:
      kind: openai_compat
      base_url: http://127.0.0.1:1234/v1     # include /v1
      default_model: <model id>
      context_window: 32768                  # if the server does not report it
```
`kind: openai` is the same with the OpenAI base URL preset and `MM3_SECRETS__OPENAI_API_KEY`.

## AWS Bedrock
Bedrock runs the models inside your own AWS account and region, billed to your AWS bill. The app talks
to it with an **access key pair** that belongs to a dedicated AWS user that may do nothing except call
Bedrock models (ADR-0041). Install the optional extra first if you run from source:
`uv sync --extra bedrock` (the Docker image already has it).

### Setting up AWS Bedrock, step by step
You need an AWS account (<https://aws.amazon.com>, *Create an AWS account*) and about fifteen minutes.
Sign in to the AWS console as the account owner or an administrator for steps 1-4.

1. **Pick a region.** The region menu is at the top right of the console. Use one close to you that
   offers the model you want, for example **US East (N. Virginia) `us-east-1`** or **Europe (Frankfurt)
   `eu-central-1`**. Write it down: MeetingMaster3 needs the same region.
2. **Check the model is available.** Open **Amazon Bedrock** (search "Bedrock" in the top bar) →
   **Model catalog**, find the model (for example *Claude Haiku 5.5*) and open its card. Note:
   - its **model ID** and, under *Programmatic access*, its **inference profile ID**. Many current
     models can only be called through a cross-Region inference profile such as
     `us.anthropic.claude-haiku-5-5` (US) or `global.…`; use that ID in MeetingMaster3.
   - **First use:** Bedrock enables its serverless models for your account automatically on the first
     call, but **Anthropic models ask a one-time use-case question** first: open the model in the
     catalog (or the *Playground*) and submit the short form when Bedrock asks. Models sold by other
     companies through **AWS Marketplace** are subscribed automatically on first use, which is why
     the policy below allows the two `aws-marketplace` actions. If an administrator already used the
     model once in this account, you can remove that statement.
3. **Create a user just for MeetingMaster3.** Open **IAM** → **Users** → **Create user**.
   - User name: `meetingmaster3`. Leave *Provide user access to the AWS Management Console*
     **unticked**: this user never signs in, it only holds a key.
   - Permissions: choose **Attach policies directly** → **Create policy** → **JSON**, paste the policy
     below, name it `MeetingMaster3Bedrock`, create it, then back on the user, refresh, tick it and
     finish **Create user**.

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "CallBedrockModels",
         "Effect": "Allow",
         "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
         "Resource": [
           "arn:aws:bedrock:*::foundation-model/*",
           "arn:aws:bedrock:*:*:inference-profile/*"
         ]
       },
       {
         "Sid": "ListBedrockModels",
         "Effect": "Allow",
         "Action": [
           "bedrock:ListFoundationModels",
           "bedrock:ListInferenceProfiles",
           "bedrock:GetFoundationModelAvailability"
         ],
         "Resource": "*"
       },
       {
         "Sid": "FirstUseOfMarketplaceModels",
         "Effect": "Allow",
         "Action": ["aws-marketplace:ViewSubscriptions", "aws-marketplace:Subscribe"],
         "Resource": "*"
       }
     ]
   }
   ```
   The `*` regions are needed because a cross-Region inference profile may run the model in another
   region of the same geography. The user can read and call models and nothing else: it cannot see
   your other AWS resources, change settings or create users.
4. **Create its access key.** Open the user → **Security credentials** → **Access keys** → **Create
   access key** → choose **Application running outside AWS** → **Create**. You get an **Access key ID**
   (starts with `AKIA`) and a **Secret access key**. Copy both now (or download the `.csv`): AWS never
   shows the secret again. Treat it like a password. **Never create access keys for the root user**
   (the e-mail address you signed up with).
5. **Give the keys to MeetingMaster3**, one of:
   - **Settings → Language models → AWS keys for Bedrock:** paste both, **Save AWS keys**. They are
     write-only (never shown again), stored in `config.yaml` (readable only by you) and removed from
     logs;
   - or the environment, which outranks the file: `MM3_SECRETS__AWS_ACCESS_KEY_ID` and
     `MM3_SECRETS__AWS_SECRET_ACCESS_KEY`;
   - in Docker, the same two variables in the `.env` file (see
     [install-docker.md](install-docker.md#cloud-backends-bedrock-openrouter)).
6. **Add the backend:** Settings → Language models → **Add a backend**: name `bedrock`, kind
   `bedrock`, **Region** from step 1, **Default model** the inference profile ID from step 2 (or press
   **Load models** after saving), tick nothing else, **Save backend**.
7. **Test it:** press **Test** next to the backend (or run `uv run mm3 llm test`). "Connected to
   Bedrock in us-east-1; N text model(s) listed" means the keys and the region work. The first meeting
   then asks your consent before the transcript is sent to AWS.

**If something fails:** `E_LLM_AUTH` "Bedrock refused the request (UnrecognizedClientException)" is a
wrong or deleted key; "(AccessDeniedException)" is a missing permission or a model whose first-use form
or subscription is not done yet (step 2); "model … was not listed" is usually the wrong region or a model
ID where an inference profile ID is needed.

**Rotating or revoking the key:** IAM → Users → `meetingmaster3` → *Security credentials*. To rotate,
create a second key, save it in MeetingMaster3, test, then **Deactivate** and **Delete** the old one
(a user can hold two keys for exactly this). To stop MeetingMaster3 using AWS at once, deactivate or
delete the key, or delete the whole user. Removing the keys in Settings removes them from this computer
only; the key stays valid at AWS until you delete it there.

### Other ways to sign in to AWS
Leave the AWS keys in Settings empty and Bedrock uses the **standard AWS credential chain** instead:
- **an AWS profile:** put the profile name in the backend's **AWS profile** field; the profile is read
  from `~/.aws/config` and `~/.aws/credentials` (set up with the AWS CLI, `aws configure` or
  `aws configure sso` for IAM Identity Center / SSO, which gives short-lived credentials);
- **the standard variables** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and, for **temporary
  credentials**, `AWS_SESSION_TOKEN` (the Settings fields have no session token, so temporary
  credentials always go this way);
- an instance or container role when MeetingMaster3 runs on AWS itself.

Keys saved in Settings (or the `MM3_SECRETS__AWS_*` variables) win over all of these.

### Context window and models
Bedrock cannot report a model's context window, so the app reads it from a dated table of model
families (`src/meetingmaster3/llm/bedrock_models.yaml`: Claude 200k, Nova 128k-300k, Llama 3.1+
128k, …), matching inference profile IDs like `us.anthropic.…` too. Set **Context window** on the
backend only for a model the table does not know: the connection test says so ("context window of
… is not known"), and long meetings are then planned for 8,192 tokens.

```yaml
llm:
  backends:
    bedrock:
      kind: bedrock
      region: us-east-1
      default_model: us.anthropic.claude-haiku-5-5   # an inference profile ID
      # profile: my-profile          # only when not using the AWS keys
      # context_window: 200000       # only for a model the table does not know
```

## Checking it works
```bash
uv run mm3 llm list          # configured backends, local or cloud
uv run mm3 llm test          # connects to each one and checks the default model exists
```
The same tests are available at `POST /api/llm/backends/{name}/test` and the Settings page (Phase 12).
Errors carry a code: `E_LLM_AUTH` (bad key), `E_LLM_UNREACHABLE`, `E_LLM_RATE_LIMIT`, `E_LLM_CONTEXT`
(prompt too long), `E_LLM_TIMEOUT`.

## Privacy and consent
- The first use of a non-local backend in each job needs your confirmation. You can remember it per
  backend with `consent_remembered: true`. Local backends never ask.
- Only the transcript text and prompt are sent, never the audio.
- API keys live in `config.yaml` (mode `0600`) or the environment, are masked in the UI and API, and
  are removed from logs. Request and response bodies are never logged above DEBUG.
- Provider pricing and data-retention policies change. `GET /api/llm/recommendations` lists suggestions
  with links to each provider's pricing page. What a meeting cost in our tests is in
  [PERFORMANCE.md](../PERFORMANCE.md#cloud-backends).
