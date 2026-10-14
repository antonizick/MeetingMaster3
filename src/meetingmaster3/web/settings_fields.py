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

TABS: dict[str, tuple[str, tuple[Field, ...]]] = {
    "vault": ("Vault", VAULT_FIELDS),
    "transcription": ("Transcription", TRANSCRIPTION_FIELDS),
    "notes": ("Notes & jobs", NOTES_FIELDS),
    "llm": ("Language models", ()),
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
