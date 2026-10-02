#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "affine-owner smoke FAIL: $1" >&2; exit 1; }

# A DECLARED `affine`/`linear` struct is a borrowable owner (stage0's
# isBorrowableAffineOwnerType): `&handle` lends it without consuming it, and the
# borrowed-owner analysis rejects the borrow once the owner moves. Measured against stage0.
address=$(printf 'affine struct Handle:\n    raw: mutable uintptr\ndef bad(handle: Handle) -> void:\n    borrow: Handle& = &handle\n    _ = borrow\n' | "$RPT")
grep -Fq 'cannot take address' <<< "$address" && fail "borrow of an affine owner rejected: $address"
grep -Fq 'references to values containing linear handles' <<< "$address" && fail "affine owner reference rejected: $address"

# The SAME borrow after the owner moves dangles, and stage0 names what consumed it.
moved=$(printf 'affine struct Handle:\n    raw: mutable uintptr\ndef sink(h: Handle) -> void:\n    pass\ndef bad(handle: Handle) -> void:\n    borrow: Handle& = &handle\n    sink(move handle)\n    _ = borrow\n' | "$RPT")
grep -Fq 'linear value "borrow" cannot be used: usage facts were consumed by argument to call "sink"' <<< "$moved" || fail "borrow used after its owner moved accepted: $moved"

# A `linear` struct is borrowable for the same reason; a `darray` of them is NOT.
linear_ref=$(printf 'linear struct Guard:\n    raw: mutable uintptr\ndef ok(guard: Guard&) -> void:\n    pass\ndef bad(guards: darray[Guard]&) -> void:\n    pass\n' | "$RPT")
grep -Fq 'got Guard&' <<< "$linear_ref" && fail "linear owner reference rejected: $linear_ref"
grep -Fq 'references to values containing linear handles are not supported; got darray[Guard]&' <<< "$linear_ref" || fail "reference to a darray of linear values accepted: $linear_ref"

global=$(printf 'affine struct Handle:\n    raw: mutable uintptr\nglobal current: Handle = zeroed\n' | "$RPT")
grep -Fq 'global "current" cannot store linear handle values of type Handle' <<< "$global" || fail "affine global accepted: $global"

plain=$(printf 'struct Value:\n    raw: mutable uintptr\ndef ok(value: Value) -> void:\n    borrow: Value& = &value\n    _ = borrow\n' | "$RPT")
grep -Fq 'linear value' <<< "$plain" && fail "ordinary struct address rejected: $plain"

generic_affine=$(printf 'affine struct GenericOwner[T]:\n    value: T\ndef bad(owner: GenericOwner[i64]) -> void:\n    duplicate: GenericOwner[i64] = owner\n' | "$RPT")
grep -Fq 'linear value "owner" must be moved explicitly before move into local "duplicate"' <<< "$generic_affine" || fail "generic affine owner copy accepted: $generic_affine"

# A `using` import must preserve the module-owned affine marker. Otherwise an imported pool
# owner can be copied even though the same declaration is enforced at top level.
imported_affine=$(printf 'module AffineModule:\n    public:\n        affine struct GenericOwner[T]:\n            value: T\nusing AffineModule\ndef bad(owner: GenericOwner[i64]) -> void:\n    duplicate: GenericOwner[i64] = owner\n' | "$RPT")
grep -Fq 'linear value "owner" must be moved explicitly before move into local "duplicate"' <<< "$imported_affine" || fail "imported generic affine owner copy accepted: $imported_affine"

# Module-local affinity must not contaminate an unrelated same-named top-level type.
hidden_type_shadow=$(printf 'module AffineHidden:\n    public:\n        affine struct Handle:\n            value: i64\nstruct Handle:\n    value: i64\ndef ok(handle: Handle) -> void:\n    duplicate: Handle = handle\ndef main() -> i64:\n    return 0\n' | "$RPT")
grep -Fq 'must be moved explicitly' <<< "$hidden_type_shadow" && fail "hidden module affinity contaminated a same-named top-level type: $hidden_type_shadow"

