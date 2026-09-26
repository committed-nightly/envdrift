"""Turn a pile of per-engine results into the thing you actually wanted to know.

The unit of disagreement is a key. For each key, engines that read the file are
grouped by the outcome they produced, where an outcome is one of:

  * a string -- the value
  * ABSENT   -- this engine did not produce this key at all
  * VALUELESS -- the engine produced the key with no value, which is not the
    same as an empty string. Compose renders it as null (pass through from the
    host) and python-dotenv as None.

Keeping ABSENT and VALUELESS out of the string space matters: a key that one
parser drops and another sets to "" is a real difference, and collapsing both
to "nothing" would hide it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .engines import Engine, Result
from .hazards import Hazard


class _Sentinel:
    __slots__ = ("label",)

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return self.label

    def __hash__(self) -> int:
        return hash(("envdrift-sentinel", self.label))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sentinel) and other.label == self.label


ABSENT = _Sentinel("<absent>")
VALUELESS = _Sentinel("<no value>")

Outcome = str | _Sentinel


@dataclass(frozen=True)
class Group:
    """One outcome, and every engine that produced it."""

    outcome: Outcome
    engines: tuple[str, ...]


@dataclass(frozen=True)
class KeyRow:
    key: str
    groups: tuple[Group, ...]

    @property
    def agreed(self) -> bool:
        return len(self.groups) == 1

    @property
    def present_everywhere(self) -> bool:
        return all(g.outcome is not ABSENT for g in self.groups)


@dataclass(frozen=True)
class Comparison:
    path: str
    rows: tuple[KeyRow, ...]
    ran: tuple[Result, ...]
    errored: tuple[Result, ...]
    unavailable: tuple[Result, ...]
    held_back: tuple[Result, ...]
    hazards: tuple[Hazard, ...]

    @property
    def disagreements(self) -> tuple[KeyRow, ...]:
        return tuple(r for r in self.rows if not r.agreed)

    @property
    def split_on_validity(self) -> bool:
        """Some parsers read the file and others rejected it outright."""
        return bool(self.ran) and bool(self.errored)

    @property
    def drifted(self) -> bool:
        return bool(self.disagreements) or self.split_on_validity


def _outcome_for(result: Result, key: str) -> Outcome:
    assert result.values is not None
    if key in result.values:
        return result.values[key]
    if key in result.valueless_keys:
        return VALUELESS
    return ABSENT


def _sort_key(outcome: Outcome) -> tuple[int, str]:
    # Real values first and in order, then the sentinels, so the reading order
    # of a group list is stable between runs and between engines.
    if isinstance(outcome, _Sentinel):
        return (1, outcome.label)
    return (0, outcome)


def build(path: str, results: Iterable[Result], hazards: Iterable[Hazard] = ()) -> Comparison:
    results = tuple(results)
    ran = tuple(r for r in results if r.ran)
    errored = tuple(r for r in results if r.error is not None)
    unavailable = tuple(r for r in results if r.unavailable is not None)
    held_back = tuple(r for r in results if r.held_back is not None)

    keys: set[str] = set()
    for result in ran:
        assert result.values is not None
        keys.update(result.values)
        keys.update(result.valueless_keys)

    rows = []
    for key in sorted(keys):
        by_outcome: dict[Outcome, list[str]] = {}
        for result in ran:
            by_outcome.setdefault(_outcome_for(result, key), []).append(result.engine)
        groups = tuple(
            Group(outcome, tuple(engines))
            for outcome, engines in sorted(by_outcome.items(), key=lambda kv: _sort_key(kv[0]))
        )
        rows.append(KeyRow(key, groups))

    return Comparison(
        path=path,
        rows=tuple(rows),
        ran=ran,
        errored=errored,
        unavailable=unavailable,
        held_back=held_back,
        hazards=tuple(hazards),
    )


def run_all(
    path,
    engines: Iterable[Engine],
    hazards: Iterable[Hazard],
    unsafe: bool = False,
) -> Comparison:
    """Ask every engine, holding back the ones that would run the file."""
    from .hazards import held_back_reason

    hazards = tuple(hazards)
    results = []
    for engine in engines:
        why = engine.available()
        if why is not None:
            results.append(Result(engine.name, unavailable=why))
            continue
        if not unsafe:
            reason = held_back_reason(engine, list(hazards))
            if reason is not None:
                results.append(Result(engine.name, held_back=reason))
                continue
        results.append(engine.run(path))
    return build(str(path), results, hazards)
