# Compiler atom iteration

Run the focused implementation checks with:

```sh
ELISACORE_BIN=/path/to/stage0 python3 test/parity/compiler_atoms_smoke.py
```

Pass atom names to run only selected groups, for example
`python3 test/parity/compiler_atoms_smoke.py backend thread_shareability`.

Every subprocess has a 30-second timeout. The semantic and backend probes each
compiled, linked, and ran in about 1.7 seconds with a warm proof cache on the local
Mac during the 2026-10-21 continuation.

`scripts/compiler_atom_slice.py` keeps the current production implementations and
their direct-call closure, all data declarations, overloads with retained names,
protocol/impl members, and the standard runtime. Handwritten probe entry points
exercise region-only specialization, ordinary non-generic rejection, constant
registration/lookup, local shadows, scalar callback-result classification, and
constant-pattern lowering. Indirect function values may require explicit references
in a probe; this tool is a development aid rather than a general linker.

The `pymodule_struct_typedef`, `try_fallback_source`, `authority_coverage`,
`authority_annotation_index`, `iterator_alias_resolution`, `lmut_scope`,
`loop_program_view`, `type_region_suffix`, `holder_view_depth`, and
`holder_view_wrappers` atoms use `-strict`. All other atoms use `-permissive`, so unrelated dependency contracts
that cannot be proved in the sliced context retain their runtime checks. Source
checking and SMT stay enabled in both modes. These results do
**not** qualify a full strict compiler build or establish end-to-end incremental
build time. Keep the complete self-compilation check as a separate gate, also
capped at 30 seconds.

The `scalar_hash_native_smoke.sh` parity check compiles the production `ctx_hash_u64`
and `ctx_unhash_u64` helpers, runs twelve boundary and representative vectors, and
checks the unoptimized hash IR for the expected round operations so an inlined
inverse witness cannot escape the helper-call check. It is discovered by the
`test/parity/run_all.sh` smoke-file glob.

For parser/backend integration (including native execution), run:

```sh
ELISACORE_BIN=/path/to/stage0 python3 test/parity/region_constant_native_smoke.py
```

Set `ELISA_NATIVE_EMITTER_OUT=/absolute/path/to/emitter` to retain the linked
emitter after the temporary test workspace is cleaned up. This option copies the
executable immediately after a successful link; it does not reuse an older emitter.

This builds the current `test/breadth/emit_native.elisa` driver, then compiles,
links, and runs both syntax fixtures. Region-only specialization covers top-level,
module-qualified, and forwarded calls. Integer constants cover returned match
expressions, assigned matches, statement matches, and qualified module constants.
The emitter uses the concrete function's existing hidden-arena ABI for region-only
calls; region names do not become type-template arguments. Return-type resolution
uses the same selected function row as emission. Ordinary non-generic functions
remain ineligible for bracket specialization.

The native integration also checks `scalar_constant_or_match`: the word `or`
retains one OR-pattern (unlike `|`, which the parser expands into arms). Returned,
assigned, and statement matches compare each named or qualified integer constant
and exercise both hits and misses. The shared simple-pattern test resolves pins
through the local scope before constants; a backend atom verifies that a local
shadow emits a slot load rather than folding to the same-named constant. These
checks passed on 2026-10-21 against the current backend source. The atom-slicer
reference regression can run without a compiler using
`python3 test/parity/compiler_atom_slice_smoke.py`.

`scalar_pin_width_match` checks that pinned locals are loaded at their declared
width before conversion to the scrutinee width. Native cases cover unsigned
extension, signed extension, truncation, and pinned OR alternatives; the integration
script also checks the corresponding LLVM conversions. Strict stage0 checking and
current-source native execution passed on 2026-10-21.

`region_only_generic_name_collision` checks that a generic in an unrelated module
does not hide a concrete region-only function. It also exercises calls inside a
module and explicit calls to the generic. `qualified_generic_return_width` checks
module-qualified explicit generic calls directly in comparisons, including multiple
type arguments and same-named templates with different return widths. Type inference
now selects the same template slot as emission. Both fixtures passed strict stage0
checking and current-source native execution on 2026-10-21.

`generic_return_declaring_module` covers generic signatures whose unqualified
record names must resolve in the template's module. Its declaring and calling
modules define same-named records with different layouts; the larger result uses
the aggregate return ABI and is passed back into another generic. Return inference,
signature creation, parameter resolution, and arena queries now use the declaration
owner and restore caller scope. The backend atom checks owner restoration, and the
native fixture passed on 2026-10-21.

The focused runner also includes `thread_shareability`: a forbidden callback result
produces `ThreadResultNotShareable`, and the probe reads that diagnostic after the
checker's scratch region is released. This checks diagnostic ownership without
qualifying the complete semantic checker. All four atom groups passed with the
2026-10-21 summary-fixes bootstrap, but full-checker lifetime diagnostics have varied
between runs and remain unresolved.

The `exclusivity` atom invokes the real call-argument checker with two mutable
references to the same place. It verifies `CallArgumentAlias` and the retained
place, callee, and parameter names after scratch release. It passed with the
enum/trace bootstrap on 2026-10-21.

The original two integration fixtures passed on 2026-10-21 with every subprocess capped at
30 seconds. The semantic and backend atom checks also passed (2.06s and 1.59s).
The integration emitter omits the semantic pass, so use both scripts together.
The installed stage1 executable has not been refreshed by these checks: the full
strict bootstrap remains a separate gate and has previously exceeded the 30-second
limit. No full self-compilation or sub-10-second incremental-build result is claimed.

