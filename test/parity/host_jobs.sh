# shellcheck shell=bash
# Sourced by every per-program harness: how wide to fan out on THIS host.
#   ELISA_JOBS           an explicit width for every harness (run_all exports one per worker)
#   /sys/fs/cgroup/cpu.max   a container CPU quota beats the visible core count (a Vast box
#                        advertised 32 cores but ran 7.68; a 32-wide xargs there only thrashed)
#   nproc / hw.ncpu      otherwise
elisa_host_jobs() {
    if [[ -n "${ELISA_JOBS:-}" ]]; then echo "$ELISA_JOBS"; return; fi
    local cores quota period
    cores="$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4) )"
    if [[ -r /sys/fs/cgroup/cpu.max ]]; then
        read -r quota period < /sys/fs/cgroup/cpu.max
        if [[ "$quota" != max && -n "$period" && "$period" -gt 0 ]]; then
            local q=$(( (quota + period - 1) / period ))
            (( q < cores )) && cores=$q
        fi
    fi
    (( cores < 1 )) && cores=1
    echo "$cores"
}
