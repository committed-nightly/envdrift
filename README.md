# envdrift

Run every `.env` parser on the box against the same file, and show where they
disagree.

There is no `.env` specification. The format started as a convention, got
copied into Node, Python, Ruby, Docker Compose and a dozen other loaders, and
each one wrote its own parser with its own opinion about quoting, comments,
interpolation and line endings. Your app reads the file with one of them. Your
`docker compose up` reads it with another. Your deploy script reads it with
`set -a; . .env`, which is not a parser at all.

envdrift hands one file to all of them and prints the keys they do not agree
about.

## Install

No dependencies. Python 3.10 or newer.

```
git clone https://github.com/committed-nightly/envdrift
cd envdrift
pip install .
```

Or run it straight out of the tree with `python3 -m envdrift.cli`.

The parsers themselves are not dependencies — they are other people's programs,
and envdrift uses whichever ones are already installed. `envdrift
--list-engines` says which those are.

## Use it

```
$ cat .env
# staging
DB_PASSWORD=s3cr#t
API_URL="https://api.example.com/v1"
GREETING="hello\nworld"
CACHE_TTL = 300

$ envdrift .env
.env — 4 keys, 6 of 6 parsers read it

  CACHE_TTL  —  2 outcomes
      '300'      node, npm-dotenv, python-dotenv, ruby-dotenv, compose
      <absent>   bash
  DB_PASSWORD  —  2 outcomes
      's3cr'     node, npm-dotenv, ruby-dotenv
      's3cr#t'   python-dotenv, compose, bash
  GREETING  —  2 outcomes
      'hello\nworld'    node, npm-dotenv, python-dotenv, ruby-dotenv, compose
      'hello\\nworld'   bash

parsers: npm-dotenv 18.0.4, python-dotenv 1.2.3, ruby-dotenv 2.8.1

read the file, and complained
  bash  sourced, exit 127: line 5: CACHE_TTL: command not found

3 of 4 keys differ between parsers
```

Three of those six parsers think the password is `s3cr`.

Exit status is `0` when every parser that read the file agreed about every key
and none had to be held back, `1` when they drift or a parser was held back
from a file it would execute, and `2` when envdrift could not do its job —
including when fewer than two parsers were available, because one parser
agreeing with itself is not agreement.

```
envdrift .env                      # just the disagreements
envdrift --all .env                # every key
envdrift --redact .env             # digests instead of values
envdrift --json .env               # for something other than a person
envdrift --engines node,compose .env
envdrift --list-engines
```

## Redacting the values

`.env` files are full of secrets and envdrift prints values. `--redact`
replaces every value with a keyed digest, so a report can still say *these
three parsers disagree with those three about `DB_PASSWORD`, and one group kept
two more characters* without saying what the password is:

```
$ envdrift --redact .env
.env — 4 keys, 6 of 6 parsers read it

  DB_PASSWORD  —  2 outcomes
      <762f5461>             node, npm-dotenv, ruby-dotenv
      <a57da94a, +2 chars>   python-dotenv, compose, bash

redacted: digests are keyed by a random per-run salt, so they separate
  outcomes inside this report and match nothing outside it. Set
  ENVDRIFT_REDACT_SALT to a secret to compare runs.
  Lengths are relative to the shortest outcome for that key.
```

The key is random bytes generated for that run and never printed, which is what
makes a digest safe to paste at all. **An unkeyed hash of a `.env` value is
not.** Values are short and drawn from small alphabets, so a truncated SHA-256
is only the answer to a guessing game anyone holding the output can play: all
one thousand three-digit strings sweep in about a millisecond, and the four
characters of `s3cr` fall to the full lowercase-and-digits keyspace in under a
second on one CPU. Printing the exact length hands over the size of that
keyspace as well, which is why lengths here are relative to the shortest
outcome for the key (`+2 chars`) rather than absolute — the difference is the
finding, and the absolute length is a hint about the value.

The cost of a per-run key is that two runs are not comparable. When comparing
them is the point — a staging file against production, today against yesterday
— put a secret of your own in `ENVDRIFT_REDACT_SALT` and the digests become
stable for anyone holding it:

```
$ ENVDRIFT_REDACT_SALT="$(cat /run/secrets/envdrift-salt)" envdrift --redact --json .env
```

An environment variable rather than a flag, because arguments are
world-readable in `/proc` on Linux and land in shell history. Use a long one: a
short salt can be guessed alongside a short value, which is the whole problem
back again, and envdrift says so in its output when yours is under 16 bytes.

`--redact` withholds values, not structure. Key names, line numbers, which
parsers disagreed and every hazard line are all still in the output. If the key
names are themselves the secret, this is not the tool you want.

## The parsers

| engine | what it is |
| --- | --- |
| `node` | Node's built-in `util.parseEnv` (Node ≥ 20.12) |
| `npm-dotenv` | the npm `dotenv` package, resolved from the file's own directory |
| `python-dotenv` | `python-dotenv`'s `dotenv_values()` |
| `ruby-dotenv` | the Ruby `dotenv` gem's `Dotenv.parse` |
| `compose` | Docker Compose reading the file as a service's `env_file` |
| `bash` | `set -a; . file`, the way a deploy script reads it |

A parser that is not installed is named in the output rather than dropped,
because a parser missing from a comparison looks exactly like one that agreed.

Availability is decided by looking for a file on disk, never by running the
command and seeing whether it answers. A shell function called `node` will
answer `node --version` perfectly convincingly on a machine with no node binary
anywhere on the path.

