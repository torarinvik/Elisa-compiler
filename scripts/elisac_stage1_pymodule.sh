# `-emit pymodule-so` — the host-facing convenience path for the complete Python extension
# pipeline. The compiler owns the language-facing pieces (the export manifest, the CPython C
# shim, the native object); this owns the platform toolchain invocation, so a user needs one
# command rather than five.
#
# Sourced by elisac_stage1.sh; it reads that script's ROOT, BIN, out, src and toolchain
# variables as globals and exits the whole script when it is done.

emit_pymodule_so() {
  [[ -x "$ELISA_CLANG_TOOL" ]] || {
    echo "-emit pymodule-so requires clang compatible with LLVM_CONFIG=$LLVM_CONFIG (set ELISA_CLANG)" >&2
    exit 2
  }
  python_config="$PYTHON_CONFIG_HOST"
  python_bin="$PYTHON_HOST"
  [[ -x "$python_bin" ]] || {
    echo "-emit pymodule-so requires python3 (set PYTHON_BIN)" >&2
    exit 2
  }
  pymodule_runtime_auto=0
  if [[ ! -f "$runtime_obj" && "${ELISA_PYMODULE_AUTO_RUNTIME:-1}" != "0" ]]; then
    runtime_support="$ROOT/elisacore_std/native_runtime_support.elisa"
    [[ -f "$runtime_support" ]] || {
      echo "-emit pymodule-so cannot auto-build the runtime: missing $runtime_support; run scripts/build_runtime_object.sh or set ELISA_RUNTIME_OBJ" >&2
      exit 2
    }
    mkdir -p "$(dirname -- "$runtime_obj")"
    echo "pymodule-so: building runtime object at $runtime_obj" >&2
    "$0" -emit obj -O0 -o "$runtime_obj" "$runtime_support"
    pymodule_runtime_auto=1
  fi
  [[ -f "$runtime_obj" ]] || {
    echo "-emit pymodule-so requires the runtime object at $runtime_obj (run scripts/build_runtime_object.sh or set ELISA_PYMODULE_AUTO_RUNTIME=0)" >&2
    exit 2
  }

  pymodule_work="$(mktemp -d)"
  trap 'rm -rf "$pymodule_work"' EXIT
  pymodule_manifest="$pymodule_work/manifest.json"
  pymodule_c="$pymodule_work/module.c"
  pymodule_obj="$pymodule_work/module.o"

  # Emit the manifest first so the no-output-path form can derive its canonical
  # module name before choosing an ABI-tagged filename.
  "$0" -emit pymodule -o "$pymodule_manifest" "$src"
  pymodule_module="$("$python_bin" - "$pymodule_manifest" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)
module = manifest.get("module")
if not isinstance(module, str) or not module:
    raise SystemExit("pymodule manifest has no module name")
print(module)
PY
)"
  if [[ -z "$out" ]]; then
    out="$pymodule_module"
  fi

  # Python's import machinery recognizes ABI-tagged extension suffixes (and the plain .so
  # fallback), not an arbitrary suffixless filename. Keep the convenient no-output-path and
  # -o demo spellings importable by appending the selected interpreter's canonical suffix;
  # explicit .so or ABI-tagged output names remain untouched.
  pymodule_ext_suffix="$("$python_bin" - <<'PY'
import sysconfig

suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
print(suffix)
PY
)"
  [[ -n "$pymodule_ext_suffix" ]] || {
    echo "-emit pymodule-so could not determine Python's extension suffix" >&2
    exit 2
  }
  pymodule_output_has_suffix=0
  pymodule_extension_suffixes="$("$python_bin" - <<'PY'
import _imp

for suffix in _imp.extension_suffixes():
    print(suffix)
