"""Constructs that make a .env file a program rather than a table.

Two of the six engines run what they find in a value. `bash` obviously does --
`. file` is running the file. The Ruby `dotenv` gem does too, and that one
surprises people, because it looks like a parser and is named like a parser.

envdrift decides whether to hand your file to those two by looking at the raw
text, not at what a parser made of it. It deliberately does not try to work out
whether the quoting around a `$(` renders it inert: whether a given quote
disables expansion is precisely the thing the parsers disagree about, so
answering it would mean picking one parser's opinion to gate the comparison
that is supposed to reveal it. Conservative, and occasionally conservative
about a `$(` that nothing would ever have run.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Human names for the constructs engines declare in `Engine.executes`.
CONSTRUCTS = {
    "$(": "command substitution `$(...)`",
    "`": "backtick substitution",
}


@dataclass(frozen=True)
class Hazard:
    construct: str
    line_no: int
    line: str

    @property
    def description(self) -> str:
        return CONSTRUCTS.get(self.construct, self.construct)


def scan(text: str, constructs: tuple[str, ...] = ("$(", "`")) -> list[Hazard]:
    """Every line of the raw file that contains an executable construct."""
    found: list[Hazard] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # A whole-line comment is one of the few things every engine here
            # agrees about, including bash.
            continue
        for construct in constructs:
            if construct in line:
                found.append(Hazard(construct, line_no, line.rstrip("\r")))
    return found


def held_back_reason(engine, hazards: list[Hazard]) -> str | None:
    """Why this engine should not be run against this file, if it should not."""
    if not engine.executes:
        return None
    hits = [h for h in hazards if h.construct in engine.executes]
    if not hits:
        return None
    where = ", ".join(f"line {h.line_no}" for h in hits[:4])
    if len(hits) > 4:
        where += f", +{len(hits) - 4} more"
    return f"would execute {hits[0].description} at {where}; re-run with --unsafe to allow it"