## Bootstrap profiling under the 30-second cap

The 2026-10-21 continuation added bounded profiling in the sibling Go bootstrap:
`ELISACORE_CPUPROFILE_SECONDS` and `ELISACORE_MEMPROFILE_SECONDS` flush their
respective profiles before the external timeout. The existing profile paths still
come from `ELISACORE_CPUPROFILE` and `ELISACORE_MEMPROFILE`.

An 18-second allocation sample exposed about 832 MB of temporary token slices in
proof-cache alpha normalization. A streaming scanner preserves canonical cache
keys and passes malformed-input, capture, solver-parity, and cache-integrity checks.
A subsequent 18-second sample recorded 3.57 GB allocated versus 4.51 GB previously;
these are partial samples, not total-build or elapsed-time results. The small-query
benchmark now reports 936 B/op and 3 allocations (previously 1,656 B/op and 7).

Packed-store type discovery now remembers each type's shallowest visited depth,
so shared DAGs are not repeatedly expanded. Tests cover cycles, distinct roots,
and a shorter revisit that must still discover a root within the depth budget.
The lexer capacity estimate changed from source bytes / 4 to / 7: the driver
measured 23,086,542 source bytes, 3,142,013 tokens, and capacity 5,771,635 before,
versus capacity 3,298,077 after. Lexer tests pass; denser inputs still grow normally.
Resolved pointer-free records and integer enums can also answer empty lazy
provenance summaries from their type. Reference, owning, generic, unresolved, and
recursive types retain the ordinary inference path. Regression tests verify body
diagnostics still run, including an invalid callee returning a scalar record.

Full O0 driver bootstrap attempts still reach the 30-second limit during body
analysis. A warm proof-cache comparison also timed out. Precompute inference still
measured about 6.53 seconds after these changes, so no end-to-end timing improvement
or successful current stage1 rebuild is established. The existing shard cache
starts after analysis and cannot bypass that remaining gate.

`test/breadth/check_native.elisa` is a native diagnostic driver for the complete
current `Semantic::check` entry point; `scripts/expand_source_probe.py` prepares an
include-expanded stdin unit with an optional physical-line map. This diagnostic
route is separate from strict full-bootstrap qualification.

The sibling bootstrap's `ELISA_STORE_PAYLOAD_TRACE=1` emits only failed
program-lived-payload proof paths. Set it to a declaration-name prefix instead to
filter the output. Each record names the source/target parameters, failure reason,
expression position/kind, and already-recorded expression type (or `<missing>`).
Tracing never resolves a type or runs an extra proof to fill a missing entry.


## Store-summary correctness continuation

The bounded native semantic driver reached analysis completion in 16.2 seconds
with `-permissive`, then rejected source lifetime errors. That flag keeps unproved
contracts as runtime checks and is used only for diagnostic tooling; it does not
qualify a strict stage1 bootstrap. The rejected calls included borrow-replay flow
forwarding and two checker-to-SymbolTable boundaries.

The sibling Core return-summary scan now joins only the value branches of a
conditional return, rather than retaining storage used solely by its predicate.
Regression cases first failed for typed and untyped callee bodies; they now pass,
including a negative control ensuring stores made by the predicate still count.
A separate cold/warm projection regression found that element copies through
`param.rows[index].field` needed the existing parameter-projection type resolver
before the callee body was typed. The localized fallback preserves rejection of
unqualified views and copied nested container headers.

The production borrow replay copy path now writes into destination-owned snapshot
buffers. Its native probe merges return, break, and continue snapshots from a
scratch region, reads them after that region is freed, and checks self-copy.
Earlier full-program and isolated probe results disagreed, so the isolated success
alone is not evidence that every full-program lifetime error is resolved.
The new Core binary passed semantic, backend, and borrow-replay atom groups in
2.24s, 1.54s, and 1.12s respectively. Full checker and bootstrap gates remain separate.

Later full-checker runs exposed cold/warm variance: one run reported four lifetime
errors, another again reported about 65. That four-error result is not a stable
qualification. Parallel read-only callee copies intentionally have no body
expression-type facts, so static summary precision must match warm bodies.

New Core regressions cover pointer-free scalar/tuple return values: reading a
container's count does not make the returned integer borrow the container.
`uintptr` and tuple-contained container headers still retain their dependencies.
A further cold/warm fresh-result test found that writing a Boolean comparison
(e.g. `merged.closed[key] <- merged.owner_heads[key] == 0`) could invalidate the
fresh-result proof before body typing. Static typing now recognizes comparisons
and Boolean connectives as Boolean results. Controls retain real input headers and
independent stores performed by Boolean-returning helper calls. The next complete
checker run finished analysis in 16.488s and had no borrow-replay forwarding errors,
but still rejected seven other checker-to-table lifetime boundaries. No checker
executable or full current stage1 bootstrap is yet qualified by those results.

Ordinary enum payloads now retain program-lived view proofs across common fields,
variants, and refinements. Packed stores still require their declared store proof;
unqualified views and local packed roots remain rejected. The resulting bootstrap
binary passed all five focused groups: semantic, backend, borrow replay, thread
shareability, and exclusivity. The latter two execute the real checkers and inspect
diagnostics after their scratch regions are freed.

A further cold-body regression covers `local[index].field` when the local has an
explicit `darray[Struct]` declaration and the struct mixes program-lived and
borrowed fields. The scanner reads that declared element type without resolving or
warming body types. It accepts the program-lived field while retaining dependencies
for borrowed siblings and nested array headers. Parameter/other bindings, conflicting
declarations, generic shadows, and ambiguous or unrelated module type names remain
conservative. Related Core store-scan and program-lifetime tests pass; this patch
still requires the next full-checker snapshot.

