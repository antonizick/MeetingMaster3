# Security Policy

## Supported versions
No version has been released yet (pre-alpha). Once releases exist, the latest minor release will be
supported with security fixes.

## Reporting a vulnerability
Please report vulnerabilities **privately**; do not open a public issue.

- Preferred: GitHub private vulnerability reporting (Security tab → "Report a vulnerability") once the
  repository is published.
- Email fallback: _maintainer contact to be confirmed by the project owner before first publication
  (tracked for Phase 16)._

Please include what you found, steps to reproduce, and the version or commit. Do not attach private
audio or personal data.

## Scope
In scope: the MeetingMaster3 application and its Docker packaging, including the web server, file
handling, vault writes, secret handling and any data leaving the machine.
Out of scope: vulnerabilities in third-party models or dependencies (report upstream), and issues
that require an attacker who already has local shell access as the same user.

## Security model summary
The full baseline is in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) section 15.3.

- **Local only by default.** The server binds `127.0.0.1`. Binding elsewhere needs an explicit
  setting and shows a warning. There is **no authentication in the MVP** (single user), so network
  exposure is the main control.
- **Browser-origin attacks.** Host-header allowlist (DNS rebinding), CSRF token and Origin check on
  state-changing requests, `SameSite=Strict` cookies, sanitised rendering and a strict CSP (all
  assets are vendored; no CDN).
- **Filesystem.** Vault writes are confined to the configured vault root (no `..` or symlink
  escapes) and are atomic. Uploads are stored under app data with server-generated names.
- **Secrets.** API keys and the Hugging Face token come from environment variables or a `0600`
  config file; they are never logged, never returned unmasked, never written to the vault.
- **Cloud egress consent.** Cloud LLM backends are clearly badged and need explicit confirmation on
  first use per job. No telemetry, ever.
- **Voiceprints are biometric data.** Opt-in, local only, never written to the vault, listable and
  deletable.
- **Supply chain.** Locked dependencies, `pip-audit` in CI, Dependabot, licence inventory.

## Data the app stores and where
_To be completed as phases land. Final version in Phase 15._

| Data | Location | Added in | Leaves the machine? |
|---|---|---|---|
| Notes and companion transcripts | Your Obsidian vault | Phase 03/09 | Only if your vault syncs |
| Job audio and stage artifacts | `$XDG_DATA_HOME/meetingmaster3/jobs/` | Phase 04 | No |
| Job state, feedback, voiceprints | `$XDG_DATA_HOME/meetingmaster3/mm3.db` | Phase 04/07 | No |
| Config and secrets | `$XDG_CONFIG_HOME/meetingmaster3/config.yaml` (mode `0600`) | Phase 02 | No |
| Model weights | `$XDG_CACHE_HOME/meetingmaster3/models` | Phase 06 | Downloaded in, never out |
| Transcript text sent to an LLM | Selected backend | Phase 08 | **Only for a cloud backend you confirmed** |
