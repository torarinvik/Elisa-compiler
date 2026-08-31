#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-component-runtime.XXXXXX")"

[[ -x "$STAGE1" ]] || { echo "wasm_component_runtime_smoke SKIP: no stage1 seed at $STAGE1"; exit 0; }
build_fixture() {
    local wit="$1"
    local source="$2"
    local name="$3"
    [[ -f "$wit" && -f "$source" ]] || { echo "wasm_component_runtime_smoke SKIP: fixture missing"; exit 0; }

    ELISA_COMPILER_ROOT="$ROOT" \
    ELISA_STAGE1_BIN="$STAGE1" \
      "$ROOT/scripts/elisac_stage1.sh" \
      -emit wasm \
      --wasm-only \
      --component-type "$wit" \
      -o "$WORK/$name.wasm" \
      "$source" \
      >"$WORK/$name.log" 2>&1

    [[ -s "$WORK/$name.wasm" ]] || { echo "$name component output is empty" >&2; exit 1; }
    [[ -f "$WORK/$name.json" ]] || { echo "$name component manifest is missing" >&2; exit 1; }
    grep -Fq '"allocator": "component-cabi-realloc"' "$WORK/$name.json"
}

build_fixture \
    "$ROOT/test/fixtures/wasm/component_cabi_realloc.wit" \
    "$ROOT/test/fixtures/wasm/component_cabi_realloc.elisa" \
    component
build_fixture \
    "$ROOT/test/fixtures/wasm/component_host_surface.wit" \
    "$ROOT/test/fixtures/wasm/component_host_surface.elisa" \
    host-surface

# Keep stage0's component ABI path covered as well.  This is optional so the
# normal stage1 smoke remains runnable from a checkout that has not built a
# dedicated stage0 compiler, while CI and local compiler worktrees can set
# ELISACORE_BIN to exercise both compiler generations.
STAGE0="${ELISACORE_BIN:-}"
if [[ -n "$STAGE0" && -x "$STAGE0" ]]; then
    build_stage0_fixture() {
        local wit="$1"
        local source="$2"
        local name="$3"

        ELISA_WASM_NO_CACHE=1 \
          python3 "$ROOT/scripts/wasm_build.py" \
          --root "$ROOT" \
          --compiler "$STAGE0" \
          --source "$source" \
          --output "$WORK/stage0-$name.wasm" \
          --wasm-only \
          --component-type "$wit" \
          >"$WORK/stage0-$name.log" 2>&1

        [[ -s "$WORK/stage0-$name.wasm" ]] || { echo "stage0 $name component output is empty" >&2; exit 1; }
        [[ -f "$WORK/stage0-$name.json" ]] || { echo "stage0 $name component manifest is missing" >&2; exit 1; }
        grep -Fq '"allocator": "component-cabi-realloc"' "$WORK/stage0-$name.json"
    }

    build_stage0_fixture \
        "$ROOT/test/fixtures/wasm/component_cabi_realloc.wit" \
        "$ROOT/test/fixtures/wasm/component_cabi_realloc.elisa" \
        component
    build_stage0_fixture \
        "$ROOT/test/fixtures/wasm/component_host_surface.wit" \
        "$ROOT/test/fixtures/wasm/component_host_surface.elisa" \
        host-surface
fi

if find "$WORK" -maxdepth 1 -type f \( -name '*.mjs' -o -name '*.d.ts' -o -name '*.d.mts' \) -print -quit | grep -q .; then
    echo "wasm_component_runtime_smoke produced a JavaScript/TypeScript artifact" >&2
    exit 1
fi

echo "wasm component runtime smoke OK: canonical strings, lists, options, results, records, and scalar returns componentize with freestanding cabi_realloc and no JS/TS artifacts"
