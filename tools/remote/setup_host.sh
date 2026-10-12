#!/usr/bin/env bash
# One-command toolchain setup for a fresh Ubuntu 24.04 x86_64 gate host (memory note
# linux-gate-host). Idempotent: re-running skips what is already installed.
#
#   tools/remote/setup_host.sh <host-alias>        # from the Mac (alias from hosts.local)
#   bash setup_host.sh --local                      # on the host itself
#
# Installs: the latest stable LLVM from apt.llvm.org (or the explicitly selected
# ELISA_REMOTE_LLVM major), the z3 5.1.0
# RELEASE binary (apt's 4.8.12 makes contract-bearing compiles ~25x slower), Go 1.27.1, and
# the clang shim at /root/elisa/bin/clang (= tools/remote/clang_shim: dead_strip -> --gc-sections, drop
# -stack_size, -lLLVM -> the selected LLVM shared library, -no-pie +
# --unresolved-symbols=ignore-all on links).
# Work dir: /root/elisa. The box is SHARED (another session uses clang-19 from apt): nothing
# here touches /usr/local/bin, the default clang, update-alternatives or any global PATH.
# Our shim, z3 and llvm-config live in /root/elisa/bin and only our scripts put it on PATH.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" != --local ]]; then
  source "$HERE/hosts.sh"; host_ssh_args "${1:?host alias}"
  ssh "${SSH_ARGS[@]}" "mkdir -p /root/elisa && cat > /root/elisa/setup_host.sh" < "$HERE/setup_host.sh"
  ssh "${SSH_ARGS[@]}" "cat > /root/elisa/clang_shim" < "$HERE/clang_shim"
  exec ssh "${SSH_ARGS[@]}" "bash /root/elisa/setup_host.sh --local"
