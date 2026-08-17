#!/usr/bin/env bash
# Differential corpus for `project easm-lint`, and the progress metric for porting its
# verifier.
#
# stage0's easm-lint is a machine-state VERIFIER: 126 distinct issue codes over register
# liveness, stack alignment, callee-saved preservation, direction-flag state and operand-size
# inference (see docs/PORTING_GAPS.md). stage1 refuses every target carrying EASM inputs,
# because "clean" is a claim about all of those checks at once and a partial verifier cannot
# make it honestly.
#
# This harness exists so that porting the verifier is INCREMENTAL AND SAFE:
#
#   * It generates a closed corpus — an instruction whitelist crossed with section, signature
#     and ABI variants — and asks stage0 what it says about each. Over 900 configurations
#     reach only ~22 of the 126 codes, so the subset a real port must handle first is small
#     and, crucially, ENUMERABLE by running the oracle rather than by reading 3.9k lines.
#   * For each configuration it records one of three outcomes: AGREE (stage1 matched stage0
#     byte for byte), REFUSED (stage1 declined to report, which is sound), or DIVERGED
#     (stage1 reported something stage0 did not, or vice versa — never acceptable).
#   * DIVERGED fails the gate. REFUSED does not: refusing is the correct behaviour for an
#     unimplemented check. So the port can land one check at a time, and this reports
#     coverage moving from refused to agreeing without ever letting a false clean through.
#
# Today every configuration is REFUSED, and that is the baseline the number should climb from.
#
# The 22 codes this corpus reaches, with stage0's exact message text — harvested by running
# the oracle, so a port implements against measured strings rather than re-derived ones. All
# are severity `error`:
#
#   missing-body                  EASM export must contain a body
#   missing-stack-contract        EASM export must declare stack behavior
#   missing-control-contract      EASM export must declare control behavior
#   unknown-control-contract      unknown control contract <atom>
#   missing-capability            instruction "<op>" requires capability <cap>
#   unsupported-instruction       unsupported EASM instruction "<op>"
#   duplicate-param               duplicate EASM parameter <name>
#   missing-input-binding         parameter <name> must be declared in inputs
#   unknown-input-binding         input binding <name> does not name a parameter
#   invalid-register-binding      input binding <name> must use = <register>
#   missing-return-output         non-void EASM export must declare outputs: ret = <register>
#   unknown-output-binding        EASM v1 only supports ret output binding, got <name>
#   invalid-clobber-register      unknown clobber register <name>
#   invalid-preserve-register     unknown preserve register <name>
#   preserve-without-clobber      preserves declares <reg> but clobbers does not
#   returns-missing-ret           returning function must contain ret
#   noreturn-can-return           noreturn function contains ret
#   noreturn-missing-terminal     noreturn function must end in jmp or trap
#   unsupported-entry-fact        unsupported EASM entry fact "<fact>"
#   label-contract-without-label  label contract <name> has no matching body label
#   empty-label-precondition      label contract <name> must require at least one machine-state precondition
#   unexpected-top-level          expected module, target, export def, fragment, protocol, or template def
#
# The three tables those checks need, from stage0 (easm.go / easm_oprules.go):
#
#   control atoms   allowedControlToken: returns | noreturn | tail_jumps | may_fault
#   capabilities    easm_oprules.go, one entry per mnemonic —
#                     pause -> x86_64.sse.pause      lfence -> x86_64.sse.lfence
#                     trap  -> debug.trap            cpuid  -> x86_64.cpuid
#                     rdtsc -> x86_64.rdtsc          yield  -> aarch64.yield
#                     mrs/isb -> aarch64.cntvct      fldcw/fnstcw/stmxcsr -> x86_64.fpu_control
#                   cpuid and rdtsc also carry ImplicitReads/ImplicitClobbers, which is why
#                   the corpus above excludes them: they pull in the clobber checks.
#   registers       isRegisterName: rax..r15, eax..ebp, the 8/16-bit forms, x0..x30, w0..w30,
#                   sp, plus XMM and AArch64 SIMD names.
#   require tokens  allowedRequireToken, a ~40-entry closed list.
#
# MEASURED, by building it and watching this harness reject it: implementing SOME checks and
# accepting the routines they cover is NOT a sound increment. A parser plus three checks
# (duplicate-param, unsupported-instruction, missing-capability) took 8 configurations to
# agreement and put 808 into DIVERGED — because `missing-stack-contract` and
# `missing-control-contract` apply to every routine, so accepting any routine at all claims
# every check that could fire on it.
#
# The refusal boundary therefore cannot be drawn per-check. It has to be drawn so that no
# ACCEPTED routine can reach an unimplemented check, which for the universal ones means
# implementing them first. Practically: land the whole declaration-level set before the first
# routine is accepted, and only then widen the instruction model.
#
# So the port has no discovery left: the corpus, the 22 messages, and the tables are all
# here. What remains is writing the parser and the checks, each with a fixture that FAILS
# first — a passing fixture cannot tell an implemented check from an unimplemented one.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 20 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"

