"""The `python-dotenv` package, via dotenv_values() with its default settings.

Run as a subprocess rather than imported so that a python-dotenv installed in
the project's virtualenv answers, not whichever one envdrift happens to sit in.
"""

import json
import sys


def out(obj):
    sys.stdout.write(json.dumps(obj))


try:
    import dotenv
except ImportError as exc:
    out({"unavailable": "python-dotenv is not installed: %s" % exc})
    sys.exit(0)

try:
    values = dotenv.dotenv_values(sys.argv[1])
    # dotenv_values yields None for a bare `KEY` with no `=`. Every other engine
    # either rejects that line or gives it a value, so keep the distinction.
    out(
        {
            "values": {k: v for k, v in values.items() if v is not None},
            "valueless_keys": sorted(k for k, v in values.items() if v is None),
            "version": getattr(dotenv, "__version__", None),
        }
    )
except Exception as exc:  # noqa: BLE001 - report whatever the parser raised
    out({"error": "%s: %s" % (type(exc).__name__, exc)})
