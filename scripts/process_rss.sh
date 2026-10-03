# Fork-free process observation for the RSS guards (sourced by elisac_stage1.sh,
# elisac_stage1_seed.sh via it, and self_host_gen2.sh).
#
# Every guard poll used to be `ps -o rss= -p PID | awk ...` plus an external `sleep` plus an
# awk for the backoff: four fork+execs per poll. Polling every 50 ms, that was ~3.5k
# processes for a two-minute compile and ~16k for the 7-minute self-compile -- ~10% of the
# wall clock and 90% of the minor page faults /usr/bin/time charged to the compile (the
# compiler itself took 310k faults; the guarded run 2.86M). On Linux the same facts are in
# /proc and bash can read them and sleep with builtins, so a poll forks nothing. Everywhere
# else (macOS has no /proc) the original ps/sleep path is kept unchanged.
#
# Results come back in globals, never through $(...), which would fork a subshell.

elisa_rss_have_proc=0
[[ -r /proc/self/status ]] && elisa_rss_have_proc=1
elisa_rss_sleep_fd=""

# PROCESS_RSS_KB <- resident set of $1 in KB, or "" when the process is gone.
# PROCESS_STATE  <- its one-letter state ("Z" for a zombie), or "" when gone.
process_observe() {
  local pid="$1" key value _rest
  PROCESS_RSS_KB=""
  PROCESS_STATE=""
  if (( elisa_rss_have_proc )); then
    [[ -r "/proc/$pid/status" ]] || return 0
    # A zombie has no VmRSS line; State is always present while the entry exists.
    while read -r key value _rest; do
      case "$key" in
        State:) PROCESS_STATE="$value" ;;
        VmRSS:) PROCESS_RSS_KB="$value"; break ;;
      esac
    done <"/proc/$pid/status" 2>/dev/null || true
    return 0
  fi
  PROCESS_STATE="$(ps -o stat= -p "$pid" 2>/dev/null)" || PROCESS_STATE=""
  PROCESS_RSS_KB="$(ps -o rss= -p "$pid" 2>/dev/null | awk '{print $1}')" || PROCESS_RSS_KB=""
}

# Sleep $1 seconds (a decimal such as 0.05). On Linux a `read -t` on a pipe nobody writes
# to is a builtin timed wait; the pipe is opened once per shell.
process_sleep() {
  if (( elisa_rss_have_proc )) && (( BASH_VERSINFO[0] >= 4 )); then
    if [[ -z "$elisa_rss_sleep_fd" ]]; then
      exec {elisa_rss_sleep_fd}<> <(:) 2>/dev/null || elisa_rss_sleep_fd="none"
    fi
    if [[ "$elisa_rss_sleep_fd" != "none" ]]; then
      read -r -t "$1" -u "$elisa_rss_sleep_fd" _ 2>/dev/null || true
      return 0
    fi
  fi
  sleep "$1"
}

# Seconds (decimal string) -> integer microseconds, without awk. Unparseable input gives
# the 50 ms default the guards document.
process_seconds_to_us() {
  local s="$1" whole frac
  PROCESS_US=50000
  [[ "$s" =~ ^([0-9]*)(\.([0-9]*))?$ ]] || return 0
  whole="${BASH_REMATCH[1]:-0}"
  frac="${BASH_REMATCH[3]:-}000000"
  frac="${frac:0:6}"
  PROCESS_US=$(( 10#$whole * 1000000 + 10#$frac ))
}

# Microseconds -> "S.UUUUUU" for sleep/read -t.
process_us_to_seconds() {
  printf -v PROCESS_SECONDS '%d.%06d' $(( $1 / 1000000 )) $(( $1 % 1000000 ))
}