The readonly-reference metadata path now states its existing source-text lifetime:
`type_names` vector elements, AST bare-name results, and symbol-table field-name
results are source-lived views. The temporary vector buffers keep local ownership.
The new `readonly_ref` atom runs the real checker in a scratch region and reads its
diagnostic after that region is freed; it passes independently. The default atom
runner initially expanded to six groups; that first combined rerun stopped at the
error-union checker boundary.
`test/parity/readonly_metadata_contract_smoke.py` confirms a direct push of a
short-lived view into a source-view metadata vector is rejected. The initial bootstrap
accepted a separate forwarded-argument repro; the caller checks described below
subsequently reject it.

A focused Core loop-binder regression now recovers `sview @source` elements from
one explicitly typed local array declaration before body typing. This records the
view's declared lifetime without changing local buffer ownership. Borrowed views,
`cstr` elements, other binders, and matching generic/local region shadows retain
conservative behavior. Related store-scan and program-lifetime tests pass. The
ordinary direct copy case already passed before this change, so only the next
complete checker run can establish its effect on the strict-unsafe boundary.


Caller contract enforcement now checks concrete program-region `sview` parameters,
including functions with no generic region parameters. Before the change, both a
short-region view and a region-less borrowed parameter could be forwarded into
`sview @source`; both are now rejected. Literals and source-qualified parameters
pass, including reordered named arguments. A complementary Core check validates
`darray[sview @source]` element promises separately from the array buffer lifetime:
local buffers with source-lived elements pass, shorter-lived elements do not.
Related Core regressions pass. The twelve binary-level cases in
`test/parity/program_view_call_contract_smoke.py` now pass against the rebuilt
`codex-elisac-source-contracts3` snapshot, including local-buffer positives and
reordered named vector arguments.

Enabling the previously missing scalar caller checks exposed source metadata
signatures that omitted the lifetime already required by AST and symbol fields.
Those requirements are being propagated to callers rather than suppressing the
checks. Complete-checker snapshot `codex-check-native-current` reported 249 actual
lifetime errors (warnings excluded); `codex-check-native-contract2` reported 88.
Both runs finished within the 30-second cap and rejected the compilation. The
error-union summary boundary reproduced more often with declined-SMT caching
enabled, but identical enabled invocations also disagreed. A cache-disabled
successful atom is not accepted as final validation.


The atom runner now includes a seventh `error_union` group. It checks that a bare
fallible call produces a diagnostic that survives scratch-region cleanup, while
ordinary calls and try-wrapped calls do not. Its compile result remains sensitive
to summary context until the pending payload-proof changes are tested in a rebuilt
binary. Core regressions cover preserving an immutable local's checked
`sview @source` declaration before re-inferring a conditional initializer, and
judging a builtin same-place `push` assignment by its appended payloads. Cold
record-literal proofs use the exact declaration in the inspected function's
namespace; borrowed fields, copied container headers, and namespace/type shadows
retain conservative behavior.


The next binary also enforces source-view element contracts at calls, which exposed
unqualified metadata vectors that scalar checks could not catch. The first complete
nested-contract run reported 485 errors; subsequent exact-call-site annotation
propagation reduced that to 227 and then 82. These counts describe rejected
snapshots, not regressions in language syntax or a successful bootstrap. Local
vector backing lifetimes remain unchanged.

A separate reduced packed-enum match regression reproduced the refinement caller
failure: a program-lived view returned by `node_name` was incorrectly propagated
as a borrow of the caller's local enum handle. Call return-borrow analysis now
honors an explicit, non-generic program-region `sview` result, while retaining the
callee dependency and independently validating its body. The positive match test,
ordinary program-result controls, caller short-view negatives, and invalid
program-return body control pass together.


Complete nested-contract propagation snapshots then reduced the remaining
lifetime errors to 14 (`contract8`) and 3 (`contract9`), with all compiler
invocations bounded at 30 seconds. The three were the error-union and private-field
summary boundaries plus one final name-vector qualifier. The last qualifier is
corrected; a successful complete checker build is still outstanding.

The Diagnostic construction proof now handles omitted scalar and static-view
defaults without declaring every Diagnostic value program-lived. A reference
default is accepted here only when it is a static string literal in an `sview`
field; other reference defaults remain unproved because they resolve in the
struct's declaration scope, not the caller's scope. A regression first reproduced
an incorrect proof caused by a same-named caller local, then confirmed rejection
after this guard. Borrowed overrides, address-integer defaults, container defaults,
and opaque view defaults remain rejected. `ELISA_STORE_PAYLOAD_TRACE` additionally
emits `STORELITERAL` field/reason records when this construction proof fails.
Trace-enabled controls pass with the same decisions. The pending combined binary
must still validate the actual error-union boundary in its larger summary context.


The error-union boundary is absent from the next full snapshot (`contract11`), and
its larger semantic atom passes with tracing enabled, disabled, and filtered.
That complete snapshot still rejects readonly-reference and private-field
boundaries. Their traces identify builtin `darray.push` calls being analyzed again
as unresolved user callees after their receiver payloads were already checked.
A source-backed regression reproduces the nested read of the target in the payload;
controls retain borrowed overrides, hidden effectful nested calls, and user-defined
`push` methods. The builtin handling fix and related Core tests pass, awaiting the
next complete build.

