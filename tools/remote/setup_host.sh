#!/usr/bin/env bash
# One-command toolchain setup for a fresh Ubuntu 24.04 x86_64 gate host (memory note
# linux-gate-host). Idempotent: re-running skips what is already installed.
#
#   tools/remote/setup_host.sh <host-alias>        # from the Mac (alias from hosts.local)
#   bash setup_host.sh --local                      # on the host itself
#
# Installs: LLVM 21 (apt.llvm.org: llvm-21-dev clang-21 lld-21 libpolly-21-dev), the z3 5.1.0
# RELEASE binary (apt's 4.8.12 makes contract-bearing compiles ~25x slower), Go 1.27.1, and
# the clang shim at /root/elisa/bin/clang (= tools/remote/clang_shim: dead_strip -> --gc-sections, drop
# -stack_size, -lLLVM -> -lLLVM-21, -no-pie + --unresolved-symbols=ignore-all on links).
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
GO_VER=1.27.1; Z3_VER=5.1.0; LLVM="${ELISA_REMOTE_LLVM:-21}"
# ELISA_REMOTE_ROOT relocates the work dir on a box where /root/elisa is not ours;
# ELISA_REMOTE_LLVM=20 reuses an LLVM the box already has instead of apt-installing 21.
W="${ELISA_REMOTE_ROOT:-/root/elisa}"
export DEBIAN_FRONTEND=noninteractive
log() { echo "[setup $(date +%T)] $*"; }
need_apt=0
if [[ -x /usr/lib/llvm-$LLVM/bin/llvm-config && -x /usr/lib/llvm-$LLVM/bin/clang && -n "${ELISA_REMOTE_ROOT:-}" ]]; then
  : # relocated root on a shared box: reuse the LLVM it already has, never apt-install
else
for p in llvm-$LLVM-dev clang-$LLVM lld-$LLVM libpolly-$LLVM-dev gdb file unzip; do
  dpkg -s "$p" >/dev/null 2>&1 || need_apt=1
done
fi
if [[ $need_apt == 1 ]]; then
  log "apt base"
  apt-get update -qq
  apt-get install -y -qq wget curl gnupg lsb-release software-properties-common unzip file gdb \
    build-essential rsync python3 git time zstd >/dev/null
  log "LLVM $LLVM from apt.llvm.org"
  wget -qO /tmp/llvm.sh https://apt.llvm.org/llvm.sh && chmod +x /tmp/llvm.sh
  /tmp/llvm.sh $LLVM >/dev/null
  apt-get install -y -qq llvm-$LLVM-dev clang-$LLVM lld-$LLVM libpolly-$LLVM-dev >/dev/null
fi
L=/usr/lib/llvm-$LLVM/lib
[[ -e $L/libLLVM.so || -n "${ELISA_REMOTE_ROOT:-}" ]] || ln -sf "$(ls $L/libLLVM-$LLVM.so $L/libLLVM.so.* 2>/dev/null | head -1)" $L/libLLVM.so
[[ -e $L/libLLVM-C.so || -n "${ELISA_REMOTE_ROOT:-}" ]] || ln -sf $L/libLLVM.so $L/libLLVM-C.so
B=$W/bin; mkdir -p $B $W/tmp
ln -sf /usr/lib/llvm-$LLVM/bin/llvm-config $B/llvm-config
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