[ -x "$BIN" ] || { echo "easm_lint_differential SKIP: no stage1 binary at $BIN"; exit 0; }
[ -x "$ELISACORE_BIN" ] || { echo "easm_lint_differential SKIP: no elisac at $ELISACORE_BIN"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "easm_lint_differential SKIP: no python3"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

mkdir -p "$WORK/proj/src" "$WORK/proj/easm"
printf 'def main() -> i64:\n    return 0\n' > "$WORK/proj/src/main.elisa"
cat > "$WORK/proj/project.json" <<'JSON'
{"version":"0.1.0","include-dirs":["src"],
 "targets":{"app":{"entry":"src/main.elisa","emit":"llvm","easm":["easm/t.easm"]}}}
JSON

python3 - "$WORK/proj" "$ELISACORE_BIN" "$BIN" <<'PY'
import itertools, os, subprocess, sys

root, stage0, stage1 = sys.argv[1], sys.argv[2], sys.argv[3]
easm = os.path.join(root, "easm", "t.easm")

# A CLOSED subset: operand-free instructions only, so the corpus cannot wander into the parts
# of the verifier that need a full operand model. Widen this as the port covers more.
BODIES = ["pause\nret", "ret", "trap", "nop\nret", "lfence\nret", None]
SECTIONS = [
    [], ["clobbers: memory"], ["stack: unchanged"], ["control: returns"], ["control: noreturn"],
    ["requires: x86_64.sse.pause"], ["facts: pure"], ["labels: retry"], ["inputs: rdi"],
    ["outputs: rax"], ["preserves: rbx"],
    ["stack: unchanged", "control: returns"],
    ["clobbers: memory", "stack: unchanged", "control: returns"],
    ["stack: unchanged", "control: returns", "requires: x86_64.sse.pause"],
    ["clobbers: notareg"], ["preserves: nope"], ["control: bogus"],
    ["inputs: nosuch"], ["outputs: nosuch"],
]
SIGS = ["() -> void", "(a: uintptr) -> void", "() -> u64", "(a: uintptr, a: u64) -> void"]
ABIS = ["abi c", "abi ps4_sysv"]

def run(binary):
    p = subprocess.run([binary, "project", "easm-lint"], cwd=root,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr

agree = refused = diverged = 0
codes = {}
examples = []
for body, sect, sig, abi in itertools.product(BODIES, SECTIONS, SIGS, ABIS):
    lines = ["module t", "target any", f"export def r{sig} {abi}:"]
    lines += ["    " + s for s in sect]
    if body is not None:
        lines.append("    body:")
        lines += ["        " + b for b in body.split("\n")]
    source = "\n".join(lines) + "\n"
    open(easm, "w").write(source)

    rc0, out0, _ = run(stage0)
    rc1, out1, err1 = run(stage1)

    for line in out0.splitlines():
        line = line.strip()
        if line.startswith("[") and "]" in line:
            codes[line.split("]")[1].strip().split()[0]] = True

    if rc1 != 0 and "cannot verify them" in err1:
        refused += 1
    elif rc0 == rc1 and out0 == out1:
        agree += 1
    else:
        diverged += 1
        if len(examples) < 3:
            examples.append((source, out0, out1))

total = agree + refused + diverged
print(f"easm-lint differential: {total} configurations")
print(f"  agreeing with stage0 : {agree}")
print(f"  refused by stage1    : {refused}   (sound: an unimplemented check must not report)")
print(f"  DIVERGED             : {diverged}")
print(f"  stage0 issue codes reachable in this subset: {len(codes)}")
for source, out0, out1 in examples:
    print("--- diverging fixture ---")
    print(source.rstrip())
    print("  stage0:", " | ".join(out0.splitlines()[3:6]))
    print("  stage1:", " | ".join(out1.splitlines()[3:6]))
sys.exit(1 if diverged else 0)
PY
status=$?
if [ "$status" -ne 0 ]; then
    echo "easm_lint_differential FAILED: stage1 reported something stage0 did not (or the reverse)"
    exit 1
fi
echo "easm_lint_differential OK: no divergence (refusals are sound; see the counts above)"
