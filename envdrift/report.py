"""Rendering. Text for a person, JSON for anything else."""

from __future__ import annotations

import json

from .compare import ABSENT, VALUELESS, Comparison, KeyRow, Outcome, _Sentinel
from .redact import DIGEST_CHARS, SALT_ENV, Redactor

MAX_VALUE = 120


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


def show(outcome: Outcome, redactor: Redactor | None = None, baseline: int | None = None) -> str:
    if isinstance(outcome, _Sentinel):
        return outcome.label
    if redactor is not None:
        # Relative length, not absolute. What a reader needs from a redacted
        # row is "these two outcomes differ, and by how much" -- a trailing \r
        # or an expanded \n shows up as +1. The absolute length was never the
        # useful half, and it narrows the search for the value itself.
        extra = ""
        if baseline is not None and len(outcome) > baseline:
            extra = f", +{_plural(len(outcome) - baseline, 'char')}"
        return f"<{redactor.digest(outcome)}{extra}>"
    text = repr(outcome)
    if len(text) > MAX_VALUE:
        return text[: MAX_VALUE - 4] + "..." + text[-1]
    return text


def _baseline_length(row: KeyRow) -> int | None:
    """The shortest real value for this key, which every other one is measured from."""
    lengths = [len(g.outcome) for g in row.groups if not isinstance(g.outcome, _Sentinel)]
    return min(lengths) if lengths else None


def to_text(cmp: Comparison, show_all: bool = False, redactor: Redactor | None = None) -> str:
    lines: list[str] = []
    total_engines = len(cmp.ran) + len(cmp.errored) + len(cmp.unavailable) + len(cmp.held_back)
    head = f"{cmp.path} — {_plural(len(cmp.rows), 'key')}, "
    head += f"{len(cmp.ran)} of {total_engines} parsers read it"
    lines.append(head)

    rows = cmp.rows if show_all else cmp.disagreements
    if rows:
        lines.append("")
    for row in rows:
        lines.extend(_render_row(row, redactor))

    if redactor is not None and rows:
        # Right under the rows it explains, because a reader meeting
        # `<a3f9c1d2, +2 chars>` for the first time needs it there.
        lines.append("")
        lines.extend(redactor.explain())

    versioned = [r for r in sorted(cmp.ran, key=_by_name) if r.version]
    if versioned:
        # Worth a line: the Ruby dotenv gem stopped expanding \n inside double
        # quotes between 2.8 and 3.2, so "ruby-dotenv said X" is only half an
        # answer without knowing which ruby-dotenv.
        lines.append("")
        lines.append(
            "parsers: " + ", ".join(f"{r.engine} {r.version}" for r in versioned)
        )

    noted = [r for r in sorted(cmp.ran, key=_by_name) if r.note]
    if noted:
        lines.append("")
        lines.append("read the file, and complained")
        width = max(len(r.engine) for r in noted)
        for result in noted:
            lines.append(f"  {result.engine:<{width}}  {result.note}")

    executed = _executed_lines(cmp)
    if executed:
        lines.append("")
        lines.append("executed, not read")
        lines.extend(executed)

    for title, results, attr in (
        ("rejected the file", cmp.errored, "error"),
        ("held back", cmp.held_back, "held_back"),
        ("not available", cmp.unavailable, "unavailable"),
    ):
        if not results:
            continue
        lines.append("")
        lines.append(title)
        width = max(len(r.engine) for r in results)
        for result in sorted(results, key=lambda r: r.engine):
            lines.append(f"  {result.engine:<{width}}  {getattr(result, attr)}")

    lines.append("")
    if len(cmp.ran) < 2 and not cmp.split_on_validity:
        # One parser reading a file that another rejected is a comparison, and
        # the most interesting one there is -- so it does not count as "nothing
        # to compare" even though only one engine produced any keys.
        lines.append(
            "fewer than two parsers read this file, so there was nothing to compare"
        )
    else:
        summary = []
        if cmp.disagreements:
            n = len(cmp.disagreements)
            summary.append(
                f"{n} of {_plural(len(cmp.rows), 'key')} "
                f"{'differs' if n == 1 else 'differ'} between parsers"
            )
        if cmp.split_on_validity:
            summary.append(
                f"{_plural(len(cmp.errored), 'parser')} rejected the file that "
                f"{_plural(len(cmp.ran), 'parser')} read"
            )
        if not cmp.drifted:
            summary.append(
                f"{_plural(len(cmp.ran), 'parser')} agreed on every one of "
                f"{_plural(len(cmp.rows), 'key')}"
            )
        if cmp.held_back:
            summary.append(
                f"{_plural(len(cmp.held_back), 'parser')} held back from a file "
                f"{'it' if len(cmp.held_back) == 1 else 'they'} would execute"
            )
        lines.append("; ".join(summary))
    return "\n".join(lines) + "\n"


