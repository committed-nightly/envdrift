"""The grouping layer, with made-up engine results.

None of these need a parser installed. If the grouping is wrong, every claim
the tool makes is wrong, so this is the part worth over-testing.
"""

from envdrift import compare
from envdrift.compare import ABSENT, VALUELESS, Result, build


def r(name, values=None, **kw):
    return Result(name, values=values, **kw)


def test_unanimous_key_is_one_group():
    cmp = build("f", [r("a", {"K": "1"}), r("b", {"K": "1"})])
    (row,) = cmp.rows
    assert row.agreed
    assert row.groups[0].engines == ("a", "b")
    assert not cmp.drifted


def test_two_values_group_by_outcome():
    cmp = build("f", [r("a", {"K": "1"}), r("b", {"K": "2"}), r("c", {"K": "1"})])
    (row,) = cmp.rows
    assert not row.agreed
    assert [(g.outcome, g.engines) for g in row.groups] == [
        ("1", ("a", "c")),
        ("2", ("b",)),
    ]
    assert cmp.drifted


def test_absent_is_not_the_empty_string():
    cmp = build("f", [r("a", {"K": ""}), r("b", {})])
    (row,) = cmp.rows
    assert not row.agreed
    outcomes = [g.outcome for g in row.groups]
    assert "" in outcomes and ABSENT in outcomes


def test_valueless_is_not_the_empty_string():
    cmp = build("f", [r("a", {"K": ""}), r("b", {}, valueless_keys=("K",))])
    (row,) = cmp.rows
    assert not row.agreed
    assert [g.outcome for g in row.groups] == ["", VALUELESS]


def test_valueless_is_not_absent():
    cmp = build("f", [r("a", {}, valueless_keys=("K",)), r("b", {"OTHER": "x"})])
    row = {x.key: x for x in cmp.rows}["K"]
    # Both are sentinels, so they sort between themselves by label.
    assert [g.outcome for g in row.groups] == [ABSENT, VALUELESS]


def test_keys_are_the_union_across_engines():
    cmp = build("f", [r("a", {"X": "1"}), r("b", {"Y": "2"})])
    assert [row.key for row in cmp.rows] == ["X", "Y"]
    assert all(not row.agreed for row in cmp.rows)


def test_sentinels_sort_after_real_values():
    cmp = build("f", [r("a", {}), r("b", {"K": "zzz"}), r("c", {"K": "aaa"})])
    (row,) = cmp.rows
    assert [g.outcome for g in row.groups] == ["aaa", "zzz", ABSENT]


def test_engines_that_did_not_run_are_not_in_any_group():
    cmp = build(
        "f",
        [
            r("a", {"K": "1"}),
            r("b", unavailable="not installed"),
            r("c", error="rejected"),
            r("d", held_back="would execute"),
        ],
    )
    (row,) = cmp.rows
    assert row.groups == (compare.Group("1", ("a",)),)
    assert [x.engine for x in cmp.unavailable] == ["b"]
    assert [x.engine for x in cmp.errored] == ["c"]
    assert [x.engine for x in cmp.held_back] == ["d"]


def test_a_rejection_alongside_a_read_is_drift():
    cmp = build("f", [r("a", {"K": "1"}), r("b", error="unexpected EOF")])
    assert cmp.split_on_validity
    assert cmp.drifted
    # ...even though the one key nobody disagreed about looks fine.
    assert cmp.rows[0].agreed


def test_everyone_rejecting_is_not_drift():
    cmp = build("f", [r("a", error="bad"), r("b", error="bad")])
    assert not cmp.split_on_validity
    assert not cmp.drifted


def test_sentinel_identity_survives_a_round_trip():
    # The sentinels are used as dict keys during grouping, so a broken __hash__
    # would silently split one outcome into several.
    assert ABSENT == compare._Sentinel("<absent>")
    assert hash(ABSENT) == hash(compare._Sentinel("<absent>"))
    assert ABSENT != VALUELESS
    assert ABSENT != "<absent>"
