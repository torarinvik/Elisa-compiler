#!/usr/bin/env bash
# One line per host in hosts.local: reachability, cores, load, free RAM/disk, our runs/fuzzers.
#   tools/remote/hosts_status.sh [alias...]
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/hosts.sh"
aliases=("$@"); [[ ${#aliases[@]} -gt 0 ]] || aliases=($(host_aliases))
for h in "${aliases[@]}"; do
  host_ssh_args "$h" || continue
  line=$(ssh "${SSH_ARGS[@]}" 'printf "cores=%s load=%s mem_avail=%sG disk_free=%s z3=%s runs=%s fuzz=%s" \
    "$(nproc)" "$(cut -d" " -f1-3 /proc/loadavg)" "$(free -g | awk "/Mem:/{print \$7}")" \
    "$(df -h /root | awk "NR==2{print \$4}")" "$(/root/elisa/bin/z3 --version 2>/dev/null | cut -d" " -f3)" \
    "$(for p in /root/elisa/runs/*/pid; do [ -f "$p" ] && kill -0 "$(cat "$p")" 2>/dev/null && basename "$(dirname "$p")"; done | tr "\n" " ")" \
    "$(for p in /root/elisa/fuzz/*/pid; do [ -f "$p" ] && kill -0 "$(cat "$p")" 2>/dev/null && basename "$(dirname "$p")"; done | tr "\n" " ")"' 2>/dev/null | tail -1)
  printf '%-8s %s\n' "$h" "${line:-UNREACHABLE}"
done
