gate_jobs_by_memory() {
    local free_kb="" gb
    case "$(uname -s)" in
        Darwin)
            # memory_pressure's free percentage, not vm_stat: free+inactive pages
            # badly UNDERSTATE reclaimable memory on macOS (compressed memory and
            # file cache are invisible to them) — this pool once picked 3 workers
            # while the system reported 66% of 24GB free. The kernel's own pressure
            # figure already accounts for everything reclaimable.
            local free_pct total_bytes
            free_pct="$(memory_pressure -Q 2>/dev/null | awk -F': ' '/free percentage/ {gsub(/%/,"",$2); print int($2)}')"
            total_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
            if [[ -n "$free_pct" && -n "$total_bytes" ]]; then
                free_kb=$(( total_bytes / 1024 * free_pct / 100 ))
            else
                free_kb="$(vm_stat 2>/dev/null | awk -v ps="$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)" '
                    /Pages free/ {f=$3} /Pages inactive/ {i=$3}
                    END {gsub(/\./,"",f); gsub(/\./,"",i); if (f=="") exit 1; print int((f+i)*ps/1024)}')" || free_kb=""
            fi
            ;;
        Linux)
            free_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null)"
            ;;
    esac
    # Unknown host: keep the historical default rather than guessing.
    [[ -z "$free_kb" ]] && { echo 6; return; }
    gb=$((free_kb / 1048576))
    # ~3 GB of headroom per concurrent check, floor of 2 so a loaded box still finishes.
    # Ceiling: the core count (Phase T, 2026-09-06 — the old fixed cap of 6 left a 32-core,
    # 251 GB host running six checks at a time; ELISA_GATE_JOBS still overrides).
    local n=$((gb / 3)) cores
    cores="$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 6) )"
    # A CONTAINER QUOTA beats the visible core count. A Vast box advertised 32 cores and
    # ran the gate 32-wide, yet vmstat showed 29 % busy with 60-98 runnable processes:
    # cgroup `cpu.max` was 768000/100000 = 7.68 CPUs and every period was throttled
    # (2026-09-06). Size the pool by the quota, rounded up, or the gate thrashes.
    if [[ -r /sys/fs/cgroup/cpu.max ]]; then
        local quota period
        read -r quota period < /sys/fs/cgroup/cpu.max
        if [[ "$quota" != max && -n "$period" && "$period" -gt 0 ]]; then
            local q=$(( (quota + period - 1) / period ))
            (( q < cores )) && cores=$q
        fi
    fi
    (( n < 2 )) && n=2
    (( n > cores )) && n=$cores
    echo "$n"
}
