"""envdrift's command line.

Exit codes:
  0  every parser that read the file agreed about every key
  1  the parsers disagree, or some read the file and others rejected it
  2  envdrift could not do its job (no such file, no engines, bad arguments)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, compare, hazards, report
from .engines import BY_NAME, ENGINES

EPILOG = """\
exit status: 0 if the parsers agree, 1 if they drift, 2 if envdrift could not run.

envdrift prints the values it finds, and a .env file is usually full of
secrets. Use --redact when the output is going anywhere you would not paste
the file itself.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="envdrift",
        description="Run every .env parser on the box against the same file, "
        "and show where they disagree.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", nargs="?", help="the .env file to read")
    parser.add_argument(
        "--engines",
        metavar="LIST",
        help="comma-separated subset to ask (default: all of them)",
    )
    parser.add_argument(
        "--list-engines",
        action="store_true",
        help="show every engine and whether it can run here, then exit",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="print every key, not only the ones the parsers disagree about",
    )
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="also run the engines that execute the file's contents",
    )
    parser.add_argument(
        "--redact",
        action="store_true",
        help="print a short digest instead of each value",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--version", action="version", version=f"envdrift {__version__}")
    return parser


def _selected(names: str | None) -> list:
    if not names:
        return list(ENGINES)
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in BY_NAME]
    if unknown:
        known = ", ".join(e.name for e in ENGINES)
        raise SystemExit(
            f"envdrift: no such engine: {', '.join(unknown)}\n"
            f"envdrift: engines are: {known}"
        )
    # Keep the declared order rather than the order they were typed in, so two
    # runs of the same set read the same way.
    return [e for e in ENGINES if e.name in wanted]


def _list_engines(out) -> int:
    width = max(len(e.name) for e in ENGINES)
    for engine in ENGINES:
        why = engine.available()
        status = "ready" if why is None else f"unavailable — {why}"
        out.write(f"{engine.name:<{width}}  {status}\n")
        out.write(f"{'':<{width}}  {engine.what}\n")
        if engine.executes:
            runs = ", ".join(hazards.CONSTRUCTS.get(c, c) for c in engine.executes)
            out.write(f"{'':<{width}}  executes {runs} — held back unless --unsafe\n")
        out.write("\n")
    out.write(
        "An engine's runtime being present does not mean its library is. The\n"
        "`dotenv` gem and the `dotenv` package are only checked when actually run.\n"
    )
    return 0


def main(argv: list[str] | None = None, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)

    if args.list_engines:
        return _list_engines(out)

    if not args.file:
        err.write("envdrift: give me a .env file to read (or --list-engines)\n")
        return 2

    path = Path(args.file)
    if not path.is_file():
        err.write(f"envdrift: {path}: no such file\n")
        return 2

    try:
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        err.write(f"envdrift: {path}: {exc}\n")
        return 2

    engines = _selected(args.engines)
    if not engines:
        err.write("envdrift: no engines selected\n")
        return 2

    found = hazards.scan(text)
    result = compare.run_all(path, engines, found, unsafe=args.unsafe)

    if not result.ran:
        if args.json:
            out.write(report.to_json(result, redact=args.redact))
        else:
            out.write(report.to_text(result, show_all=args.show_all, redact=args.redact))
        err.write("envdrift: no parser could read this file; nothing to compare\n")
        return 2

    if args.json:
        out.write(report.to_json(result, redact=args.redact))
    else:
        out.write(report.to_text(result, show_all=args.show_all, redact=args.redact))

    return 1 if result.drifted else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
