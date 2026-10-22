# Settings

Open **Settings** in the top bar. Everything you can set in `config.yaml` is also here, in seven tabs. Changes
take effect immediately (the one exception, noted on the field, needs a restart) and are written to
`config.yaml`, so they survive a restart. If a value is invalid, the field shows why and **nothing** is saved.

> **Environment variables win.** If a setting is also given as an `MM3_*` environment variable, the field says so.
> The variable outranks what you save here. Saving from the screen also writes the live value (including one that
> came from an environment variable) into `config.yaml`, so keep secrets you want to keep out of the file in your
> environment and leave the field alone. Saving normalises the file: YAML comments and key order in `config.yaml`
> are not preserved.

## Vault
The vault folder, the notes folder (`Meetings/{yyyy}/` by default), the templates folder and the audio attachments
folder. All must stay inside the vault. **Copy the audio into the vault** puts the compressed recording next to your
notes and links it from the note (`mm3-audio`), so Obsidian can play it. It is off by default because it makes the vault
larger (about 11 MB per hour) and a synced vault uploads the recordings to your other devices.

## Transcription
Hardware profile (or `auto`), Whisper model, compute type, batch size, device, language, what to do when the audio is
not English, speaker identification, offline mode, and unloading Ollama before transcription. See
[`transcription.md`](transcription.md) and [`hardware.md`](hardware.md) for what each means.

* **Hugging Face token.** Write-only: you can type a new one or tick *Remove the saved value*, but the page never shows the
  stored token. Leaving the field empty keeps it. **Test saved token** checks that the token is valid and that your account
  has accepted the diarization model's terms (the page links to them). It contacts `huggingface.co` only when you press it.
* **Models on this computer** lists what is already downloaded. **Download models** fetches the chosen Whisper model, the
  alignment model and (optionally) the diarization model, with live status; it is the same as `mm3 models download`. It needs
  the transcription engine installed (`uv sync --extra ml`).

## Notes & jobs
The default template, the companion transcript, the context size for local models, reasoning-model "thinking", the first-run template
install, the upload limit, the retained-audio bitrate, how many meetings are processed at once and how often the retention check
runs. The last two need a restart.

Turning off the companion transcript saves space, but a note can then no longer be re-opened to regenerate sections or rename speakers.

## Language models
The backends that write your notes, their connection tests and the recommendations for your computer.

* **Add a backend** (Ollama, OpenAI-compatible, OpenRouter, OpenAI or Bedrock). Fields that do not apply to a kind are ignored.
* **AWS keys for Bedrock:** the access key ID and secret access key of the IAM user you made for MeetingMaster3. Write-only like every key here (never shown again; *Remove the saved value* removes both), stored in `config.yaml`, removed from logs. Leave them empty to use an AWS profile or the standard AWS variables. How to create them: [Setting up AWS Bedrock, step by step](llm-backends.md#setting-up-aws-bedrock-step-by-step); for OpenRouter, [Setting up OpenRouter](llm-backends.md#setting-up-openrouter-step-by-step).
* **API keys are write-only**: type a new key to replace the old one, or tick *Remove the saved key*. A stored key is never displayed.
* **Test** tries the connection. In the form, **Load models** shows a drop-down of the models that can write notes (cloud backends with prices, an estimated cost and Best value / Best quality badges; **Show all models** reveals the rest). Choosing one fills the **Default model** box, which still accepts any id you type. See [Choosing a model](llm-backends.md#choosing-a-model-the-picker-prices-and-recommendations).
* **Remember my consent** (cloud backends) skips the per-meeting question. **Revoke consent** brings the question back (and also withdraws the search-indexing permission below).
* **Allow search indexing with this backend's embeddings** (cloud backends, Phase 15i): only matters if you pick this backend as the embedder in *Search & Ask*. Indexing then sends the full text of every meeting, and each search sends the query, to the provider. Off by default and separate from the consent above. The backend list says *Search indexing allowed* when it is on.
* The **default backend** is what a new meeting uses. You cannot remove the default; choose another first.

## Search & Ask
The meeting index behind the **Search** page (and, from Phase 15j, Ask). Details: [search-and-ask.md](search-and-ask.md).

* **Index meetings for search** (on by default), the **embedding backend** (`auto` = the local Ollama) and **model** (`nomic-embed-text`), and **Index the transcripts too**. *Advanced:* passage size and overlap (apply to all meetings after *Rebuild index*) and how often the vault is checked for edits made in Obsidian.
* The **Meeting index** card shows the embedder (with a *local* or *cloud* badge), the number of meetings, notes, transcripts and passages, how many passages have meaning vectors, the file size and location, the last update, files that could not be indexed, and why meaning vectors are missing if they are (for example "run `ollama pull nomic-embed-text`"). While an update runs it shows a progress bar, the elapsed time and the time left, and a **Stop** button.
* **Update index** reads what changed; **Rebuild index** starts from scratch; **Delete index** removes `search.db` (and its `-wal`/`-shm` files) and turns indexing off until you press Update again. Notes are never touched.

## Privacy
* **Audio retention**: keep forever, for N days (default 90), or delete right after the note is written. Under the form, the page lists
  what the current setting would delete at the next check, and **Delete it now** does it. Pin a meeting's audio on its own page to keep it.
* **Voiceprints**: the opt-in switch, the list of remembered voices (delete one at a time), and **Delete all voiceprints**, which asks you to
  confirm in a second step. The matching threshold and margin are under *Advanced*. See [`speakers.md`](speakers.md).
* **Network exposure** shows the address the app listens on and warns if it is not loopback. It is read-only on purpose: change `server.host`
  in the config file if you really mean to.

## About & diagnostics
The same checks as `mm3 doctor`, the version, and where the config file, data, models, database and logs live. **Copy** puts a path on your
clipboard; **Open the config folder** launches your file manager (native installs only, not in Docker). **Export all app data** downloads a zip of
the database (as JSON), your settings with every secret masked, and each meeting's working files. Audio and voiceprints are not in it.

## Ratings and export
After a note is written, the completion page has a **Download** menu (note, transcript, plain-text transcript, or everything in a zip, with the audio
while it is still kept) and a star rating with an optional comment. Ratings are stored only on this computer; **Feedback (CSV/JSON)** on the About tab
exports them for your own analysis. There is no telemetry, ever.
