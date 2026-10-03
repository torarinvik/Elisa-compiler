#!/usr/bin/env bash
# Host registry, sourced by the other tools/remote scripts. Rented-box addresses are
# ephemeral, so the real list lives in the gitignored hosts.local (start from
# hosts.local.sample). One host per line:   <alias> <ssh-port> <user@host> <cpu-cap>
# cpu-cap = OUR total concurrent jobs on that host (gates + seeds + fuzz), agreed per box.
_hosts_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOSTS_FILE="${ELISA_HOSTS_FILE:-$_hosts_dir/hosts.local}"
# No hosts.local yet: use the committed sample (current default host: vast4).
[[ -f "$HOSTS_FILE" ]] || HOSTS_FILE="$_hosts_dir/hosts.local.sample"
host_ssh_args() {  # sets SSH_ARGS=(...) for alias $1
  local line _a port target cap
  line="$(awk -v a="$1" '$1==a {print; exit}' "$HOSTS_FILE" 2>/dev/null)"
  [[ -n "$line" ]] || { echo "hosts.sh: unknown host '$1' (add it to $HOSTS_FILE)" >&2; return 2; }
  read -r _a port target cap <<<"$line"
  HOST_CPU_CAP="${cap:-8}"
  SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -p "$port" "$target")
}
host_aliases() { awk '!/^#/ && NF>=3 {print $1}' "$HOSTS_FILE" 2>/dev/null; }
# ssh to the current SSH_ARGS host with the provider's login banner stripped from stderr.
# (fd swap, not process substitution: macOS bash 3.2 fails to parse `2> >(...)` inside $(...).)
rssh() {
  # The grep stage must never fail the pipeline (callers run under set -e -o pipefail and a
  # banner-free stderr makes grep exit 1); the ssh status is returned explicitly.
  local st f="${TMPDIR:-/tmp}/rssh.$$.$RANDOM$RANDOM"
  { { s0=0; ssh "${SSH_ARGS[@]}" "$@" 2>&1 1>&3 3>&- || s0=$?; echo "$s0" > "$f"; } |
      { grep -v -E 'Welcome to vast.ai|^Have fun!|^AI agents: READ /etc/vast-agents-guide' >&2 || true; }; } 3>&1
  st=$(cat "$f" 2>/dev/null || echo 255); rm -f "$f"
  return "$st"
}
