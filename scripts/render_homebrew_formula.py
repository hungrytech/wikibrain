#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = (
    ROOT / "packaging" / "homebrew" / "Formula" / "wikibrain.rb.in"
)
DEFAULT_OUTPUT = ROOT / "Formula" / "wikibrain.rb"


def sha256(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("SHA-256 must be 64 lowercase hex characters")
    return value


def https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise argparse.ArgumentTypeError("source URL must be an absolute HTTPS URL")
    return value


def owner_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", value):
        raise argparse.ArgumentTypeError("invalid GitHub owner")
    return value


def version(value: str) -> str:
    normalized = value.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", normalized):
        raise argparse.ArgumentTypeError("version must be SemVer")
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a release-ready Homebrew Formula."
    )
    parser.add_argument("--owner", required=True, type=owner_name)
    parser.add_argument("--version", required=True, type=version)
    parser.add_argument("--source-url", required=True, type=https_url)
    parser.add_argument("--source-sha256", required=True, type=sha256)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    text = args.template.read_text(encoding="utf-8")
    replacements = {
        "@OWNER@": args.owner,
        "@VERSION@": args.version,
        "@SOURCE_URL@": args.source_url,
        "@SOURCE_SHA256@": args.source_sha256,
    }
    for marker, value in replacements.items():
        text = text.replace(marker, value)
    leftovers = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if leftovers:
        raise SystemExit(f"unresolved template markers: {', '.join(leftovers)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