Program-lived record return types also keep their declared field contracts before
body typing. A new cold-body regression failed with `storeHeader` for a record
containing only a source-lived view; it now retains no parameter storage. A record
with an unqualified borrowed view still retains dependencies. Recursive payload
proof state is now distinct from store-mode traversal state; all concrete stores
and unknown calls remain checked, with borrowed/header and preseeded-mode controls.

The parallel ownership audit now recognizes exact region-qualified `sview`
spellings when classifying descriptor copies and mutable aliases. A qualified view
still counts as carrying a reference: returning a table-owned view record or
casting its backing to a mutable pointer remains rejected. Containers, mutable
references, owning strings, and malformed qualifiers keep their conservative
classification. All 92 focused audit tests pass; the complete generator audit has
not been rerun during the compiler profiling pipeline.

On `codex-elisac-source-contracts5`, the semantic, readonly, and error-union atom
groups compile, link, and run successfully. The readonly proof now finishes
handling a verified builtin array `push` after checking its payload, rather than
trying to resolve the builtin as a user function when a payload reads the target.
Nested helper calls still receive their own store checks; controls retain borrowed
payloads, hidden stores, and user-defined methods named `push`. The complete
checker remains a separate timing gate: semantic completion alone does not prove
an object was emitted within the 30-second cap.


Current combined Core binary `/tmp/codex-elisac-payload-memo` passes all seven atom
groups and all seven native region/constant/backend fixtures. The complete unpruned
checker source snapshot `codex-check-native-contract11.elisa` also passes full
semantic analysis (`-emit iface -permissive -O0`) in 16.46 seconds. This is a real
zero-error semantic result, with permissive dependent-contract runtime checks;
it is not a strict shipping bootstrap or a current stage1 self-compile.

The first complete object builds still hit the 30-second cap. A saved profile
identified repeated recursive payload proof traversal; completed obligations are
now memoized only within one root proof. Late unsafe-ancestor, diamond, borrowed
payload, header, and foreign mode-marker controls pass. The next object run
finishes semantic analysis but still exceeds the cap in backend work. LLVM emission
is being measured separately before further optimization; no complete checker
executable is claimed yet.


The complete checker LLVM artifact emitted in 21.36s; LLVM clang produced its object
in 4.28s and linking took 0.14s. Investigation of the combined object timeout found
that Core always selected LLVM's default machine-code optimization even for `-O0`.
It now selects machine-code level None for O0, preserving other levels. Existing
O0 object/native-target and explicit AArch64 O2 tests pass. The combined checker
object build then completed in 28.67s, within the 30-second cap.

Executing the complete checker exposed an independent return-arena bug: clean
input passes, but diagnostics have preserved counts and zeroed records. LLVM for
`Semantic.check_full` copies the returned SymbolTable descriptor and then frees
its local arena, without a caller arena parameter. Its diagnostic arrays therefore
point into freed storage. Isolated real-Diagnostic-layout indexed/for/copy and
overwrite probes pass, so the worker-copy code is not being changed on speculation.
A focused returned-owning-struct/move/wrapper regression and inference fix are in
progress. Until corrected, this checker executable's diagnostic contents are not
qualified and it has not established current driver self-compilation.


A further source-backed registration regression found that parser `global region`
rows use `owner == "__global_region"` with the actual region in `name`, while the
semantic pre-registration loop recognized only the legacy `__region_name` form.
The semantic atom failed with exit 100 before the change and passes after it.
Global region selectors now enter `region_names` alongside lexical region binders;
this is separate from accepting a function's region-only specialization arity.

The complete native checker exposed a returned-table lifetime bug: `check_full`
copied its table descriptor to the return slot and then freed the backing arena.
Region-polymorphic inference now looks through `move`, preserving the caller arena
across a same-named constructor, lmut fill, and return wrappers. The native
`returned_record_arena_smoke.py` regression changed from a zeroed element after
allocation churn to success. Five complete native checker content cases now pass
via `native_checker_smoke.py`: clean input, undefined names, readonly references,
dropped error unions, and overlapping mutable arguments. The rebuilt O0 checker
emits an object within the 30-second cap after selecting LLVM's unoptimized machine
code level for O0. This remains distinct from strict-bootstrap qualification and
from checking the entire expanded compiler driver, which still exceeds the cap.

A separate Core return check now preserves a moved aggregate's interior region
taint. Named short-region buffers are rejected in plain, moved, parenthesized,
and nested moved returns; caller-owned and program-owned regions remain valid.
The focused escape/move tests pass. This rejects invalid ownership transfers rather
than adopting explicitly named short regions into the caller.


After the move-return inference fix, the rebuilt complete checker builds in 26.65s
and passes real-content diagnostic integration tests. Region-only specialization,
same-name generic-module collision, and named integer constant match fixtures all
produce zero diagnostics. Ordinary non-generic specialization and local constant
shadow fixtures still reject with their correct nonzero kinds/locations. The word
`or` constant fixture remains a distinct semantic gap (three kind-609 syntactic
binder reports); native backend execution alone does not qualify its full checker.

The first complete native driver semantic run reaches the 30-second cap. Opt-in
pass timing identifies authority return summaries (~7.5s) and inference (~7.3s),
with reporting still in progress. A summary-only void-result shortcut is pending
runtime validation; it does not skip inference/reporting of global effects. Added
void and scalar global-effect integration controls capture 4 and 5 expected
findings. Whole-checker clang O1 optimization also exceeds 30s; a bounded cost
experiment optimizing only 234 authority functions finishes in 11.05s. That cost
probe uses an older LLVM snapshot and is not a qualified runtime artifact. The
next current snapshot must validate its semantic controls and actual driver time.