# Inside its declaring module, an affine owner remains borrowable. The registry lookup must use
# the module context while this post-resolution pass visits its declarations.
module_owner_borrow=$(printf 'module AffineBorrow:\n    public:\n        affine struct Handle:\n            value: i64\n        def ok(handle: Handle&) -> void:\n            pass\ndef main() -> i64:\n    return 0\n' | "$RPT")
grep -Fq 'references to values containing linear handles are not supported; got Handle&' <<< "$module_owner_borrow" && fail "module-local affine owner reference rejected: $module_owner_borrow"
grep -Fq 'cannot take address' <<< "$module_owner_borrow" && fail "module-local affine owner borrow rejected: $module_owner_borrow"

# Multi-argument generic owners (including region parameters) retain their affine head.
region_generic_affine=$(printf 'module AffineRegionModule:\n    public:\n        affine struct GenericOwner[T, @r]:\n            value: T\nusing AffineRegionModule\ndef bad[@r](owner: GenericOwner[i64, r]) -> void:\n    duplicate: GenericOwner[i64, r] = owner\n' | "$RPT")
grep -Fq 'linear value "owner" must be moved explicitly before move into local "duplicate"' <<< "$region_generic_affine" || fail "region-generic affine owner copy accepted: $region_generic_affine"

# A module-qualified affine type (`M::Token`) is enforced like a bare one, whatever its field
# types. The qualified spelling used to type the local as Unknown, so a scalar-only token could
# be copied and released twice (elisa-engine W03, `WorldAccess::Token`).
qual_mod='module Access:\n    public:\n        affine struct Token:\n            private:\n                owner: i64\n                serial: usize\n        def acquire() -> Token:\n            Token{owner: 1, serial: 2}\n        def release(token: Token) -> i64:\n            token.owner\n'
qualified_copy=$(printf "${qual_mod}"'def main() -> i32:\n    first: mutable Access::Token = Access::acquire()\n    duplicate: mutable Access::Token = first\n    _ = Access::release(move duplicate)\n    _ = Access::release(move first)\n    0\n' | "$RPT")
grep -Fq 'linear value "first" must be moved explicitly before move into local "duplicate"' <<< "$qualified_copy" || fail "qualified scalar-only affine copy accepted: $qualified_copy"
qualified_reuse=$(printf "${qual_mod}"'def main() -> i32:\n    token: Access::Token = Access::acquire()\n    _ = Access::release(move token)\n    _ = Access::release(move token)\n    0\n' | "$RPT")
grep -Fq 'linear handle value "token" cannot be used after ownership was consumed' <<< "$qualified_reuse" || fail "qualified affine use after move accepted: $qualified_reuse"
qualified_param=$(printf "${qual_mod}"'def bad(token: Access::Token) -> void:\n    duplicate: Access::Token = token\n    _ = Access::release(move duplicate)\n' | "$RPT")
grep -Fq 'linear value "token" must be moved explicitly before move into local "duplicate"' <<< "$qualified_param" || fail "qualified affine parameter copy accepted: $qualified_param"
qualified_generic=$(printf 'module AffineGenericModule:\n    public:\n        affine struct GenericOwner[T]:\n            value: T\ndef bad(owner: AffineGenericModule::GenericOwner[i64]) -> void:\n    duplicate: AffineGenericModule::GenericOwner[i64] = owner\n' | "$RPT")
grep -Fq 'linear value "owner" must be moved explicitly before move into local "duplicate"' <<< "$qualified_generic" || fail "qualified generic affine owner copy accepted: $qualified_generic"
qualified_move_ok=$(printf "${qual_mod}"'def main() -> i32:\n    token: Access::Token = Access::acquire()\n    _ = Access::release(move token)\n    0\n' | "$RPT")
grep -Fq 'linear' <<< "$qualified_move_ok" && fail "correct qualified affine move rejected: $qualified_move_ok"

