#!/bin/bash
# cmp.sh FILE... : build + run each program with stage0 (`-emit obj`, its default -O3) and
# stage1 (-O0); print the verdict (first diagnostic line) or the exit code and stdout.
# The quickest way to probe one shape by hand during difffuzz triage.
#   S0=elisac S1=elisac-stage1 RT=elisacore_runtime.o HOOKS=profile_hooks.c cmp.sh a.elisa ...
# Run inside the Linux host environment (clang shim on PATH, ELISA_HOST_LINUX=1, ...).
: "${S0:?stage0 elisac}" "${S1:?stage1 elisac}" "${RT:?runtime object}" "${HOOKS:?profile_hooks.c}"
H=$HOOKS
for f in "$@"; do
  d=$(mktemp -d); b=$(basename $f .elisa)
  for t in s0 s1; do
    if [ $t = s0 ]; then $S0 -emit obj -o $d/$t.o $f > $d/$t.err 2>&1; else $S1 -O0 -o $d/$t.o $f > $d/$t.err 2>&1; fi
    rc=$?
    if [ $rc != 0 ]; then echo "$b $t REJECT rc=$rc: $(grep -v warning $d/$t.err | head -2 | tr '\n' ' ' | cut -c1-200)"; continue; fi
    clang -o $d/$t $d/$t.o $RT $H 2>/dev/null; timeout 10 $d/$t > $d/$t.out; ec=$?; echo "$b $t exit=$ec out=[$(tr "\n" " " < $d/$t.out)]"
  done
  rm -rf $d
done