The OR-selector follow-up adds aligned parser pattern handles beside the recorded
arm spans. Serial lexical type resolution records exact integer-constant OR
handles; the parallel reporter skips only those verified handles. This preserves
local and parameter shadow rejection without a text-based exemption. The focused
`or_constants` atom exercises actual lexer/parser metadata production and the real
scalar checker/reporting functions, including a distinct same-text shadow pattern
and its original diagnostic span; it passes in 4.59s. The changed reporter remains
append-only under the source audit, and all 92 audit unit tests pass. The nine-case
`scalar_or_constants_smoke.py` is awaiting the rebuilt complete checker: the old
checker rejects both valid cases, while all seven invalid controls already pass.


`authority_return_origin_smoke.py /path/to/check_native` adds a separate guard for
summary optimizations. A getter returns a mutable `void&` into global storage with
its local effects granted. The caller grants the getter call, then casts/writes
without a local Global.Write grant. The old live checker retains both expected
kind-404 reports at the cast and write (lines 7 and 8). A type-head test for `void`
would also match pointer-wrapped `void`; the coordinator restricted
both void guards to exact identifier expressions before rebuilding. The refreshed
full checker LLVM emission succeeds in 20.40s; native regression results are pending.


The refreshed Core binary also passes all six CLI-level cases in
`moved_aggregate_escape_smoke.py`: plain, moved, parenthesized, and nested moved
short-region aggregates reject with the region escape diagnostic; caller-owned
Arena and program-region returns accept. These use interface emission to exercise
the actual source analysis without another LLVM object build.


The current `/tmp/codex-check-native-authority` executable now passes all nine
OR-selector integration cases: expression/slot/statement and module constants
accept; parameter/local shadows, true binders, wrong constant types, character
names, partially unresolved patterns, and nested payload bindings reject. Both
void-pointer global-origin cases pass (two exact missing-write diagnostics and
zero diagnostics with local grants). The fresh Core binary also passes the moved
returned-record runtime regression with allocation churn and all twelve source-view
caller-contract cases. These qualify current diagnostic content and targeted
lifetime behavior; the full expanded-driver timing is still a separate gate.


Further read-only summary investigation found two unqualified authority cases.
On the current optimized native checker, a global-pointer return followed by zero,
one, or three wrappers produces the two expected missing-write findings; four,
five, or eight wrappers produce zero findings. A function returning either of two
global pointers also produces zero caller findings. The four-round summary cap and
UNKNOWN-to-detached conversion make these results weaker than the direct known
single-origin case. Exploratory reproducers are saved as
`/tmp/elisa-helper-authority-deep-return.elisa` and
`/tmp/elisa-helper-authority-union-return.elisa`; no failing case has been added to
the shared passing smoke gate. The bootstrap also accepts the deep-wrapper case,
so the intended opaque-call compatibility policy must be considered when fixing
source-defined may-global summaries. All earlier targeted passing claims remain
limited to their stated cases.


The offline `compare_semantic_timings.py` helper compares completed phase rows and
keeps truncated summary sweeps separate from final reporting. Its three parsing
regressions pass. On the same current LLVM snapshot, recorded pre-authority
sequential phases total 15,946.9ms at external-clang O0 and 12,363.9ms with scoped
O1; authority setup is 526.6ms versus 234.6ms. Both remain incomplete at the cap.
Old direct-Core-object versus fresh external-clang comparisons also have a verified
target mismatch: dry-run clang `-###` selects apple-m1 by default and apple-m5 with
`-mcpu=native`, while Core direct native objects select host CPU/features. This
must be controlled before attributing the older/fresher timing gap to source.


The CPU-target confound is now controlled. Recompiling the same current LLVM with
clang O0 `-mcpu=native` takes 4.30s, linking 0.14s, and the resulting checker passes
all seven diagnostic, nine OR, and two pointer-origin controls. With matching
`ELISA_STAGE1_TIMINGS=2 ELISA_SEMANTIC_SERIAL=1`, its driver run still reaches
30.28s inside summaries. Generic versus native pre-authority wall totals are
15,946.9ms versus 15,632.4ms (CPU totals nearly equal), and both observe summary
sweep lower bounds [7168, 2048]. CPU tuning is therefore not the primary cause of
the present timeout. The native artifact is `/tmp/elisa-helper-check-native-m5`.

`authority_summary_rounds_smoke.py` captures thirteen current-policy cases for the
coordinator's dependency-driven summary-round optimization. Shallow/forward chains,
argument origins, overload selection, exact write locations, and matching grants
are checked, alongside explicit existing opaque/deep/recursive/mixed-global
limitations. All thirteen pass on the pre-optimization authority checker. This
comparison gate preserves current behavior while the traversal is changed; it does
not certify complete alias tracking for the documented zero-report limitations.


A separate paired IR probe now isolates packed-read helper optimization. Starting
from the same authority-O1 LLVM snapshot, only `ctx_aos_store_record` and
`ctx_aos_store_sized_record` regain normal optimization attributes; all other bodies
and attributes stay unchanged. Compile/link take 12.17s/0.14s. All 112 existing
authority fixture outputs match the baseline exactly, and the seven diagnostic,
nine OR, two pointer-origin, and thirteen summary controls pass. Recorded
pre-authority wall time falls from 12,363.9ms to 10,604.6ms; firm argument checking
falls from 2490.2ms to 1663.9ms and declaration resolution from 1603.1ms to 1274.9ms.
The driver still hits 30.28s, reaching four observed summary sweeps rather than
three. No completed whole-driver speedup is claimed. The record helper shrinks
from 43 to 18 AArch64 instructions and retains its bounds trap in both objects.
Artifacts are `/tmp/elisa-helper-authority-packed-reads` and matching `.ll`/`.o`;
assembly comparisons are `/tmp/elisa-helper-ctxrecord-before.asm` and `-after.asm`.