# A same-named plain type in a module that is NOT visible here must not hide the qualified
# owner's marker, and inside that module its own plain type stays copyable.
qualified_hidden_plain=$(printf "${qual_mod}"'module Parser:\n    public:\n        struct Token:\n            value: i64\n        def ok(token: Token) -> void:\n            duplicate: Token = token\ndef main() -> i32:\n    first: Access::Token = Access::acquire()\n    duplicate: Access::Token = first\n    _ = Access::release(move duplicate)\n    _ = Access::release(move first)\n    0\n' | "$RPT")
grep -Fq 'linear value "first" must be moved explicitly before move into local "duplicate"' <<< "$qualified_hidden_plain" || fail "hidden plain namesake disabled qualified affinity: $qualified_hidden_plain"
grep -Fq 'linear value "token"' <<< "$qualified_hidden_plain" && fail "qualified affinity contaminated a module-local plain namesake: $qualified_hidden_plain"

# `M::T` takes M's own marker only. A plain qualified `Hier::Snapshot` beside an unrelated
# affine `Render::Snapshot` stays copyable (elisa-engine: WorldHierarchy vs RenderSnapshot).
qualified_foreign_namesake=$(printf 'module Render:\n    public:\n        affine struct Snapshot:\n            private:\n                id: i64\nmodule Hier:\n    public:\n        struct Snapshot:\n            count: usize\n        def take() -> Snapshot:\n            Snapshot{count: 0}\n        def restore(snapshot: Snapshot) -> bool:\n            snapshot.count == 0\ndef main() -> i32:\n    snapshot: Hier::Snapshot = Hier::take()\n    copy: Hier::Snapshot = snapshot\n    _ = Hier::restore(snapshot)\n    _ = Hier::restore(copy)\n    0\n' | "$RPT")
grep -Fq 'linear' <<< "$qualified_foreign_namesake" && fail "plain qualified type borrowed another module's affine marker: $qualified_foreign_namesake"
qualified_return=$(printf "${qual_mod}"'def make() -> Access::Token:\n    token: mutable Access::Token = Access::acquire()\n    token\n' | "$RPT")
grep -Fq 'linear value "token" must be moved explicitly before return' <<< "$qualified_return" || fail "qualified affine implicit return accepted: $qualified_return"

generic_plain=$(printf 'struct PlainBox[T]:\n    value: T\ndef ok(box: PlainBox[i64]) -> void:\n    duplicate: PlainBox[i64] = box\n' | "$RPT")
grep -Fq 'must be moved explicitly' <<< "$generic_plain" && fail "ordinary generic value was classified affine: $generic_plain"

containing=$(printf 'struct Holder:\n    thread: mutable Thread[i64, Joinable]\ndef bad_param(holder: Holder&) -> void:\n    pass\ndef bad_local(holder: Holder) -> void:\n    alias: Holder& = &holder\n    _ = alias\n' | "$RPT")
grep -Fq 'references to values containing linear handles are not supported; got Holder&' <<< "$containing" || fail "reference to affine-containing struct accepted: $containing"
grep -Fq 'cannot take address of value containing linear handles' <<< "$containing" || fail "address of affine-containing struct accepted: $containing"

aggregate_global=$(printf 'struct Holder:\n    thread: mutable Thread[i64, Joinable]\nglobal current_thread: Thread[i64, Joinable] = zeroed\nglobal current_holder: Holder = zeroed\n' | "$RPT")
grep -Fq 'global "current_thread" cannot store linear handle values of type Thread' <<< "$aggregate_global" || fail "direct affine global accepted: $aggregate_global"
grep -Fq 'global "current_holder" cannot store linear handle values of type Holder' <<< "$aggregate_global" || fail "affine-containing global accepted: $aggregate_global"

echo "affine-owner smoke OK: declared owners borrowable, containers refused, globals rejected"
