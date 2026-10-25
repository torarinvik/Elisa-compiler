"""Source-only binding checks for PyModule enum import and root fallback order."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "src/driver/pymodule/defaults/alias_targets.elisa"


def compact_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(f"def {name}(") ), None)
    if start is None:
        raise SystemExit(f"missing production helper {name}")
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("def ")), len(lines))
    code = []
    for line in lines[start:end]:
        code.append(line.split("#", 1)[0])
    return "".join("".join(line.split()) for line in code)


source = DEFAULTS.read_text(encoding="utf-8")
imports = compact_function(source, "pymodule_default_visible_enum_import")
priority_loop = imports.find("forimport_priorityin0..<2")
wildcard_tier = imports.find('ifimport_priority==0:')
scope_rank = imports.find("forimport_scope_rankin0..<(lexical_owner.len+1.usize())")
wildcard_loop = imports.find("forimport_annotationinfile.enum_annotations", scope_rank)
wildcard_scope_filter = imports.find("continueifnotpymodule_default_alias_scope_matches", wildcard_loop)
wildcard_filter = imports.find('continueifimport_annotation.name!="__binding_wildcard_import"', wildcard_scope_filter)
selective_tier = imports.find("else:", wildcard_filter)
selective_loop = imports.find("forimport_annotationinfile.enum_annotations", selective_tier)
selective_filter = imports.find('continueifimport_annotation.owner!="__from_member"orimport_annotation.name!=enum_name', selective_loop)
scope_filter_after_selective = imports.find("pymodule_default_alias_scope_matches", selective_loop)
selective_target = imports.find("imported_owner:(found:bool", selective_filter)
selective_terminal = imports.find('return(false,false,"")', selective_target)
if not (
    priority_loop >= 0
    and wildcard_tier > priority_loop
    and scope_rank > wildcard_tier
    and wildcard_loop > scope_rank
    and wildcard_scope_filter > wildcard_loop
    and wildcard_filter > wildcard_scope_filter
    and selective_tier > wildcard_filter
    and selective_loop > selective_tier
    and selective_filter > selective_loop
    and scope_filter_after_selective < 0
    and selective_target > selective_filter
    and selective_terminal > selective_target
):
    raise SystemExit("import lookup must scope-rank wildcard rows, search global selective aliases, and keep first-candidate fallback terminal")
if 'return(false,false,"")' not in imports:
    raise SystemExit("a missing imported enum must fall through to the raw root candidate")

import_target = compact_function(source, "pymodule_default_import_target_module_path")
if any(token in import_target for token in (
    "pymodule_default_visible_module_alias",
    "pymodule_default_visible_module_identifier",
    "pymodule_default_resolve_alias_target_path",
)):
    raise SystemExit("bare import source paths must preserve alias spelling like Core candidates")
if not (
    import_target.find("pymodule_default_append_text_bytes(bytes,lexical_owner)")
    < import_target.find("pymodule_default_append_text_bytes(bytes,target)")
    < import_target.find("returnpymodule_default_module_path_exists(file.top_decls,bytes)")
):
    raise SystemExit("import source candidate must qualify the raw spelling with its declaring module")

enum_value = compact_function(source, "pymodule_default_enum_value")
lexical = enum_value.find("whilecandidate_owner!=")
visible_import = enum_value.find("visible_import:(found:bool")
root_candidate = enum_value.find("top_level_member:(declared:bool")
if not (lexical >= 0 and visible_import > lexical and root_candidate > visible_import):
    raise SystemExit("enum default lookup order must be lexical, imported, then root")
imported_member_success = enum_value.find("return(true,imported_member.value)ifimported_member.foundandnotimported_member.ambiguous")
imported_member_failure = enum_value.find("return(false,0)", imported_member_success + 1)
if not (imported_member_success >= 0 and imported_member_failure > imported_member_success and root_candidate > imported_member_failure):
    raise SystemExit("a selected imported enum with a missing variant must fail closed before root fallback")

fixtures = {
    "selective-over-root": (
        "test/repro/pymodule_selective_import_shadows_root.elisa",
        "High = 41",
        "High = 47",
        "using Values::ImportedMode",
        '"default": "41"',
    ),
    "wildcard-over-selective": (
        "test/repro/pymodule_wildcard_precedes_selective_default.elisa",
        "High = 41",
        "High = 73",
        "using SelectiveValues::Mode\nusing WildcardValues",
        '"default": "73"',
    ),
    "missing-import-falls-through": (
        "test/repro/pymodule_missing_wildcard_enum_root_fallback.elisa",
        "const enum OtherMode of i64",
        "High = 97",
        "using Values",
        '"default": "97"',
    ),
}
for case, (relative, first, second, imports_text, expected) in fixtures.items():
    fixture = (ROOT / relative).read_text(encoding="utf-8")
    if not all(fragment in fixture for fragment in (first, second, imports_text)):
        raise SystemExit(f"{case} fixture lost its distinct source/import/root candidates")
    smoke = (ROOT / "test/parity" / f"pymodule_{'selective_import_shadows_root' if case == 'selective-over-root' else 'wildcard_precedes_selective_default' if case == 'wildcard-over-selective' else 'missing_wildcard_enum_root_fallback'}_smoke.sh").read_text(encoding="utf-8")
    if expected not in smoke:
        raise SystemExit(f"{case} smoke no longer asserts the chosen candidate")

missing_variant = (ROOT / "test/repro/pymodule_imported_enum_missing_variant_root_present.elisa").read_text(encoding="utf-8")
if not all(fragment in missing_variant for fragment in (
    "const enum Mode of i64:\n            Available = 41",
    "const enum Mode of i64:\n    High = 97",
    "using Values::Mode",
    "value: i64 = Mode.High",
)):
    raise SystemExit("missing-variant fixture no longer distinguishes imported and root enums")

alias_sources = (ROOT / "test/repro/pymodule_alias_import_source_spelling.elisa").read_text(encoding="utf-8")
if not all(fragment in alias_sources for fragment in (
    "High = 41",
    "High = 47",
    "using RealSelective as F\nusing F::SelectiveMode",
    "High = 61",
    "High = 67",
    "using RealWildcard as W\nusing W",
)):
    raise SystemExit("selective/wildcard alias-source fixture must distinguish expanded and raw candidates")
alias_smoke = (ROOT / "test/parity/pymodule_alias_import_source_spelling_smoke.sh").read_text(encoding="utf-8")
if '"default": "47"' not in alias_smoke or '"default": "67"' not in alias_smoke:
    raise SystemExit("alias-source smoke must assert the raw-spelling root fallbacks")

nested_wildcards = (ROOT / "test/repro/pymodule_inherited_wildcard_precedes_local.elisa").read_text(encoding="utf-8")
if not (
    nested_wildcards.find("using LocalValues") < nested_wildcards.find("using ParentValues")
    and "High = 73" in nested_wildcards
    and "High = 17" in nested_wildcards
):
    raise SystemExit("nested wildcard fixture must put the nearer using first in source with distinct values")
nested_smoke = (ROOT / "test/parity/pymodule_inherited_wildcard_precedes_local_smoke.sh").read_text(encoding="utf-8")
if '"default": "17"' not in nested_smoke:
    raise SystemExit("nested wildcard smoke must assert the inherited parent candidate")

defaults_source = (ROOT / "src/driver/pymodule/defaults.elisa").read_text(encoding="utf-8")
visible_alias = compact_function(defaults_source, "pymodule_default_visible_module_alias")
if not (
    'annotation.name!="__using_alias"orannotation.owner!=name' in visible_alias
    and "return(index,false)" in visible_alias
    and "pymodule_default_alias_scope_matches" not in visible_alias
):
    raise SystemExit("module alias lookup must be global and retain Core's first declaration")
prior_alias = compact_function(defaults_source, "pymodule_default_visible_prior_module_alias")
if not (
    "annotation.offset>=before_offset" in prior_alias
    and "pymodule_default_alias_scope_matches" not in prior_alias
    and "return(index,false)" in prior_alias
):
    raise SystemExit("alias target canonicalization must use the first earlier global alias")
sibling_alias = (ROOT / "test/repro/pymodule_sibling_module_alias_qualifier.elisa").read_text(encoding="utf-8")
if not all(fragment in sibling_alias for fragment in (
    "module AliasDecl:",
    "High = 41",
    "using Provider as V",
    "module V:",
    "High = 97",
    "module Caller:",
    "V::Mode.High",
)):
    raise SystemExit("sibling module-alias fixture must distinguish the global alias from the raw module")
sibling_smoke = (ROOT / "test/parity/pymodule_sibling_module_alias_qualifier_smoke.sh").read_text(encoding="utf-8")
if '"default": "41"' not in sibling_smoke:
    raise SystemExit("sibling alias smoke must assert the aliased enum candidate")

# A same-named real module must not preempt a nearer `using Other as Mode`
# alias when both modules declare the requested enum leaf.
same_leaf_alias = (ROOT / "test/repro/pymodule_alias_module_same_leaf.elisa").read_text(encoding="utf-8")
if not all(fragment in same_leaf_alias for fragment in (
    "module Mode:",
    "Closed = 1",
    "module Other:",
    "Ready = 57",
    "using Other as Mode",
    "Mode::Kind.Ready",
)):
    raise SystemExit("same-leaf alias fixture must distinguish a real module from its nearer alias")
same_leaf_smoke = (ROOT / "test/parity/pymodule_selective_enum_defaults_smoke.sh").read_text(encoding="utf-8")
if '"default": "57"' not in same_leaf_smoke or "alias_wins(value: int = 57)" not in same_leaf_smoke:
    raise SystemExit("same-leaf alias smoke must assert the alias target's distinct enum value")
qualifier_resolution = compact_function(DEFAULTS.read_text(encoding="utf-8"), "pymodule_default_enum_qualifier_matches_owner")
lexical_enum_check = qualifier_resolution.find("iflexical_enum_path_foundandpymodule_default_module_path_declares_enum")
alias_target_check = qualifier_resolution.find("target_match.resolvedandtarget_match.contains_enum")
if not (
    "alias_preempts_ancestor_module" not in qualifier_resolution
    and lexical_enum_check >= 0
    and alias_target_check > lexical_enum_check
):
    raise SystemExit("qualified enum resolution must check lexical enum paths before module-alias rewrites")
ancestor_alias = (ROOT / "test/repro/pymodule_nearer_alias_shadows_ancestor.elisa").read_text(encoding="utf-8")
if not all(fragment in ancestor_alias for fragment in (
    "module Outer:",
    "module Mode:",
    "High = 11",
    "module Inner:",
    "High = 73",
    "using Actual as Mode",
    "Mode::Kind.High",
)):
    raise SystemExit("ancestor-alias fixture must distinguish lexical and rewritten module candidates")
ancestor_alias_smoke = (ROOT / "test/parity/pymodule_nearer_alias_shadows_ancestor_smoke.sh").read_text(encoding="utf-8")
if '"default": "11"' not in ancestor_alias_smoke or "nearer_alias_wins(value: int = 11)" not in ancestor_alias_smoke:
    raise SystemExit("ancestor lexical module must be the asserted candidate ahead of its nearer alias")

sibling_import = (ROOT / "test/repro/pymodule_sibling_selective_import_root_precedence.elisa").read_text(encoding="utf-8")
if not all(fragment in sibling_import for fragment in (
    "High = 97",
    "module ImportSite:",
    "High = 41",
    "from Provider import Mode",
    "module Consumer:",
    "Mode.High",
)):
    raise SystemExit("sibling selective-import fixture must distinguish the global alias from root")
sibling_import_smoke = (ROOT / "test/parity/pymodule_sibling_selective_import_root_precedence_smoke.sh").read_text(encoding="utf-8")
if '"default": "41"' not in sibling_import_smoke:
    raise SystemExit("sibling import smoke must assert the program-wide selective candidate")

missing_selective = (ROOT / "test/repro/pymodule_missing_selective_enum_root_fallback.elisa").read_text(encoding="utf-8")
if not all(fragment in missing_selective for fragment in (
    "const enum OtherMode of i64",
    "const enum Mode of i64",
    "High = 97",
    "from Provider import Mode",
    "Mode.High",
)):
    raise SystemExit("missing selective-enum fixture must leave a distinct root enum fallback")
missing_selective_smoke = (ROOT / "test/parity/pymodule_missing_selective_enum_root_fallback_smoke.sh").read_text(encoding="utf-8")
if '"default": "97"' not in missing_selective_smoke:
    raise SystemExit("missing selective-enum smoke must assert root fallback")

print('{"source_bound": true, "contracts": 11, "precedence_cases": 10}')
