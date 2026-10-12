#!/usr/bin/env bash
# pip-audit of the `ml` extra (WhisperX stack) with the advisories accepted in ADR-0014 ignored by
# id. WhisperX 3.8.6 pins torch~=2.8.0 and huggingface-hub<1.0, which blocks the fixed torch and
# transformers releases; nltk has no fixed release. Any NEW advisory still fails.
# Review this list on every WhisperX upgrade (docs/THREAT_MODEL.md, residual risks).
set -euo pipefail
ACCEPTED=(
  PYSEC-2026-3740                                   # nltk 3.10.3 (no fix)
  PYSEC-2025-193 PYSEC-2025-194 PYSEC-2025-195      # torch 2.8.0
  PYSEC-2025-203 PYSEC-2025-204 PYSEC-2025-206
  PYSEC-2026-139 PYSEC-2026-2286
  PYSEC-2025-217 PYSEC-2026-2288 PYSEC-2026-2289    # transformers 4.57.6
  PYSEC-2026-2290 PYSEC-2026-3929 PYSEC-2026-4174
)
args=()
for id in "${ACCEPTED[@]}"; do args+=(--ignore-vuln "$id"); done
uv export --frozen --no-emit-project --no-hashes --extra ml \
  | uvx pip-audit -r /dev/stdin --no-deps --disable-pip "${args[@]}"
