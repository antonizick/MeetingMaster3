"""Upload storage, ffprobe probing, ffmpeg normalisation and Opus re-encoding (R7, R8, S4).

Every subprocess runs from an argument list (never a shell), with ``-nostdin`` and a timeout.
Uploaded files get server-chosen names; the client filename only contributes an allowlisted
extension.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from meetingmaster3.errors import MM3Error

log = logging.getLogger(__name__)

#: Extensions kept from the client filename; anything else is stored as ``.bin``. ffprobe
#: decides what is really accepted, so this list only affects the stored file name.
AUDIO_EXTENSIONS = frozenset(
    {
        "3gp", "aac", "aif", "aiff", "amr", "caf", "flac", "m4a", "m4b", "mka", "mkv", "mov",
        "mp3", "mp4", "mpeg", "mpga", "oga", "ogg", "opus", "wav", "weba", "webm", "wma",
    }
)  # fmt: skip

SAMPLE_RATE = 16_000
PROBE_TIMEOUT = 60.0
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ProbeResult:
    duration_seconds: float
    codec: str
    channels: int
    sample_rate: int
    format_name: str
    has_video: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "codec": self.codec,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "format_name": self.format_name,
            "has_video": self.has_video,
        }


def safe_extension(filename: str | None) -> str:
    """The lower-cased extension of ``filename`` if allowlisted, otherwise ``bin``."""
    if not filename:
        return "bin"
    name = PurePath(filename.replace("\\", "/")).name
    _, dot, ext = name.rpartition(".")
    ext = ext.lower()
    return ext if dot and ext in AUDIO_EXTENSIONS else "bin"


def display_filename(filename: str | None) -> str:
    """The client's base name with control characters removed, for display only (max 255)."""
    name = PurePath((filename or "").replace("\\", "/")).name
    return re.sub(r"[\x00-\x1f\x7f]", "", name)[:255]


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise MM3Error(
            "E_FFMPEG_MISSING",
            f"{name} was not found on PATH; MeetingMaster3 needs ffmpeg to read audio.",
            "Install ffmpeg (Arch: sudo pacman -S ffmpeg; Debian/Ubuntu: sudo apt install "
            "ffmpeg; macOS: brew install ffmpeg), then restart MeetingMaster3.",
            status_code=500,
        )
    return path


def _run(args: list[str], timeout: float, what: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 - argument list, no shell
            args, capture_output=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL
        )
    except subprocess.TimeoutExpired as exc:
        raise MM3Error(
            "E_AUDIO_TIMEOUT",
            f"{what} took longer than {timeout:.0f} s and was stopped.",
            "The file may be damaged or unusually long. Try converting it to WAV or MP3 first.",
            status_code=422,
        ) from exc


def _stderr_tail(proc: subprocess.CompletedProcess[bytes]) -> str:
    text = proc.stderr.decode("utf-8", "replace").strip().splitlines()
    return text[-1][:300] if text else f"exit code {proc.returncode}"


def _not_audio(detail: str) -> MM3Error:
    return MM3Error(
        "E_AUDIO_UNSUPPORTED",
        f"This file does not contain audio that ffmpeg can read ({detail}).",
        "Upload an audio file (MP3, WAV, M4A, FLAC, OGG/Opus, WebM…) or a video with an audio "
        "track.",
        status_code=422,
    )


def probe(path: Path) -> ProbeResult:
    """Describe the first audio stream of ``path``; raise ``E_AUDIO_UNSUPPORTED`` if none."""
    ffprobe = require_tool("ffprobe")
    proc = _run(
        [
            ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
            "--", str(path),
        ],
        PROBE_TIMEOUT,
        "Reading the file's format",
    )  # fmt: skip
    if proc.returncode != 0:
        raise _not_audio(_stderr_tail(proc))
    try:
        info = json.loads(proc.stdout or b"{}")
    except json.JSONDecodeError as exc:
        raise _not_audio("unreadable ffprobe output") from exc
    streams = info.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio:
        raise _not_audio("no audio track")
    a = audio[0]
    fmt = info.get("format") or {}
    duration = _as_float(a.get("duration")) or _as_float(fmt.get("duration")) or 0.0
    if duration <= 0:
        raise _not_audio("zero or unknown duration")
    return ProbeResult(
        duration_seconds=round(duration, 3),
        codec=str(a.get("codec_name") or "unknown"),
        channels=int(a.get("channels") or 0),
        sample_rate=int(_as_float(a.get("sample_rate")) or 0),
        format_name=str(fmt.get("format_name") or ""),
        has_video=any(
            s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
            for s in streams
        ),
    )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _transcode_timeout(duration_seconds: float | None) -> float:
    # ffmpeg decodes far faster than real time; allow real time plus margin.
    return 120.0 + float(duration_seconds or 3600.0)


def _transcode(src: Path, dst: Path, codec_args: list[str], timeout: float, what: str) -> Path:
    ffmpeg = require_tool("ffmpeg")
    tmp = dst.with_name(f".{dst.name}.part")
    args = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1",
        *codec_args, "-f", dst.suffix.lstrip(".").replace("opus", "ogg"), str(tmp),
    ]  # fmt: skip
    try:
        proc = _run(args, timeout, what)
        if proc.returncode != 0:
            raise MM3Error(
                "E_AUDIO_DECODE",
                f"{what} failed: {_stderr_tail(proc)}",
                "The file may be damaged. Try converting it to WAV or MP3 first.",
                status_code=422,
            )
        os.replace(tmp, dst)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    return dst


def normalise(src: Path, dst: Path, duration_seconds: float | None = None) -> Path:
    """Convert ``src`` to 16 kHz mono 16-bit PCM WAV at ``dst`` (written atomically)."""
    return _transcode(
        src,
        dst,
        ["-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le"],
        _transcode_timeout(duration_seconds),
        "Normalising the audio",
    )


def encode_opus(
    src: Path, dst: Path, bitrate_kbps: int = 24, duration_seconds: float | None = None
) -> Path:
    """Re-encode ``src`` to mono Opus (speech-tuned) in an Ogg container at ``dst``."""
    return _transcode(
        src,
        dst,
        ["-ac", "1", "-c:a", "libopus", "-b:a", f"{bitrate_kbps}k", "-application", "voip"],
        _transcode_timeout(duration_seconds),
        "Compressing the audio for retention",
    )


class UploadTooLarge(MM3Error):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            "E_UPLOAD_TOO_LARGE",
            f"The upload is larger than the limit of {max_bytes // (1024 * 1024)} MB.",
            "Raise audio.max_upload_mb in the settings, or compress the recording (for example "
            "to Opus or MP3) and upload it again.",
            status_code=413,
        )


async def save_stream(chunks: AsyncIterator[bytes], dest: Path, max_bytes: int) -> int:
    """Write ``chunks`` to ``dest`` (mode 0600), enforcing ``max_bytes`` while streaming.

    On any error the partial file is removed. Returns the number of bytes written."""
    written = 0
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in chunks:
                written += len(chunk)
                if written > max_bytes:
                    raise UploadTooLarge(max_bytes)
                fh.write(chunk)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            dest.unlink()
        raise
    return written