fi
GO_VER=1.27.1; Z3_VER=5.1.0
# ELISA_REMOTE_ROOT relocates the work dir on a box where /root/elisa is not ours.
# ELISA_REMOTE_LLVM_CONFIG selects an exact installed toolchain; ELISA_REMOTE_LLVM pins a
# major for reproducible remote runs. With neither set, install/select apt.llvm.org's latest.
W="${ELISA_REMOTE_ROOT:-/root/elisa}"
B="$W/bin"; mkdir -p "$B" "$W/tmp"
export DEBIAN_FRONTEND=noninteractive
log() { echo "[setup $(date +%T)] $*"; }
select_existing_llvm_config() {
  local candidate
  if [[ -n "${ELISA_REMOTE_LLVM_CONFIG:-}" && -x "$ELISA_REMOTE_LLVM_CONFIG" ]]; then
    printf '%s\n' "$ELISA_REMOTE_LLVM_CONFIG"
    return 0
  fi
  if [[ -n "${ELISA_REMOTE_LLVM:-}" ]]; then
    candidate="/usr/lib/llvm-${ELISA_REMOTE_LLVM}/bin/llvm-config"
    [[ -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  fi
  if [[ -x "$B/llvm-config" ]]; then
    printf '%s\n' "$B/llvm-config"
    return 0
  fi
  if [[ -n "${ELISA_REMOTE_ROOT:-}" ]]; then
    for candidate in /usr/lib/llvm-*/bin/llvm-config; do
      [[ -x "$candidate" ]] && printf '%s\n' "$candidate"
    done | sort -V | tail -n 1
  fi
}

LLVM_CONFIG="$(select_existing_llvm_config || true)"
LLVM_BIN_DIR=""
if [[ -n "$LLVM_CONFIG" ]]; then
  LLVM_BIN_DIR="$("$LLVM_CONFIG" --bindir 2>/dev/null || true)"
fi
if [[ -z "$LLVM_BIN_DIR" || ! -x "$LLVM_BIN_DIR/clang" ]]; then
  log "apt base"
  apt-get update -qq
  apt-get install -y -qq wget curl gnupg lsb-release software-properties-common unzip file gdb \
    build-essential rsync python3 git time zstd >/dev/null
  log "LLVM from apt.llvm.org"
  wget -qO "$W/tmp/llvm.sh" https://apt.llvm.org/llvm.sh && chmod +x "$W/tmp/llvm.sh"
  if [[ -n "${ELISA_REMOTE_LLVM:-}" ]]; then
    "$W/tmp/llvm.sh" "$ELISA_REMOTE_LLVM" >/dev/null
    apt-get install -y -qq "llvm-${ELISA_REMOTE_LLVM}-dev" "clang-${ELISA_REMOTE_LLVM}" "lld-${ELISA_REMOTE_LLVM}" "libpolly-${ELISA_REMOTE_LLVM}-dev" >/dev/null
  else
    "$W/tmp/llvm.sh" >/dev/null
    apt-get install -y -qq llvm-dev clang lld >/dev/null
  fi
  LLVM_CONFIG="$(select_existing_llvm_config || true)"
  if [[ -z "$LLVM_CONFIG" ]]; then
    LLVM_CONFIG="$(for candidate in /usr/lib/llvm-*/bin/llvm-config; do
      [[ -x "$candidate" ]] && printf '%s\n' "$candidate"
    done | sort -V | tail -n 1)"
  fi
  [[ -n "$LLVM_CONFIG" ]] || { log "llvm-config not found after installation"; exit 2; }
  LLVM_BIN_DIR="$("$LLVM_CONFIG" --bindir)"
fi
LLVM_LIB_DIR="$("$LLVM_CONFIG" --libdir)"
LLVM_INCLUDE_DIR="$("$LLVM_CONFIG" --includedir)"
[[ -x "$LLVM_BIN_DIR/clang" ]] || { log "selected LLVM has no clang: $LLVM_CONFIG"; exit 2; }
LLVM_CONFIG="$(readlink -f "$LLVM_CONFIG")"
ln -sfn "$LLVM_CONFIG" "$B/llvm-config"
if [[ ! -e "$LLVM_LIB_DIR/libLLVM.so" ]]; then
  llvm_shared="$(find "$LLVM_LIB_DIR" -maxdepth 1 -type f -name 'libLLVM-*.so*' -print 2>/dev/null | sort -V | tail -n 1)"
  [[ -n "$llvm_shared" ]] && ln -sfn "$llvm_shared" "$LLVM_LIB_DIR/libLLVM.so"
fi
if [[ ! -e "$LLVM_LIB_DIR/libLLVM-C.so" && -e "$LLVM_LIB_DIR/libLLVM.so" ]]; then
  ln -sfn "$LLVM_LIB_DIR/libLLVM.so" "$LLVM_LIB_DIR/libLLVM-C.so"
fi
if ! $B/z3 --version 2>/dev/null | grep -q "$Z3_VER"; then
  log "z3 $Z3_VER release binary"
  wget -qO $W/tmp/z3.zip "https://github.com/Z3Prover/z3/releases/download/z3-$Z3_VER/z3-$Z3_VER-x64-glibc-2.39.zip"
  rm -rf $W/tmp/z3x && unzip -q $W/tmp/z3.zip -d $W/tmp/z3x
  install -m755 "$(find $W/tmp/z3x -path '*/bin/z3' -type f | head -1)" $B/z3
fi
if ! $W/go/bin/go version 2>/dev/null | grep -q "go$GO_VER"; then
  log "Go $GO_VER"
  wget -qO $W/tmp/go.tgz "https://go.dev/dl/go$GO_VER.linux-amd64.tar.gz"
  rm -rf $W/go && tar -C $W -xzf $W/tmp/go.tgz
fi
if [[ -f $W/clang_shim ]]; then
  install -m755 $W/clang_shim $B/clang
  for n in clang++ cc; do ln -sf clang $B/$n; done
fi
log "versions:"; $B/z3 --version; $W/go/bin/go version; $B/llvm-config --version
 nproc; cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo "cpu.max: absent (no CPU cap)"
