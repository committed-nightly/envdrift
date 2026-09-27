"""Say that two outcomes differ without saying what either one is.

A plain truncated SHA-256 of the value does not do this. `.env` values are
short and drawn from small alphabets, and the digest is the answer to an
offline guessing game anyone can play: every three-digit string takes a
millisecond to sweep, every four-character lowercase-and-digits string under a
second. Printing the exact length alongside it hands over the keyspace as well.

So redaction here is a *keyed* digest, and the key is a secret:

  * by default, random bytes generated for this run and never printed. The
    digests separate outcomes inside one report and match nothing outside it,
    which is all a single report needs them to do.
  * if ENVDRIFT_REDACT_SALT is set, that value is the key instead, so two runs
    sharing the salt produce comparable digests -- the staging file against the
    production one, today's against yesterday's.

It is an environment variable rather than a flag on purpose. Arguments are
world-readable in /proc on Linux and land in shell history; a salt that leaks
is a salt that is not there.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

SALT_ENV = "ENVDRIFT_REDACT_SALT"
DIGEST_CHARS = 8
RANDOM_SALT_BYTES = 32

# Under this, guessing the salt and a short value together is back within
# reach, which is the thing this module exists to prevent. Worth saying out
# loud rather than refusing: it is the caller's secret and their call.
WEAK_SALT_BYTES = 16


class Redactor:
    """Keyed digests for values that must not be printed."""

    __slots__ = ("_salt", "from_env")

    def __init__(self, salt: bytes, *, from_env: bool) -> None:
        self._salt = salt
        self.from_env = from_env

    @classmethod
    def build(cls, environ: dict[str, str] | None = None) -> "Redactor":
        environ = os.environ if environ is None else environ
        # An empty ENVDRIFT_REDACT_SALT is an unset one. `SALT= envdrift ...`
        # should not silently key every digest with nothing.
        supplied = environ.get(SALT_ENV) or ""
        if supplied:
            return cls(supplied.encode("utf-8", "surrogateescape"), from_env=True)
        return cls(secrets.token_bytes(RANDOM_SALT_BYTES), from_env=False)

    def digest(self, value: str) -> str:
        return hmac.new(
            self._salt,
            value.encode("utf-8", "surrogateescape"),
            hashlib.sha256,
        ).hexdigest()[:DIGEST_CHARS]

    @property
    def weak_salt(self) -> bool:
        return self.from_env and len(self._salt) < WEAK_SALT_BYTES

    def __repr__(self) -> str:
        # Never let the salt reach a traceback, a log line or a debugger dump.
        # Everything else in this tool is built to print what it is holding.
        source = SALT_ENV if self.from_env else "random"
        return f"<Redactor salt={source} (hidden)>"

    def explain(self) -> list[str]:
        """The footnote that makes a redacted report readable by a stranger.

        Without it a reader cannot tell whether two digests differing between
        two reports means the value changed or means the salt did.
        """
        tail = "  Lengths are relative to the shortest outcome for that key."
        if self.from_env:
            lines = [
                f"redacted: digests are keyed by {SALT_ENV}, so two runs",
                "  sharing that salt are comparable.",
                tail,
            ]
            if self.weak_salt:
                lines.append(
                    f"  That salt is under {WEAK_SALT_BYTES} bytes, which is short enough"
                )
                lines.append("  to guess alongside a short value.")
            return lines
        return [
            "redacted: digests are keyed by a random per-run salt, so they separate",
            "  outcomes inside this report and match nothing outside it. Set",
            f"  {SALT_ENV} to a secret to compare runs.",
            tail,
        ]
