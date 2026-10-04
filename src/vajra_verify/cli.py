"""Command-line interface: `vajra verify`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__, gitsrc
from .analyze import analyze
from .diffparse import DiffParseError, parse_diff
from .render import render_json, render_receipt
from .rules import load_doc_texts

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 2
DEFAULT_OUTPUT_DIR = ".vajra-verify"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # argparse exits 2 on usage errors
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"vajra: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="vajra",
        description="Local, deterministic change receipts for git diffs. No network access.",
    )
    parser.add_argument("--version", action="version", version=f"vajra-verify {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    verify = sub.add_parser(
        "verify", help="Produce a change receipt for a diff.",
        description=("Analyze a diff and print a change receipt. With no source flag, "
                     "analyzes unstaged working-tree changes (git diff)."),
    )
    source = verify.add_mutually_exclusive_group()
    source.add_argument("--base", metavar="REF",
                        help="Analyze `git diff REF...HEAD` (e.g. origin/main).")
    source.add_argument("--staged", action="store_true",
                        help="Analyze staged changes (`git diff --cached`).")
    source.add_argument("--diff", metavar="PATH", help="Parse a saved unified-diff file.")
    verify.add_argument("--strict", action="store_true",
                        help="Block the merge gate (exit 1) on MEDIUM risk as well as HIGH.")
    verify.add_argument("--output-dir", metavar="DIR", default=DEFAULT_OUTPUT_DIR,
                        help=f"Where to write receipt.md and receipt.json "
                             f"(default: {DEFAULT_OUTPUT_DIR}).")
    verify.add_argument("--repo-root", metavar="DIR",
                        help="Checkout to search for .env.example/.env.sample/README when "
                             "checking config drift (default: git top-level for live diffs; "
                             "none for --diff).")
    return parser


def _fail(message: str) -> int:
    print(f"vajra: error: {message}", file=sys.stderr)
    return EXIT_USAGE


def run_verify(args: argparse.Namespace) -> int:
    repo_root: Path | None = Path(args.repo_root) if args.repo_root else None
    if args.repo_root and not repo_root.is_dir():  # type: ignore[union-attr]
        return _fail(f"--repo-root is not a directory: {args.repo_root}")

    try:
        if args.diff is not None:
            try:
                text = Path(args.diff).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return _fail(f"cannot read diff file {args.diff}: {exc.strerror or exc}")
            branch = f"n/a (saved diff: {args.diff})"
            source: dict[str, object] = {"mode": "diff", "path": args.diff}
        else:
            if args.base is not None:
                if args.base.startswith("-"):
                    return _fail(f"invalid --base ref: {args.base}")
                text = gitsrc.diff_against_base(args.base)
                source = {"mode": "base", "base": args.base}
            elif args.staged:
                text = gitsrc.diff_staged()
                source = {"mode": "staged"}
            else:
                text = gitsrc.diff_working_tree()
                source = {"mode": "working-tree"}
            branch = gitsrc.current_branch()
            if repo_root is None:
                repo_root = gitsrc.repo_root()
        diff = parse_diff(text)
    except gitsrc.GitError as exc:
        return _fail(str(exc))
    except DiffParseError as exc:
        return _fail(f"could not parse diff: {exc}")

    report = analyze(diff, branch=branch, source=source, strict=args.strict,
                     doc_texts=load_doc_texts(repo_root))
    receipt = render_receipt(report)

    out_dir = Path(args.output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "receipt.md").write_text(receipt, encoding="utf-8")
        (out_dir / "receipt.json").write_text(render_json(report), encoding="utf-8")
    except OSError as exc:
        return _fail(f"cannot write receipt to {out_dir}: {exc.strerror or exc}")

    sys.stdout.write(receipt)
    sys.stdout.flush()
    print(f"vajra: wrote {out_dir / 'receipt.md'} and {out_dir / 'receipt.json'}",
          file=sys.stderr)
    return EXIT_BLOCKED if report.gate == "BLOCKED" else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "verify":
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    return run_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