The measured packed-read probe is reproducible with:

```sh
python3 scripts/authority_probe_ir.py INPUT.ll OUTPUT.ll --packed-reads
```

Omitting the flag retains the original authority-only control. The tool now copies
original group-0 attributes when adding `optnone`/`noinline`, preserving target CPU
attributes; preexisting special attribute groups remain untouched. Four offline
CLI regression tests pass, including refusal of helper-only or already-optnone
inputs. The regenerated real probe differs from the measured IR only in the order
of equivalent attributes on the appended cold group.


`scripts/compare_native_checker_snapshot.py CHECKER SNAPSHOT.json` compares every
captured source/status/stdout/stderr in both dependency and full-summary modes,
with timing output disabled. The retained `/tmp/elisa-helper-summary-all-before.json`
contains all 112 existing authority fixtures, all parser-clean. The comparator
passes on the old checker and is ready for the rebuilt dependency-round checker.
The thirteen-case summary smoke runner also compares both modes automatically.

The rebuilt dependency-round checker now passes that gate: all 112 saved fixture
outputs match exactly in both modes (224 comparisons), and all thirteen focused
summary cases match between modes. The seven general diagnostic, five region and
constant, nine OR-pattern, and two void-pointer-origin controls also pass. Source
LLVM generation takes 20.47s and scoped authority plus packed-read object emission
takes 11.74s, each under the 30-second cap. The dependency graph uses parallel
scalar edge arrays; duplicate edges only repeat an idempotent dirty-bit update.
The earlier dictionary representation was rejected because it introduced new
global-effect requirements. This validates fixture equivalence, not complete
self-compilation or the incremental timing goal.

The source-matched expanded driver run reaches the cap at 30.31s during authority
inference (progress 5120). Return summaries now finish in 11,117.8ms across three
rounds: 5395.3ms, 5478.5ms, and 243.7ms, with 19,772 recorded dependency reads.
The final sparse round demonstrates reduced revisiting; the earlier packed-read
control still timed out inside summary traversal. Full checking remains unfinished.

A two-second native sample during summaries attributes 1004 of 1655 top-of-stack
samples to the five inverse-hash arithmetic helpers, with another 144 in string
indexing. The attribute-only `--context-lookups` probe enables O1 for eleven hash,
inverse-hash and string-index helpers without changing LLVM bodies or source
contracts. Its object builds in 11.90s, and all 112 saved fixture outputs match in
both modes; thirteen summary and all focused language controls pass, including the
new primitive-spelling reference-alias control. On the identical expanded driver,
return summaries fall from 11,117.8ms to 2843.9ms, inference finishes in 3044.7ms,
and effect-row closure takes 462.1ms. The run still reaches 30.30s, now after
`check_call_argument_exclusivity` following parallel group 27. Self-checking has
not completed. Exact primitive-return skipping remains deferred because aliases
can give primitive spellings reference-carrying meanings.

The additional `--lookup-tables` control optimizes dictionary probes, semantic
name hashing, and string equality, adding fourteen functions to the hot set. Its
object builds in 11.58s and all 224 snapshot comparisons plus 37 focused controls
pass. Serial driver checking reaches group 44 at 30.34s; normal parallel mode
also reaches group 44 at 30.35s. The cap still prevents a completed check.

A whole-module local cleanup is a separate bounded experiment:

```sh
timeout 30 opt -verify-each \
  -passes='function(mem2reg,instcombine<no-verify-fixpoint>,simplifycfg)' \
  -S ORIGINAL.ll -o CLEAN.ll
```

It takes 2.95s and shrinks the original 188MiB IR to 162MiB. LLVM's default
single-iteration fixpoint assertion failed after 1.15s in `arena_vsprintf`; the
explicit InstCombine option follows the tool diagnostic and disables only that
fixpoint assertion. `-verify-each` still validates IR after each pass. Applying
the same three hot-helper controls to cleaned IR and emitting the object takes
10.80s. All 224 snapshot comparisons and 37 focused controls pass again. These
remain development artifacts; the installed stage1 has not been replaced.

The cleaned checker completes all semantic passes on the source-matched expanded
driver in 29.57s, returning 206,540 diagnostics. This is a completed diagnostic
run, not successful self-compilation. Of those findings, 102,987 are missing
Global-call grants. A single depth diagnostic at expanded line 274547 maps to
`semantic_parallel_passes.elisa:277`: the generated 221-arm `elif` chain exceeds
the authority walk's depth bound and intentionally marks every function as
possibly reading and writing globals. The dispatcher and generator now use
independent `if` arms over an immutable unique pass ID, preserving dispatch while
keeping the AST shallow. The audit accepts consistent legacy chains or flat arms
and rejects mixed shapes; all 93 audit regressions pass. Depth bounds and the
conservative overflow behavior remain intact. Fresh full-source qualification is
required after this fix.


The rebuilt `/tmp/codex-check-native-dependencies` now passes exact baseline
comparison for all 112 authority fixtures in both dependency and full-summary
modes (224 comparisons). All thirteen focused return-summary cases also pass and
produce identical outputs in both modes. The full-source LLVM build takes 20.47s;
authority-plus-packed-read clang optimization takes 11.74s. These results qualify
behavioral equivalence for the tested fixtures, including their documented existing
opaque-result limitations; the full expanded-driver measurement remains pending.


