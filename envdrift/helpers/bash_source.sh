#!/usr/bin/env bash
# `set -a; . file` -- what a deploy script does, and the only engine here that
# is unambiguously running your file as a program.
#
# Usage: bash_source.sh <env-file> <before-dump> <after-dump> <status-file>
#
# Intended to be launched under `env -i` so the starting environment is empty
# and anything new in the after-dump came from the file. The caller diffs the
# two dumps; doing it here would mean writing a JSON encoder in bash.

set -u

envfile=$1
before=$2
after=$3
statusfile=$4

env -0 >"$before"

# The source runs in a subshell so that a file calling `exit` takes the subshell
# down and not this script -- but then the dump has to happen inside it too, or
# there would be nothing left to dump.
#
# A non-zero status from `.` is deliberately not fatal. `A=a b` runs `b` with A
# set only for that command, so sourcing "fails" and the shell is left in a
# state worth reporting rather than discarding. Only a syntax error takes the
# subshell down before the dump, which is the empty-file case below.
#
# The status goes to a file rather than a variable on purpose: `set -a` is still
# on at that point, so any variable assigned here would be exported and show up
# in the after-dump as if the .env file had set it.
(
  set -a
  # shellcheck disable=SC1090
  . "$envfile"
  echo $? >"$statusfile"
  set +a
  env -0 >"$after"
)

if [ ! -s "$after" ]; then
  # Nothing was dumped, so the shell died partway: the file is not sourceable.
  exit 1
fi
exit 0
