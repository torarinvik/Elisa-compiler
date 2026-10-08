#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
out="${ELISA_CPU_PROBE_OUTPUT:?set an isolated output directory}"
mkdir -p "$out"
producer="${ELISA_CPU_PROBE_PRODUCER:?set explicit compiler producer}"
hooks="${ELISA_CPU_PROBE_HOOKS:?set source-runtime fallback hooks only}"
: "${ELISA_CORE:?set matching core source/runtime identity}"
sha256sum "$producer" "$hooks" test/repro/cpu_optional_goal_allocation_probe.* > "$out/inputs.sha256"
source scripts/process_rss.sh
exec 9>/tmp/elisac-stage1-global-seed.lock
flock -w 180 9
ulimit -s 524288
/usr/lib/llvm-21/bin/clang -c test/repro/cpu_optional_goal_allocation_probe.c -o "$out/oracle.o"
for opt in 0 2; do
 GOMAXPROCS=2 ELISACORE_CODEGEN_JOBS=1 ELISA_HOST_LINUX=1 ELISA_HOST_X86_64=1 "$producer" -emit obj -target-triple x86_64-unknown-linux-gnu -O"$opt" -o "$out/probe-O$opt.o" test/repro/cpu_optional_goal_allocation_probe.elisa > "$out/compile-O$opt.stdout" 2> "$out/compile-O$opt.stderr" &
 child=$!
 peak=0
 while kill -0 "$child" 2>/dev/null; do
  process_observe "$child"
  [[ "$PROCESS_STATE" == Z || -z "$PROCESS_STATE" ]] && break
  if [[ -n "$PROCESS_RSS_KB" ]]; then
   (( PROCESS_RSS_KB > peak )) && peak=$PROCESS_RSS_KB
   if (( PROCESS_RSS_KB > 12582912 )); then kill "$child"; wait "$child" || true; exit 99; fi
  fi
  process_sleep 0.5
 done
 set +e
 wait "$child"; status=$?
 set -e
 printf '%s\n' "$status" > "$out/compile-O$opt.status"
 printf '%s\n' "$peak" > "$out/compile-O$opt.peak-rss-kb"
 [[ "$status" == 0 ]] || exit "$status"
 /usr/lib/llvm-21/bin/clang -no-pie "$out/probe-O$opt.o" "$out/oracle.o" "$hooks" -L/usr/lib/llvm-21/lib -Wl,-rpath,/usr/lib/llvm-21/lib -lLLVM -lm -lpthread -ldl -Wl,-z,stack-size=536870912 -Wl,--no-undefined -o "$out/probe-O$opt.exe" > "$out/link-O$opt.log" 2>&1
 set +e
 "$out/probe-O$opt.exe" > "$out/run-O$opt.stdout" 2> "$out/run-O$opt.stderr"; status=$?
 set -e
 printf '%s\n' "$status" > "$out/run-O$opt.status"
 [[ "$status" == 0 ]] || exit "$status"
done
sha256sum "$out"/*.o "$out"/*.exe > "$out/products.sha256"
printf '0\n' > "$out/status"
