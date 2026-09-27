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
from .redact import SALT_ENV, Redactor

EPILOG = f"""\
exit status: 0 if the parsers agree, 1 if they drift, 2 if envdrift could not run.

envdrift prints the values it finds, and a .env file is usually full of
secrets. --redact replaces each value with a digest keyed by a random per-run
salt, which separates the outcomes without disclosing them. Digests from two
runs are unrelated unless you set {SALT_ENV} to a secret of your own,
which makes them comparable to anyone holding that salt.

--redact is not an encryption of your file. It withholds the values; the key
names, the line numbers and the shape of the disagreement are all still there.
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
        help="print a keyed digest instead of each value",
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
        raise ValueError(
            f"no such engine: {', '.join(unknown)}\nenvdrift: engines are: {known}"
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

    # Argument errors before filesystem errors: a typo in --engines should be
    # reported as a typo, not hidden behind a path that also happens to be wrong.
    try:
        engines = _selected(args.engines)
    except ValueError as exc:
        err.write(f"envdrift: {exc}\n")
        return 2
    if not engines:
        err.write("envdrift: no engines selected\n")
        return 2

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

    found = hazards.scan(text)
    result = compare.run_all(path, engines, found, unsafe=args.unsafe)

    redactor = Redactor.build() if args.redact else None

    if args.json:
        out.write(report.to_json(result, redactor=redactor))
    else:
        out.write(report.to_text(result, show_all=args.show_all, redactor=redactor))

    # One engine agreeing with itself is not agreement. Exiting 0 there would
    # report a box with nothing installed on it as a clean bill of health, which
    # is the failure this tool would be most embarrassed by.
    if len(result.ran) < 2 and not result.split_on_validity:
        if not result.ran:
            err.write("envdrift: no parser read this file; nothing to compare\n")
        else:
            err.write(
                f"envdrift: only {result.ran[0].engine} read this file; "
                "nothing to compare it against\n"
            )
        return 2

    return 1 if result.notable else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