Every parser is run with the same near-empty environment. Some of them fall
back to the ambient environment for a name the file does not define and some do
not, and that difference is about your shell, not about your file.

## Some of what they disagree about

Measured, not remembered — these are the cases in `tests/test_engines.py`, and
they run against the real parsers.

| file | node / npm-dotenv | python-dotenv | ruby-dotenv | compose | bash |
| --- | --- | --- | --- | --- | --- |
| `A=1#two` | `1` | `1#two` | `1` | `1#two` | `1#two` |
| `A="$B"` (B=zzz) | `$B` | `$B` | `zzz` | `zzz` | `zzz` |
| `A="${B}"` (B=zzz) | `${B}` | `zzz` | `zzz` | `zzz` | `zzz` |
| ``A=`echo P` `` | `echo P` | `` `echo P` `` | `` `echo P` `` | `` `echo P` `` | `P` |
| `A="a\nb"` | newline | newline | newline † | newline | literal `\n` |
| `A=1␍` (CRLF) | `1` | `1` | `1` | `1` | `1␍` |
| `A=a b` | `a b` | `a b` | `a b` | `a b` | *not set* |
| `A = 1` | `1` | `1` | `1` | `1` | *not set* |
| `A="oops` | `"oops` | *not set* | `"oops` | **rejects the file** | *not set* |

† On the `dotenv` gem 2.8.1. Version 3.2.0 leaves the backslash alone, which
is the next paragraph.

### A parser can also disagree with itself

That `†` was not planned. The table was measured on a box with the `dotenv` gem
2.8.1, CI installed 3.2.0, and the suite went red on exactly one cell: 2.x
expands `\n` inside double quotes and 3.x does not.

So "ruby-dotenv said `a\nb`" is only half an answer. envdrift prints a
`parsers:` line with the version of everything that reported one, because the
version is part of the result — your laptop and your CI runner can be running
different parsers under the same name.

`tests/test_engines.py` records this as an explicit `OneOf` with the reason
attached, rather than by pinning a gem version in CI. Pinning would have made
the suite agree with itself and stop reporting the one thing it had found.

Three more worth pulling out:

- **`A=1#two`.** Half of them call the `#` a comment and half keep it. Put a
  `#` in a password or a URL fragment and two of your tools have a different
  secret. A space before the `#` makes them all agree it is a comment.
- **`A="${B}"` versus `A="$B"`.** python-dotenv interpolates the braced form and
  not the bare one, so it sits with Node on one row and with everyone else on
  the next.
- **`A=a b`.** Every dotenv parser reads a two-word value. Bash does not assign
  anything at all — `A=a b` is a command prefix, so `A` is set only for the
  duration of running `b`, and then it is gone. The complaint about `b` goes to
  stderr, and `.` still returns the status of the *last* line in the file, so a
  deploy script checking `$?` sees success.

## The two parsers that run your file

`bash` and `ruby-dotenv` do not only read values, they execute them:

```
$ cat .env
BUILD=$(echo PWNED)

$ envdrift .env
.env — 1 key, 4 of 6 parsers read it

executed, not read
  line 1  command substitution `$(...)`  —  bash, ruby-dotenv

held back
  bash         would execute command substitution `$(...)` at line 1; re-run with --unsafe to allow it
  ruby-dotenv  would execute command substitution `$(...)` at line 1; re-run with --unsafe to allow it

4 parsers agreed on every one of 1 key; 2 parsers held back from a file they would execute
```

That exits `1`. The four parsers that do not execute anything did agree, but
"everyone agreed" is the wrong headline for a file with a `$(...)` in it.

`bash` being in that list is not a surprise — `. file` is running the file. The
Ruby `dotenv` gem is, because it looks like a parser and is named like one, and
`Dotenv.parse` performs command substitution on values.

So envdrift will not hand your file to either of them if the raw text contains
something they would run, unless you pass `--unsafe`. With `--unsafe` you get
the real values, and a line saying which line was executed by whom:

```
$ envdrift --unsafe .env
  BUILD  —  2 outcomes
      '$(echo PWNED)'   node, npm-dotenv, python-dotenv, compose
      'PWNED'           ruby-dotenv, bash
```

It decides this from the raw text and deliberately does not work out whether
the quoting around a `$(` renders it inert. Whether a given quote disables
expansion is *precisely* what these parsers disagree about, so answering it
would mean picking one parser's rules to gate the comparison that is supposed
to reveal them. It is occasionally cautious about a `$(` nothing would have
run. That is the trade.

## What it does not do

- It does not tell you which parser is right. There is no right one.
- It does not fix your file, rewrite it, or suggest a canonical form.
- It does not know which parser *your* application uses. It shows you the
  spread; which two ends of it matter is your call.
- It only compares the parsers installed on the machine it runs on. Six
  agreeing on a box with three of them installed is not six agreeing, which is
  why an absent parser is printed rather than omitted.

## Tests

```
pip install -e '.[test]'
pytest
```

The suite splits in two. `test_compare.py`, `test_report.py`, `test_hazards.py`
and `test_redact.py` need nothing installed. `test_engines.py` runs the real
parsers, and each case skips itself when its engine is missing — so a clean run
on a bare box is mostly skips, and `pytest -rs` will tell you what you are not
covering.

To get all six locally: `npm install dotenv`, `pip install python-dotenv`,
`gem install dotenv`, and Docker.

If you are working in a virtualenv, `python-dotenv` has to go *inside* it. The
`python-dotenv` engine runs the interpreter the suite is running under, so a
copy installed system-wide is invisible to it and that engine's cases skip
while the other five run.

## Licence

MIT.
