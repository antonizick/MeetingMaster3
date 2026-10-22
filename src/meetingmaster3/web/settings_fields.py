"""Declarative description of the editable settings, and the form <-> settings mapping.

Each :class:`Field` is one setting (a dotted path into :class:`Settings`). The Settings screen
renders them with one macro and parses a submitted form with :func:`parse_form`, so adding a
setting to the UI is one line here. Secrets are write-only: the page never receives a value, an
empty field means "unchanged", and a separate *Clear* checkbox removes the stored secret.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import SecretStr

from meetingmaster3.config.editing import get_path
from meetingmaster3.config.settings import Settings

Kind = Literal["text", "opt_text", "int", "opt_int", "float", "bool", "select", "secret"]


@dataclass(frozen=True)
class Field:
    path: str
    label: str
    kind: Kind
    hint: str = ""
    choices: tuple[str, ...] = ()
    advanced: bool = False
    restart: bool = False
    placeholder: str = ""
    warning: str = ""
    """Shown under the field when it is switched on (bool) or always (other kinds)."""

    @property
    def env_var(self) -> str:
        return "MM3_" + self.path.upper().replace(".", "__")


@dataclass
class FieldView:
    spec: Field
    value: Any = ""
    error: str = ""
    secret_set: bool = False
    env_override: bool = False
    choices: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Group:
    title: str
    fields: tuple[Field, ...]
    description: str = ""


VAULT_FIELDS = (
    Field("vault.path", "Vault folder", "text", "The top-level folder of the vault (it contains "
          ".obsidian/).", placeholder="/home/you/Documents/MyVault"),
    Field("vault.output_subfolder", "Notes folder", "text",
          "Inside the vault. You can use {yyyy}, {mm} and {dd}, e.g. Meetings/{yyyy}/."),
    Field("vault.templates_subfolder", "Templates folder", "text",
          "Inside the vault. Built-in templates are copied here; edit them or add your own."),
    Field("vault.attachments_subfolder", "Audio attachments folder", "text",
          "Inside the vault. Used only when “copy audio” below is on."),
    Field("privacy.copy_audio_to_vault", "Copy the audio into the vault", "bool",
          "Obsidian can then play the recording from the note (the mm3-audio property).",
          warning="This makes the vault larger (about 11 MB per hour of audio), and if the vault "
          "is synced, the recordings are uploaded to your other devices and the sync service."),
)  # fmt: skip

TRANSCRIPTION_FIELDS = (
    Field("hardware.profile", "Hardware profile", "select",
          "auto detects the graphics card; pick one to override it.",
          choices=("auto", "cpu", "vram8", "vram16", "vram24plus")),
    Field("transcription.model", "Whisper model", "text",
          "auto uses the recommendation for your hardware. Or a name such as large-v3-turbo.",
          placeholder="auto"),
    Field("transcription.compute_type", "Compute type", "select",
          "auto uses the recommendation.",
          choices=("auto", "float16", "int8_float16", "int8", "float32")),
    Field("transcription.batch_size", "Batch size", "opt_int",
          "1-64. Empty uses the recommendation (halved automatically after an out-of-memory "
          "error)."),
    Field("transcription.device", "Device", "select", choices=("auto", "cuda", "cpu")),
    Field("transcription.language", "Language", "opt_text",
          "A code such as en. Empty detects the language of each recording.", placeholder="en"),
    Field("transcription.on_non_english", "When the audio is not English", "select",
          "ask pauses the job; proceed transcribes in the detected language; abort fails it.",
          choices=("ask", "proceed", "abort")),
    Field("transcription.diarize", "Identify speakers (diarization)", "bool",
          "Needs the gated model below. Off: transcripts have no speaker labels."),
    Field("transcription.offline", "Offline mode", "bool",
          "Never contact Hugging Face. Models must already be downloaded."),
    Field("transcription.unload_ollama", "Unload Ollama before transcribing", "bool",
          "Frees GPU memory for transcription when a local Ollama holds models (spec R5)."),
    Field("transcription.diarization_model", "Diarization model", "text",
          "The gated pyannote pipeline.", advanced=True),
    Field("secrets.hf_token", "Hugging Face token", "secret",
          "A read token, needed once to download the gated diarization model."),
)  # fmt: skip

NOTES_FIELDS = (
    Field("generation.default_template", "Default template", "select",
          "Pre-selected on New meeting. Starting a meeting there with another template "
          "makes that one the default."),
    Field("generation.write_companion", "Write the companion transcript", "bool",
          "A .transcript.md file next to each note.",
          warning="Without it a note cannot be re-opened to regenerate sections or rename "
          "speakers."),
    Field("generation.readable_transcript", "Write a readable transcript", "bool",
          "A '(Transcript).md' file next to each note, laid out like the review screen, with "
          "coloured speaker names. Made from the companion transcript."),
    Field("generation.max_context", "Largest context for local models (tokens)", "int",
          "Longer meetings are summarised in parts. Raise it on GPUs with more memory."),
    Field("generation.think", "Let reasoning models think", "bool",
          "Slower, and can use up a section's length limit."),
    Field("generation.install_templates", "Install built-in templates into the vault", "bool",
          "On first use. Your edited copies are never overwritten."),
    Field("audio.max_upload_mb", "Largest upload (MB)", "int"),
    Field("audio.opus_bitrate_kbps", "Retained audio bitrate (kbit/s)", "int",
          "About 24 kbit/s is 11 MB per hour."),
    Field("jobs.max_concurrent", "Meetings processed at once", "int",
          "GPU stages still run one at a time.", restart=True),
    Field("jobs.prune_interval_hours", "Retention check interval (hours)", "float",
          restart=True),
)  # fmt: skip

PRIVACY_FIELDS = (
    Field("privacy.audio_retention", "Keep the audio", "select",
          "forever, for N days (default 90) after the note is written, or delete right away. "
          "Pin a meeting to keep its audio regardless.",
          choices=("forever", "days", "delete_after_write")),
    Field("privacy.audio_retention_days", "Days to keep it", "int"),
    Field("privacy.voiceprints_enabled", "Remember voices (voiceprints)", "bool",
          "Suggests names for speakers you named before. Voiceprints stay on this computer."),
    Field("speakers.match_threshold", "Voice match threshold", "float",
          "Cosine similarity needed to suggest a name (0-1).", advanced=True),
    Field("speakers.match_margin", "Voice match margin", "float",
          "How far the best match must beat the second best (0-1).", advanced=True),
    Field("speakers.max_embeddings_per_person", "Voice samples kept per person", "int",
          advanced=True),
)  # fmt: skip

AWS_FIELDS = (
    Field("secrets.aws_access_key_id", "AWS access key ID", "secret",
          "Starts with AKIA. From the IAM user you created for MeetingMaster3, never your "
          "root account.", placeholder="AKIA…"),
    Field("secrets.aws_secret_access_key", "AWS secret access key", "secret",
          "Shown once by AWS when you create the access key."),
)  # fmt: skip

SEARCH_FIELDS = (
    Field("search.enabled", "Index meetings for search", "bool",
          "Keeps a search index of every meeting note and transcript in the vault, in the app's "
          "data folder (search.db). Your vault is not changed."),
    Field("search.embedding_backend", "Embedding backend", "select",
          "auto uses the local Ollama, which keeps everything on this computer. A cloud backend "
          "also needs “Allow search indexing” in its settings (Language models)."),
    Field("search.embedding_model", "Embedding model", "text",
          "The model that turns passages into meaning vectors. For Ollama: nomic-embed-text "
          "(run `ollama pull nomic-embed-text` once). Changing it re-embeds every passage.",
          placeholder="nomic-embed-text"),
    Field("search.index_transcripts", "Index the transcripts too", "bool",
          "Finds what was said even when the notes leave it out. Turn off to index notes only."),
    Field("search.chunk_tokens", "Passage size (tokens)", "int",
          "About how much text one search result holds. Applies to all meetings after "
          "Rebuild index.", advanced=True),
    Field("search.chunk_overlap", "Passage overlap (tokens)", "int",
          "Text repeated between neighbouring passages, so a point is not cut in half.",
          advanced=True),
    Field("search.rescan_minutes", "Check the vault every (minutes)", "int",
          "For notes edited in Obsidian. Changes made in MeetingMaster3 are indexed at once.",
          advanced=True),
)  # fmt: skip

ASK_FIELDS = (
    Field("ask.default_backend", "Backend that answers", "select",
          "auto uses the backend that writes your notes. A cloud backend asks for consent on "
          "every question unless “Always allow Ask AI agent” is ticked in its settings."),
    Field("ask.default_model", "Model that answers", "opt_text",
          "Empty uses the backend's default model. You can pick another on the Ask page.",
          placeholder="the backend's default"),
    Field("ask.max_meetings", "Most meetings read per question", "int",
          "Each meeting read is one model call (about 10-40 s with a local model). For a cloud "
          "backend, excerpts of at most this many meetings are sent."),
    Field("ask.keep_history", "Keep every answer", "bool",
          "Saves each answer as a note in the vault (linked to the meetings it used) and lists "
          "it on the Ask page. Off: answers are shown once and not kept."),
    Field("ask.answers_subfolder", "Answers folder in the vault", "text",
          "Where answer notes are written. Existing answers are not moved when you change it.",
          placeholder="MM3 Answers/", advanced=True),
)  # fmt: skip

TABS: dict[str, tuple[str, tuple[Field, ...]]] = {
    "vault": ("Vault", VAULT_FIELDS),
    "transcription": ("Transcription", TRANSCRIPTION_FIELDS),
    "notes": ("Notes & jobs", NOTES_FIELDS),
    "llm": ("Language models", AWS_FIELDS),
    "search": ("Search & Ask", SEARCH_FIELDS + ASK_FIELDS),
    "privacy": ("Privacy", PRIVACY_FIELDS),
    "about": ("About & diagnostics", ()),
}


def view_of(
    settings: Settings,
    f: Field,
    submitted: Mapping[str, str] | None = None,
    errors: Mapping[str, str] | None = None,
    choices: tuple[str, ...] | None = None,
    environ: Mapping[str, str] | None = None,
) -> FieldView:
    """What to render for one field: the submitted text (after a failed save) or the current
    value. A secret's value is never read into the view."""
    env = os.environ if environ is None else environ
    current = get_path(settings, f.path)
    view = FieldView(
        f,
        error=(errors or {}).get(f.path, ""),
        env_override=f.env_var in env,
        choices=choices if choices is not None else f.choices,
    )
    if f.kind == "secret":
        view.secret_set = isinstance(current, SecretStr) and bool(current.get_secret_value())
        return view
    if submitted is not None:  # a failed save: show what the user typed, not the old value
        raw = submitted.get(f.path)
        view.value = (
            (raw is not None and raw not in ("", "0", "false", "off"))
            if (f.kind == "bool")
            else (raw or "")
        )
    elif current is None:
        view.value = ""
    elif f.kind == "bool":
        view.value = bool(current)
    else:
        view.value = str(current)
    return view


def parse_form(
    fields: tuple[Field, ...], form: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Turn submitted strings into a settings patch. Returns ``(patch, errors)``; ``errors``
    only holds type errors here (range and pattern errors come from validation)."""
    patch: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in fields:
        raw = form.get(f.path)
        if f.kind == "bool":
            patch[f.path] = raw is not None and raw not in ("", "0", "false", "off")
        elif f.kind == "secret":
            if form.get(f"clear:{f.path}"):
                patch[f.path] = None
            elif raw and raw.strip():
                patch[f.path] = raw.strip()
        elif raw is None:
            continue
        elif f.kind in ("int", "opt_int"):
            text = raw.strip()
            if not text and f.kind == "opt_int":
                patch[f.path] = None
            else:
                try:
                    patch[f.path] = int(text)
                except ValueError:
                    errors[f.path] = "Enter a whole number."
        elif f.kind == "float":
            try:
                patch[f.path] = float(raw.strip())
            except ValueError:
                errors[f.path] = "Enter a number."
        elif f.kind == "opt_text":
            patch[f.path] = raw.strip() or None
        else:
            patch[f.path] = raw.strip()
    return patch, errors
