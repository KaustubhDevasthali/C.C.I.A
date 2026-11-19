"""Command-line entry point for CCIA."""

import argparse
import json
from pathlib import Path
import sys

from ccia.analyzer import GitError, analyze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estimate Python import impact between Git commits.")
    parser.add_argument("base", help="base commit, branch, or tag")
    parser.add_argument("head", help="head commit, branch, or tag")
    parser.add_argument("--repo", type=Path, default=Path("."), help="local Git repository")
    parser.add_argument("--source-root", default=".", help="Python import root (repo-relative)")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.repo, args.base, args.head, args.source_root)
    except (GitError, OSError, ValueError, RecursionError) as error:
        print(f"ccia: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