The dependency-round checker completes authority summaries in 11,117.8ms, with
rounds of 5395.3ms, 5478.5ms, and 243.7ms and 19,772 dependency edges. The expanded
driver still reaches the cap during inference. A proposed exact-primitive summary
shortcut remains deferred: builtin-spelling aliases require care, because
`ga_builtin_unshadowed` follows aliases. The clean alias reproducer
`/tmp/elisa-helper-primitive-alias-counterexample.elisa` uses
`alias i64 = mutable void&` and retains exact missing-write findings at lines 8/9.
A fresh native sample instead points to unoptimized integer hash/unhash and view
index helpers; the coordinator is measuring those on the same LLVM snapshot.


The attribute-only context-lookup probe `/tmp/codex-check-native-context` also
passes all 112 exact fixture comparisons in both modes, all thirteen summary mode
pairs, and all three pointer-origin controls. The third control now durably checks
the primitive-spelling reference alias at exact lines 8/9. This context probe adds
O1 for eleven profiled hash/unhash/view-index helpers without changing source
contracts or LLVM bodies; object emission takes 11.90s. Its paired driver timing
is pending, so no completed-driver improvement is yet claimed.


The context-plus-lookup probe completes authority in 7984.6ms (summaries 2008.2ms,
inference 2224.7ms, report walk 3037.9ms) and reaches parallel group 44/48 at the
cap, compared with group 27 for context helpers alone. Serial and normal parallel
runs both remain capped near 30.3s. The coordinator's next attribute-preserving
control first runs local LLVM passes across the original IR: mem2reg,
instcombine<no-verify-fixpoint>, and simplifycfg, with `-verify-each` retained.
This cleanup takes 2.95s and reduces text IR from 188MiB to 162MiB. Scoped O1 then
emits its object in 10.80s; the resulting checker passes all 224 fixture/mode
comparisons and 37 focused controls. Whole-driver timing is pending.

A read-only region-pass review found `allocated_local_region` computes allocation
lookup/direct-allocation checks for every variable declaration before filtering
by the requested binding name and source line. Moving that exact filter earlier
would preserve its last-match ordering and avoid work on unrelated declarations.
No production change has been made while the current LLVM control is measured.


The early allocation-name filter is qualified by the ninth compiler atom,
`region_assignment`: the actual helper preserves last direct allocation matches,
line cutoffs, unrelated-name rejection, parenthesized allocation handling, and
last-row allocation metadata on duplicate lines. It compiles/links/runs in 1.23s.
`region_assignment_smoke.py` also passes seven full native cases on the fresh flat
checker, matching the prefilter results exactly. Existing overlapping negative
region reports are recorded as comparison baselines rather than endorsed as an
ideal diagnostic count.


On the full expanded driver, the preflattened native semantic run completes in
29.57s with 206,540 diagnostics. Of these, 102,987 were Global permission errors
caused by a single depth-overflow report: the generated 221-arm pass dispatcher
was represented as a nested `elif` chain. Its generator and source now use
independent `if` arms over unique immutable pass IDs. The dispatcher audit accepts
either consistent legacy chains or the flat form, rejects mixed forms, and has
93 passing regressions. The fresh run on flat arms completes in 26.76s with
104,438 diagnostics and zero depth reports.

The test checker now has an opt-in `ELISA_CHECKER_ERRORS_ONLY=1` mode that uses
the same semantic severity function as the driver. Default fixture output is
unchanged; smoke tests cover both modes. It reports 1,720 error-severity
diagnostics on the flat full-source snapshot. The largest groups are mutable
global calls (759), short-lived region stores (416), aggregate stores (267),
mutable global reads (87), tied returns (86), and region-store escapes (33).
Warning and note rows no longer inflate this count.

One region false positive has a fully checked reproducer. `backend_type_visit_grow`
stores a freshly allocated bucket array through a caller-owned mutable set. A
tiny Core-built executable survives allocation churn and validates its contents;
the stage1 checker previously rejected the store. The fix gives `visited` and its
temporary `new_buckets` the same inferred region parameter. The expanded checker
with this edit built previously; a focused backend atom now inserts nine keys,
crosses the hash-growth threshold, and verifies the promoted table.


## 2026-10-21 continuation checks

The Stage1 product smoke now checks that region-only generic calls and immutable
integer constants in match arms are accepted, while ordinary functions with a
region argument and a shadowing local remain rejected. The new Stage1 smoke passes
against the rebuilt `/private/tmp` product. The
checked-in `bin/elisac-stage1` is older than the current source and must be reseeded
before the product gate can use it.

The driver line-map cache parity smoke passes. Sorted flat-line entries now use an
upper-bound binary search, preserving the last duplicate entry; unsorted maps keep
the linear fallback. Its focused Stage0 benchmark measures 56.1 ms uncached and
2.1 ms cached for 500 lookups across 2,000 map entries. The Stage1 benchmark fixture
currently includes an unrelated parallel-runtime body that the available Stage1
products decline (`for_indices_par`), so that path has no current timing result.

The full self-host gate remains open. Stage1 `-emit check src/driver/elisac.elisa`
timed out twice at the 29-second cap, and a cold Stage0 `--seed -O0` did the same.
Retrying through the running retained server returned HTTP 409 and fell back to the
cold compile before the cap. The incremental semantic-session control passes the
new nested region-store fixtures, then stops at the existing
`complete_empty_body_eligible` expectation; that failure needs a source-current
collector run before it can be classified as implementation or stale-product
behavior. No full self-compilation or sub-10-second incremental-build result is
claimed.


