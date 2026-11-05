#!/usr/bin/env bash
# Run a command with bounded terminal output while retaining its complete output.
#
# Usage: scripts/run-quiet.sh [--verbose] [--] <command> [arguments...]
# Environment:
#   MILBURN_LOG_DIR  Log destination (default: ${TMPDIR:-/tmp}/milburn-logs)
#   MILBURN_VERBOSE  Set to 1 to stream the command directly instead
set -euo pipefail

verbose=${MILBURN_VERBOSE:-0}
if [[ ${1:-} == --verbose ]]; then
  verbose=1
  shift
fi
if [[ ${1:-} == -- ]]; then
  shift
fi

if (( $# == 0 )); then
  echo "run-quiet: missing command." >&2
  exit 2
fi

command_name=$1
if [[ "$command_name" == */* ]]; then
  if [[ ! -e "$command_name" ]]; then
    echo "run-quiet: executable not found: $command_name" >&2
    exit 127
  fi
  if [[ ! -f "$command_name" || ! -x "$command_name" ]]; then
    echo "run-quiet: command is not executable: $command_name" >&2
    exit 126
  fi
elif ! command -v -- "$command_name" >/dev/null 2>&1; then
  echo "run-quiet: executable not found: $command_name" >&2
  exit 127
fi

# Verbose mode intentionally executes the command directly. This preserves its
# stdout, stderr, and signal behavior without adding a wrapper summary.
if [[ "$verbose" == 1 ]]; then
  exec "$@"
fi

log_dir=${MILBURN_LOG_DIR:-${TMPDIR:-/tmp}/milburn-logs}
if ! mkdir -p "$log_dir" 2>/dev/null; then
  echo "run-quiet: cannot create log directory: $log_dir" >&2
  exit 1
fi
if [[ ! -d "$log_dir" ]]; then
  echo "run-quiet: log directory is not a directory: $log_dir" >&2
  exit 1
fi

log=$(mktemp "$log_dir/run-quiet.XXXXXXXX") || {
  echo "run-quiet: cannot create log file in log directory: $log_dir" >&2
  exit 1
}

printf -v command_display '%q ' "$@"
command_display=${command_display% }

start=$SECONDS
command_status=0
"$@" >"$log" 2>&1 || command_status=$?
elapsed=$((SECONDS - start))

if (( command_status == 0 )); then
  printf 'run-quiet OK (%ss): %s [log: %s]\n' \
    "$elapsed" "$command_display" "$log"
else
  printf 'run-quiet FAILED exit=%s (%ss): %s [log: %s]\n' \
    "$command_status" "$elapsed" "$command_display" "$log"
  tail -n 40 "$log"
fi

exit "$command_status"
