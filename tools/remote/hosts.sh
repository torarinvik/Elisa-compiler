#!/usr/bin/env bash
# Host registry, sourced by the other tools/remote scripts. Rented-box addresses are
# ephemeral, so the real list lives in the gitignored hosts.local (start from
# hosts.local.sample). One host per line:   <alias> <ssh-port> <user@host>
HOSTS_FILE="${ELISA_HOSTS_FILE:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/hosts.local}"
host_ssh_args() {  # sets SSH_ARGS=(...) for alias $1
  local line _a port target
  line="$(awk -v a="$1" '$1==a {print; exit}' "$HOSTS_FILE" 2>/dev/null)"
  [[ -n "$line" ]] || { echo "hosts.sh: unknown host '$1' (add it to $HOSTS_FILE)" >&2; return 2; }
  read -r _a port target <<<"$line"
  SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -p "$port" "$target")
}
host_aliases() { awk '!/^#/ && NF>=3 {print $1}' "$HOSTS_FILE" 2>/dev/null; }