PY
)"
  while IFS= read -r pymodule_known_suffix; do
    if [[ -n "$pymodule_known_suffix" && "$out" == *"$pymodule_known_suffix" ]]; then
      pymodule_output_has_suffix=1
      break
    fi
  done <<< "$pymodule_extension_suffixes"
  if [[ "$pymodule_output_has_suffix" == 0 ]]; then
    out="${out}${pymodule_ext_suffix}"
  fi

  # Validate the import-facing basename before compiling the generated shim/object. This turns
  # a common typo (`-o wrong-name.so`) into an immediate diagnostic instead of doing all the
  # expensive native work first. The suffix matcher also accepts ABI-tagged names from a
  # different Python installation, which is useful when the build and import interpreters
  # intentionally differ.
  pymodule_output_base="$(basename -- "$out")"
  pymodule_output_stem="$pymodule_output_base"
  while IFS= read -r pymodule_known_suffix; do
    if [[ -n "$pymodule_known_suffix" && "$pymodule_output_base" == *"$pymodule_known_suffix" ]]; then
      # Remove the exact suffix. Python ABI tags contain punctuation, but no Bash glob
      # metacharacters, so the variable expansion is an exact match.
      pymodule_output_stem="${pymodule_output_base%$pymodule_known_suffix}"
      break
    fi
  done <<< "$pymodule_extension_suffixes"
  if [[ "$pymodule_output_stem" != "$pymodule_module" && "$pymodule_output_base" == "$pymodule_module"* ]]; then
    pymodule_output_suffix="${pymodule_output_base#"$pymodule_module"}"
    case "$pymodule_output_suffix" in
      .abi3.so|.cpython-[0-9]*.so|.pypy*.so)
        pymodule_output_stem="$pymodule_module"
        ;;
    esac
  fi
  if [[ "$pymodule_output_stem" != "$pymodule_module" ]]; then
    echo "pymodule-so: output filename '$pymodule_output_base' must be named '$pymodule_module' plus a Python extension suffix to import as $pymodule_module" >&2
    exit 2
  fi
  mkdir -p "$(dirname -- "$out")"

  # Re-enter this wrapper for the generated C shim and native object. Keeping these calls
  # through the public CLI preserves include flattening, stdlib detection, diagnostics,
  # optimisation flags, and target-triple behaviour in one place.
  "$0" -emit pymodule-c -o "$pymodule_c" "$src"
  pymodule_compile_args=()
  case "$opt_level" in
    1) pymodule_compile_args+=("-O1") ;;
    2) pymodule_compile_args+=("-O2") ;;
    3) pymodule_compile_args+=("-O3") ;;
  esac
  [[ -n "$target_triple" ]] && pymodule_compile_args+=("-target-triple" "$target_triple")
  [[ "$noalias" == 1 ]] && pymodule_compile_args+=("-fnoalias")
  [[ "$bounds_check" == 1 ]] && pymodule_compile_args+=("-fbounds-check")
  if [[ ${#pymodule_compile_args[@]} -gt 0 ]]; then
    "$0" -emit obj -o "$pymodule_obj" "${pymodule_compile_args[@]}" "$src"
  else
    "$0" -emit obj -o "$pymodule_obj" "$src"
  fi

  if [[ -n "$python_config" ]]; then
    [[ -x "$python_config" ]] || {
      echo "-emit pymodule-so requires a usable python3-config (set PYTHON_CONFIG)" >&2
      exit 2
    }
    read -r -a pymodule_include_flags <<< "$("$python_config" --includes)"
  else
    pymodule_include_dir="$("$python_bin" -c 'import sysconfig; print(sysconfig.get_config_var("INCLUDEPY") or sysconfig.get_path("include") or "")' 2>/dev/null || true)"
    [[ -n "$pymodule_include_dir" && -d "$pymodule_include_dir" ]] || {
      echo "-emit pymodule-so could not determine Python headers for $python_bin (set PYTHON_CONFIG)" >&2
      exit 2
    }
    pymodule_include_flags=("-I$pymodule_include_dir")
  fi
  # The object backend can deliberately decline an unsupported target body. On Darwin the
  # bundle linker permits unresolved symbols for Python's C API, which would otherwise let a
  # missing Elisa wrapper survive until `import module` with an opaque dynamic-loader error.
  # Audit every manifest row before linking so the user gets the exact exported symbol that
  # needs a supported native ABI.
  pymodule_nm_tool="${ELISA_LLVM_NM:-$LLVM_BIN_DIR/llvm-nm}"
  if [[ -x "$pymodule_nm_tool" ]]; then
    "$pymodule_nm_tool" -g "$pymodule_obj" >"$pymodule_work/symbols.txt"
    if ! "$python_bin" - "$pymodule_manifest" "$pymodule_work/symbols.txt" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    manifest = json.load(f)
with open(sys.argv[2], encoding="utf-8") as f:
    symbols = {line.split()[-1].lstrip("_") for line in f if line.split()}
module = manifest["module"]
missing = [
    f"elisa_pymodule_{module}_{entry['name']}"
    for entry in manifest.get("functions", [])
    if f"elisa_pymodule_{module}_{entry['name']}" not in symbols
]
missing += [
    f"elisa_pymodule_{module}_{entry['name']}"
    for entry in manifest.get("constants", [])
    if f"elisa_pymodule_{module}_{entry['name']}" not in symbols
]
if missing:
    for symbol in missing:
        print(f"error: native pymodule symbol missing from object: {symbol}", file=sys.stderr)
    raise SystemExit(1)
PY
    then
      exit 1
    fi
  fi
  # A pymodule object is linked together with the complete Elisa runtime. User functions are
  # reached through their generated `elisa_pymodule_*` wrappers, so any same-named definition
  # already present in the runtime must remain local to the module object. A common function
  # such as `fail` otherwise produces a duplicate-symbol linker error before Python can import
  # the extension. Localizing only the exact intersection preserves every public wrapper.
  pymodule_objcopy_tool="${ELISA_LLVM_OBJCOPY:-$LLVM_BIN_DIR/llvm-objcopy}"
  if [[ -x "$pymodule_nm_tool" && -x "$pymodule_objcopy_tool" ]]; then
    "$pymodule_nm_tool" --defined-only -g --format=posix "$pymodule_obj" | awk '{print $1}' | sort -u >"$pymodule_work/module-defined.txt"
    "$pymodule_nm_tool" --defined-only -g --format=posix "$runtime_obj" | awk '{print $1}' | sort -u >"$pymodule_work/runtime-defined.txt"
    comm -12 "$pymodule_work/module-defined.txt" "$pymodule_work/runtime-defined.txt" >"$pymodule_work/localize-symbols.txt"
    if [[ -s "$pymodule_work/localize-symbols.txt" ]]; then
      "$pymodule_objcopy_tool" --localize-symbols="$pymodule_work/localize-symbols.txt" "$pymodule_obj"
    fi
  fi
  pymodule_link_inputs=("$pymodule_c" "$pymodule_obj" "$runtime_obj")
  # The runtime intentionally leaves the host callback hooks unresolved. This is true for
  # both an object auto-built above and the repository's normal prebuilt runtime object.
  # Supply the extension-safe fallbacks whenever those imports are present; restricting this
  # to the auto-build path produced a .so that linked successfully on Darwin but failed at
  # import time with `_elisa_native_callback_call_i32_voidp` missing.
  pymodule_needs_callback_fallback="$pymodule_runtime_auto"
  pymodule_host_nm="${ELISA_LLVM_NM:-$LLVM_BIN_DIR/llvm-nm}"
  if [[ "$pymodule_needs_callback_fallback" != 1 && -x "$pymodule_host_nm" ]]; then
    pymodule_unresolved_symbols="$("$pymodule_host_nm" -u "$runtime_obj" 2>/dev/null || true)"
    if [[ "$pymodule_unresolved_symbols" == *elisa_native_callback_* ]]; then
      pymodule_needs_callback_fallback=1
    fi
  fi
  if [[ "$pymodule_needs_callback_fallback" == 1 ]]; then
    # The complete runtime also carries optional native-callback and varargs hooks whose
    # host implementations are supplied by an executable, not by a Python extension. Provide
    # the documented fallback behavior (return the caller's fallback value/no-op) so importing a
    # simple module does not fail on unrelated runtime entry points.
    pymodule_callback_fallback_obj="$pymodule_work/native_callback_fallback.o"
    "$ELISA_CLANG_TOOL" -c -fPIC -fno-builtin -O2 -o "$pymodule_callback_fallback_obj" "$ROOT/scripts/pymodule_runtime_fallback.c"
    pymodule_link_inputs+=("$pymodule_callback_fallback_obj")
  fi
  pymodule_link_command=()
  if [[ "$(uname -s)" == "Darwin" ]]; then
    pymodule_link_command=("$ELISA_CLANG_TOOL" -bundle -undefined dynamic_lookup -Wl,-dead_strip)
  elif [[ "$(uname -s)" == "Linux" ]]; then
    pymodule_link_command=("$ELISA_CLANG_TOOL" -shared -fPIC -Wl,--gc-sections)
  else
    echo "-emit pymodule-so is unsupported on $(uname -s)" >&2
    exit 2
  fi
  pymodule_link_command+=("${pymodule_include_flags[@]}" -o "$out" "${pymodule_link_inputs[@]}")
  "${pymodule_link_command[@]}"
  # A native extension is most useful when IDEs can discover its typed surface immediately.
  # Keep the sidecar beside the extension and name it after the manifest module, rather than
  # after the ABI-tagged filename (`demo.cpython-314-darwin.so` -> `demo.pyi`).
  pymodule_stub="$(dirname -- "$out")/$pymodule_module.pyi"
  "$python_bin" "$ROOT/scripts/pymodule_pyi.py" "$pymodule_manifest" "$pymodule_stub"
  echo "pymodule-so: wrote $out and $pymodule_stub (import as $pymodule_module)" >&2
  exit 0
}