def _executed_lines(cmp: Comparison) -> list[str]:
    """Name the lines some engine runs rather than reads.

    Worth saying out loud even when the engine was held back, and especially
    when it was not: under --unsafe the only trace of an executed `$(...)` is a
    value that quietly differs from the four parsers that left it alone.
    """
    from .engines import BY_NAME

    considered = [r.engine for r in cmp.ran] + [r.engine for r in cmp.held_back]
    lines = []
    for hazard in cmp.hazards:
        runners = [
            name
            for name in considered
            if hazard.construct in getattr(BY_NAME.get(name), "executes", ())
        ]
        if not runners:
            continue
        lines.append(
            f"  line {hazard.line_no}  {hazard.description}  —  {', '.join(sorted(runners))}"
        )
    return lines


def _render_row(row: KeyRow, redactor: Redactor | None) -> list[str]:
    baseline = _baseline_length(row) if redactor is not None else None
    if row.agreed:
        return [f"  {row.key}  =  {show(row.groups[0].outcome, redactor, baseline)}"]
    lines = [f"  {row.key}  —  {_plural(len(row.groups), 'outcome')}"]
    width = max(len(show(g.outcome, redactor, baseline)) for g in row.groups)
    width = min(width, MAX_VALUE)
    for group in row.groups:
        rendered = show(group.outcome, redactor, baseline)
        lines.append(f"      {rendered:<{width}}   {', '.join(group.engines)}")
    return lines


def _by_name(result):
    return result.engine


def to_json(cmp: Comparison, redactor: Redactor | None = None) -> str:
    def outcome_json(outcome: Outcome, baseline: int | None):
        if outcome is ABSENT:
            return {"kind": "absent"}
        if outcome is VALUELESS:
            return {"kind": "valueless"}
        if redactor is not None:
            return {
                "kind": "value",
                "digest": redactor.digest(outcome),
                "longer_by": len(outcome) - baseline if baseline is not None else 0,
            }
        return {"kind": "value", "value": outcome}

    payload = {
        "path": cmp.path,
        "drifted": cmp.drifted,
        "notable": cmp.notable,
        "keys": [
            {
                "key": row.key,
                "agreed": row.agreed,
                "outcomes": [
                    {
                        "outcome": outcome_json(
                            g.outcome, _baseline_length(row) if redactor is not None else None
                        ),
                        "engines": list(g.engines),
                    }
                    for g in row.groups
                ],
            }
            for row in cmp.rows
        ],
        "engines": {
            "ran": [
                {"engine": r.engine, "version": r.version, "note": r.note}
                for r in sorted(cmp.ran, key=_by_name)
            ],
            "rejected": [
                {"engine": r.engine, "error": r.error} for r in sorted(cmp.errored, key=_by_name)
            ],
            "held_back": [
                {"engine": r.engine, "reason": r.held_back}
                for r in sorted(cmp.held_back, key=_by_name)
            ],
            "unavailable": [
                {"engine": r.engine, "reason": r.unavailable}
                for r in sorted(cmp.unavailable, key=_by_name)
            ],
        },
        "hazards": [
            {"line": h.line_no, "construct": h.construct, "description": h.description}
            for h in cmp.hazards
        ],
    }
    if redactor is not None:
        # Present only when redacting, and it says which salt, because a
        # consumer diffing two reports cannot otherwise tell a changed value
        # from a changed key.
        payload["redaction"] = {
            "digest": f"hmac-sha256-{DIGEST_CHARS}",
            "salt": SALT_ENV if redactor.from_env else "random-per-run",
            "comparable_across_runs": redactor.from_env,
            "length": "relative-to-shortest-outcome-per-key",
        }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"
