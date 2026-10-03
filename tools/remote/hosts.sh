#!/usr/bin/env bash
# Host registry, sourced by the other tools/remote scripts. Rented-box addresses are
# ephemeral, so the real list lives in the gitignored hosts.local (start from
# hosts.local.sample). One host per line:   <alias> <ssh-port> <user@host>
_hosts_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOSTS_FILE="${ELISA_HOSTS_FILE:-$_hosts_dir/hosts.local}"
# No hosts.local yet: use the committed sample (current default host: vast4).
[[ -f "$HOSTS_FILE" ]] || HOSTS_FILE="$_hosts_dir/hosts.local.sample"
host_ssh_args() {  # sets SSH_ARGS=(...) for alias $1
  local line _a port target
  line="$(awk -v a="$1" '$1==a {print; exit}' "$HOSTS_FILE" 2>/dev/null)"
  [[ -n "$line" ]] || { echo "hosts.sh: unknown host '$1' (add it to $HOSTS_FILE)" >&2; return 2; }
  read -r _a port target <<<"$line"
  SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -p "$port" "$target")
}
host_aliases() { awk '!/^#/ && NF>=3 {print $1}' "$HOSTS_FILE" 2>/dev/null; }
# ssh to the current SSH_ARGS host with the provider's login banner stripped from stderr.
rssh() { ssh "${SSH_ARGS[@]}" "$@" 2> >(grep -v -E 'Welcome to vast.ai|^Have fun!|^AI agents: READ /etc/vast-agents-guide' >&2); }