## 2026-10-22 continuation checks

Region-only generic specialization and named integer constants in match arms are
valid Stage1 forms. The Stage1 regression passed all five checking cases and
emitted LLVM for the three positive fixtures using the available product; that
product is stale by source provenance, so this is a compatibility check rather
than a fresh-product gate. Current-source Stage0 integration passed all seven
native region/constant cases in 17.1s. Ordinary non-generic region arguments and
same-named local shadows remain rejected.

`ifc_candidate_is_complete_empty_body` now skips leading newline tokens before
matching its closed `return <literal>` shape. The focused
`incremental_empty_body` atom uses the production lexer and token-span helper,
checks the literal and newline-prefixed forms, and confirms a call body is not
classified as empty; it compiles and runs in 1.32s. The earlier
`complete_empty_body_eligible` failure remains unresolved until the session
control can run against a product built from current source.

The checked-in Stage1 executable remains stale. A fresh self-compilation and the
sub-10-second incremental-build target are still open.

The full checker timing had `check_firm_arg_type_mismatch` at 3.54s on the
expanded compiler. Its extern index was built but the per-call parameter,
compatibility, and protocol lookups still walked all extern declarations. Those
lookups now follow the existing hash bucket chain, with a linear fallback only
when the index shape is stale. The semantic, incremental-empty-body, and
same-name-overload atoms pass together in 3.7s. This focused result does not
replace a full self-check timing.

Fresh Stage1 seed attempts from the native Stage0 product remain over the 30s
cap: `-O3` reached the 6 GiB guard, `-O0` also reached that guard, and raising the
single-build limit to 9 GiB avoided the guard but still timed out at 30s. No
timed-out seed was retried unchanged. The next full-build attempt needs a source
or pipeline optimization before it can be claimed as current.

Bracketed type-region suffixes now retain their expression offsets instead of
discarding the qualifier. The loop element checker uses that metadata to exempt
`sview` elements qualified by a global region, matching Stage0's program-lived
element rule. A local or generic region with the same name cancels the exemption
within its scope. The strict `type_region_suffix` atom exercises the production
suffix recorder used by the first and subsequent bracket arguments;
`loop_program_view` checks acceptance, ordinary-view rejection, and region-name
shadowing. These focused checks do not establish a fresh Stage1 self-compile.

The holder-view provenance helpers now follow AST children without treating eight
levels of nesting as evidence of owned storage or a caller-reference alias. Name
provenance already terminates in the flow table; these traversals do not expand
alias expressions. The strict `holder_view_depth` atom checks deep scalar and
borrowed-view expressions, reference aliases, and wrapped method identity. The
`holder_scalar_deep.elisa` fixture reproduces the old Stage1 false rejection of
twelve scalar identity calls stored into a numeric holder field; Stage0 accepts
the fixture. The source-side proof audit passes. Full proof replay remains
unverified until a fresh strict Stage1 product is available.

The strict `holder_view_wrappers` atom checks that evaluated block results retain
their possible borrowed-view provenance through unary and binary expressions,
field projections, indexing, and slicing. Each wrapper has a scalar control.
The production walker retains child facts rather than replacing them with a
syntax-only lookup that cannot classify the block's result.

The bootstrap's AST-walk visited-set pool now releases oversized tables after
32 consecutive sparse uses, and discards exceptional walks above 16,384 nodes.
Shrinking immediately was rejected because an alternating large/small benchmark
regrew the map on every large walk. With the delayed policy, the focused sparse
reset benchmark measured about 15 ns versus 168 ns for clearing a retained large
map; alternating walks stayed near 79 microseconds with no recurring allocations.
These local measurements do not establish a full-build speedup. The capped full
compiler semantic check still timed out; its allocation profile identifies
repeated call-filled element-state merges as a larger remaining source.

Call-filled element states now gather argument provenance and merge flat states
with direct provenance once. Nested/field-only states retain the sequential
fold, including its sticky unknown verdict and order-sensitive normalization.
A deterministic 500-case comparison checks the result against the prior
sequential fold, including nested fields and parameter dependencies. The
flat eight-state merge benchmark reduced allocations from 2,800 bytes / 14 allocations
to 400 bytes / 2 allocations (about 3.7 to 1.1 microseconds in that focused run).
The source-gathering and full-build costs are outside that microbenchmark.

The focused merge tests used a Go test build with inlining disabled to keep test
compilation within the cap. A normally optimized bootstrap was then built in
capped dependency stages from frozen Go inputs, and the current scope,
holder-view wrapper, and program-view atoms passed against it. Fresh `-O0`
Stage1 seed attempts with both four and two semantic workers still timed out
during analysis at 30 seconds. The worker default remains unchanged; profiles
still show runtime page reuse and zeroing as the dominant costs. A fresh Stage1
product and self-compilation remain unverified.

Generic struct parameter-provenance layouts no longer reserve map slots for
fixed numeric and boolean fields once type shapes are frozen. Unresolved and
generic fields remain in the capacity hint, and substitution/traversal order is
unchanged. On a 130-field generic fixture with one retained view, the focused
benchmark fell from 27,527 bytes / 7 allocations to about 1,100 bytes / 5
allocations. Tests cover scalar, view, and reference generic arguments with both
frozen and unfrozen type shapes. This allocation result is not a fresh Stage1
seed or an end-to-end build timing.
