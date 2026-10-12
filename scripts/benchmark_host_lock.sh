# Shared host-wide lease and load checks for compiler timing entry points.
# Source this file from a Bash runner, then call
#   elisa_benchmark_lock_acquire "$OUT"
# and install elisa_benchmark_lock_release as its EXIT trap.

elisa_benchmark_lock_acquire() {
  local output_dir="$1"
  local ready_path="${output_dir}/.benchmark-lock-ready.$$"
  local lock_path="${ELISA_BENCH_LOCK_PATH:-/tmp/elisa-cross-language-benchmark.lock}"
  local status=""

  if ! mkfifo "$ready_path"; then
    echo "could not create host benchmark lock handshake: $ready_path" >&2
    return 2
  fi

  python3 - "$lock_path" "$$" <<'PY' >"$ready_path" &
import fcntl
import os
import sys
import time

fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("busy", flush=True)
    raise SystemExit(3)
print("locked", flush=True)
parent_pid = int(sys.argv[2])
while os.getppid() == parent_pid:
    time.sleep(0.5)
PY
  ELISA_BENCH_LOCK_PID=$!

  if ! IFS= read -r status <"$ready_path"; then
    rm -f "$ready_path"
    echo "could not acquire the host-wide compiler benchmark lock" >&2
    return 2
  fi
  rm -f "$ready_path"

  if [[ "$status" != locked ]]; then
    wait "$ELISA_BENCH_LOCK_PID" 2>/dev/null || true
    unset ELISA_BENCH_LOCK_PID
    echo "another compiler benchmark holds the host lock at $lock_path" >&2
    return 2
  fi
  ELISA_BENCH_LOCK_PATH="$lock_path"
}

elisa_benchmark_lock_release() {
  if [[ -n "${ELISA_BENCH_LOCK_PID:-}" ]]; then
    kill "$ELISA_BENCH_LOCK_PID" 2>/dev/null || true
    wait "$ELISA_BENCH_LOCK_PID" 2>/dev/null || true
    unset ELISA_BENCH_LOCK_PID
  fi
}

elisa_benchmark_host_qualification() {
  local root="$1"
  local output_dir="$2"
  local qualification_path="$output_dir/host_qualification.json"
  ELISA_BENCH_SYSTEM="$(uname -s)"
  ELISA_BENCH_ROOT="$root"
  ELISA_BENCH_OUTPUT_DIR="$output_dir"
  ELISA_BENCH_QUALIFICATION_PATH="$qualification_path"

  case "$ELISA_BENCH_SYSTEM" in
    Darwin)
      python3 - "$qualification_path" <<'PY'
import json
import platform
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"system": "Darwin", "machine": platform.machine()}, sort_keys=True) + "\n")
PY
      ;;
    Linux)
      local qualification_source="${ELISA_BENCH_HOST_QUALIFICATION:-}"
      if [[ -z "$qualification_source" || ! -r "$qualification_source" ]]; then
        echo "Linux timing requires ELISA_BENCH_HOST_QUALIFICATION from this host's qualified cross_language.sh run" >&2
        return 2
      fi
      cp "$qualification_source" "$qualification_path"
      ;;
    *)
      echo "unsupported benchmark host: $ELISA_BENCH_SYSTEM" >&2
      return 2
      ;;
  esac
}

elisa_benchmark_load_check() {
  local stage="$1"
  local preflight="${2:-0}"
  python3 - "$ELISA_BENCH_ROOT" "$ELISA_BENCH_OUTPUT_DIR" "$ELISA_BENCH_QUALIFICATION_PATH" \
    "$ELISA_BENCH_SYSTEM" "$stage" "$preflight" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from bench_load_gate import LoadGateError, check_load_gate, load_average
try:
    check_load_gate(
        load_average(), sys.argv[5], Path(sys.argv[2]), sys.argv[4], Path(sys.argv[3]),
        preflight=sys.argv[6] == "1", require_live_linux=sys.argv[4].lower() == "linux",
    )
except LoadGateError as error:
    print(f"timing load gate failed: {error}", file=sys.stderr)
    raise SystemExit(2)
PY
}

elisa_benchmark_finish() {
  local status=$?
  elisa_benchmark_lock_release
  if (( status != 0 )) && [[ -n "${ELISA_BENCH_OUTPUT_DIR:-}" ]] \
    && [[ ! -f "$ELISA_BENCH_OUTPUT_DIR/ABORTED.txt" ]] \
    && [[ ! -f "$ELISA_BENCH_OUTPUT_DIR/AUXILIARY_COMPLETE" ]]; then
    printf 'ABORTED — auxiliary benchmark exited with status %d before completion.\nAny partial measurements are unusable.\n' \
      "$status" >"$ELISA_BENCH_OUTPUT_DIR/ABORTED.txt" || true
  fi
  return "$status"
}
