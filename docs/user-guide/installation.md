# Installation (native, development)

MeetingMaster3 is pre-alpha: today the app is a skeleton (home page and `/healthz`). Docker Compose
arrives in Phase 14.

## Requirements
- Linux (developed on Arch-based Omarchy).
- [uv](https://docs.astral.sh/uv/). It downloads and manages Python 3.12 for you, so the system
  Python version does not matter. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  (installs to `~/.local/bin`, no sudo) or `sudo pacman -S uv`.
- ffmpeg (needed from Phase 04 onward).

## Install and run
```bash
git clone <repo-url> MeetingMaster3
cd MeetingMaster3
uv sync                 # creates .venv with Python 3.12 and the locked dependencies
uv run mm3 serve        # http://127.0.0.1:8765/
```
Open `http://127.0.0.1:8765/`. `http://127.0.0.1:8765/healthz` returns `{"status": "ok", ...}`.

The server binds to the loopback address only. Binding elsewhere (`--host 0.0.0.0`) prints a warning,
because the app has no login: anyone who can reach the port can read your meetings. See
[`../../SECURITY.md`](../../SECURITY.md).

## Where files go
`uv run mm3 config path` prints the config file and data, cache and model directories
(see [configuration.md](configuration.md)).

## Uninstall
Delete the clone (including `.venv`) and, if you want to remove app data,
`~/.config/meetingmaster3`, `~/.local/share/meetingmaster3` and `~/.cache/meetingmaster3`.
