"""Build the header logo from a source photo with ImageMagick (Phase 15a, ADR-0032).

    uv run python scripts/make_logo.py ~/Pictures/wiz.jpg
    uv run python scripts/make_logo.py SOURCE --crop 340x430+320+32 --out DIR

Crops the source (the default box is the wizard's head and crystal ball in ``wiz.jpg``, with no
background faces), rounds the corners and writes ``logo.webp``, ``logo@2x.webp``, ``logo.png``
and ``logo@2x.png`` for a 40 px high display. ``-strip`` removes all metadata (EXIF, ICC, GIMP
comments). Needs ImageMagick 7 (``magick``) on the PATH; it adds no Python dependency. The source
image itself is never committed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_CROP = "340x430+320+32"
HEIGHT = 40
"""CSS pixels; the 2x files are twice this."""
RADIUS = 0.2
"""Corner radius as a share of the width."""
OUT = Path(__file__).parents[1] / "src" / "meetingmaster3" / "web" / "static" / "brand"


def parse_crop(text: str) -> str:
    if not re.fullmatch(r"\d+x\d+\+\d+\+\d+", text):
        raise argparse.ArgumentTypeError("use WxH+X+Y, for example 340x430+320+32")
    return text


def commands(source: Path, crop: str, out: Path) -> list[list[str]]:
    w, h = (int(v) for v in crop.split("+")[0].split("x"))
    cmds = []
    for factor, suffix in ((1, ""), (2, "@2x")):
        height = HEIGHT * factor
        width = round(w * HEIGHT / h) * factor  # 2x is exactly twice 1x
        r = round(width * RADIUS)
        for ext, opts in (("webp", ["-quality", "86", "-define", "webp:method=6"]), ("png", [])):
            cmds.append(
                [
                    "magick", str(source), "-strip", "-crop", crop, "+repage",
                    "-resize", f"{width}x{height}!", "-alpha", "set",
                    "(", "-size", f"{width}x{height}", "xc:none", "-fill", "white",
                    "-draw", f"roundrectangle 0,0 {width - 1},{height - 1} {r},{r}", ")",
                    "-compose", "DstIn", "-composite", "-strip", *opts,
                    str(out / f"logo{suffix}.{ext}"),
                ]
            )  # fmt: skip
    return cmds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("--crop", type=parse_crop, default=DEFAULT_CROP)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if shutil.which("magick") is None:
        ap.error("ImageMagick 7 ('magick') is not on the PATH")
    args.out.mkdir(parents=True, exist_ok=True)
    for cmd in commands(args.source, args.crop, args.out):
        subprocess.run(cmd, check=True)  # noqa: S603 - fixed program, arguments from the CLI
        print(cmd[-1], Path(cmd[-1]).stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
