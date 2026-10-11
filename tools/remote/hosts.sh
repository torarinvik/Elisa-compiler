#!/usr/bin/env bash
# Host registry, sourced by the other tools/remote scripts. Rented-box addresses are
# ephemeral, so the real list lives in the gitignored hosts.local (start from
# hosts.local.sample). One host per line:   <alias> <ssh-port> <user@host> <cpu-cap>
# cpu-cap = OUR total concurrent jobs on that host (gates + seeds + fuzz), agreed per box.
_hosts_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOSTS_FILE="${ELISA_HOSTS_FILE:-$_hosts_dir/hosts.local}"
# Without an explicit local registry, use the empty template; never contact a retired host.
[[ -f "$HOSTS_FILE" ]] || HOSTS_FILE="$_hosts_dir/hosts.local.sample"
host_ssh_args() {  # sets SSH_ARGS=(...) for alias $1
  local line _a port target cap
  line="$(awk -v a="$1" '$1==a {print; exit}' "$HOSTS_FILE" 2>/dev/null)"
  [[ -n "$line" ]] || { echo "hosts.sh: unknown host '$1' (add it to $HOSTS_FILE)" >&2; return 2; }
  read -r _a port target cap <<<"$line"
  # Retired project instances must never become an implicit build dependency.
  case "${target##*@}" in
    38.49.42.120|141.195.21.72)
      echo "hosts.sh: retired project host '$target'; use local compute or configure a new verified host" >&2
      return 2
      ;;
  esac
  HOST_CPU_CAP="${cap:-8}"
  SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -p "$port" "$target")
}
host_aliases() { awk '!/^#/ && NF>=3 {print $1}' "$HOSTS_FILE" 2>/dev/null; }
# Run SSH only against the explicitly selected registry entry.
rssh() {
  ssh "${SSH_ARGS[@]}" "$@"
}
