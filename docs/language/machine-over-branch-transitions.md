# Branch transitions in `machine over`

`machine over` arm bodies may contain nested `if`/`elif`/`else` control flow. A branch
arrow (`-> State`) ends only the path that reaches it. Statements after a partial branch
run on the paths that fall through, and a later shared transition ends those paths.

Every path through the complete arm must end in a transition, `return`, or `break`. A
statement after an arrow in the same branch is unreachable and rejected. A complete
branch tree followed by another transition is also rejected as unreachable. Branches may
fall through to a shared suffix, but the suffix must finish every remaining path.

This first supported subset permits only payload-free target states and no transition
arguments on branch-local arrows. Arrows with payload arguments and arrows to states with
payload fields remain rejected until their path-local argument evaluation and shadowing
rules are implemented. Loops and `match` statements inside a machine arm remain refused.

The compiler threads each shared suffix into branches that fall through. An arrow, `return`,
or `break` ends that branch before the suffix, so lowering uses ordinary control-flow edges
and introduces no per-arm runtime flag. Because suffix statements are copied into branch
scopes, a local variable declaration on a branch path that falls through to a copied suffix
is rejected; this avoids changing which binding the suffix sees. Declarations confined to
terminal arrow, return, or break paths remain legal.
Transition arrows inside `can`, block, or value-expression wrappers are rejected.

The dynamic fixture `test/fixtures/machine_transition/branch_transitions.elisa` checks both
the branch-target path and shared-suffix fallthrough path at `-O0` and `-O2`.
