"""The corpus CI runs against, and the README block that claims to show it.

Pinning the *input* rather than the output on purpose. What envdrift prints
for this file moves with the parsers installed -- the `GREETING` row changes
with the `dotenv` gem's major version, which is the README's own worked
example of a parser disagreeing with itself -- so a byte-for-byte pin on the
output would go red on a gem bump and teach everyone to delete the pin. The
file itself cannot drift for any reason except somebody editing one of the
two copies and not the other.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "examples" / "readme.env"


def _readme_cat_block() -> str:
    """The lines the README shows under `$ cat examples/readme.env`."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    after = text.split("$ cat examples/readme.env\n", 1)
    assert len(after) == 2, "the README no longer cats examples/readme.env"
    return after[1].split("\n$ ", 1)[0]


def test_the_corpus_exists_and_is_what_ci_runs():
    assert CORPUS.is_file(), f"{CORPUS} is referenced by ci.yml"
    # Trailing newline and no trailing whitespace: several of the differences
    # envdrift finds are about bytes at the end of a line.
    raw = CORPUS.read_bytes()
    assert raw.endswith(b"\n")
    assert b" \n" not in raw


def test_the_readme_shows_the_corpus_verbatim():
    assert _readme_cat_block() == CORPUS.read_text(encoding="utf-8")


def test_the_corpus_still_contains_the_four_keys_the_readme_counts():
    """ci.yml pins '4 keys, 6 of 6 parsers read it' as a whole line."""
    keys = [
        line.split("=", 1)[0].strip()
        for line in CORPUS.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    ]
    assert keys == ["DB_PASSWORD", "API_URL", "GREETING", "CACHE_TTL"]
