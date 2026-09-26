#!/usr/bin/env bash
# `set -a; . file` -- what a deploy script does, and the only engine here that
# is unambiguously running your file as a program.
#
# Usage: bash_source.sh <env-file> <before-dump> <after-dump>
#
# Intended to be launched under `env -i` so the starting environment is empty
# and anything new in the after-dump came from the file. The caller diffs the
# two dumps; doing it here would mean writing a JSON encoder in bash.

set -u

envfile=$1
before=$2
after=$3

env -0 >"$before"

# The source runs in a subshell so that a file calling `exit` takes the subshell
# down and not this script -- but then the dump has to happen inside it too, or
# there would be nothing left to dump.
(
  set -a
  # shellcheck disable=SC1090
  . "$envfile" || exit 3
  set +a
  env -0 >"$after"
)
rc=$?

if [ ! -s "$after" ]; then
  exit "${rc:-1}"
fi
exit 0
