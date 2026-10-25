"""Source-bind selective-import conflict checking to static branch selection."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_import_conflict.elisa"
FIXTURE = ROOT / "test/repro/import_conflict_mutually_exclusive_static_branches.elisa"
SAME_LINE_FIXTURE = ROOT / "test/repro/import_conflict_same_logical_line.elisa"
UNKNOWN_SIBLINGS_FIXTURE = ROOT / "test/repro/import_conflict_unknown_static_siblings.elisa"
UNKNOWN_UNCONDITIONAL_FIXTURE = ROOT / "test/repro/import_conflict_unknown_static_unconditional.elisa"
UNKNOWN_SEPARATE_CHAINS_FIXTURE = ROOT / "test/repro/import_conflict_unknown_static_separate_chains.elisa"
SMOKE = ROOT / "test/parity/import_conflict_mutually_exclusive_static_branches_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
if "from_import_source_of_position" not in source:
    raise SystemExit("selective-import source modules must be paired by exact annotation position")
source_helper = function_source(source, "from_import_source_of_position")
if not all(fragment in source_helper for fragment in (
        'annotation.owner == "__from_src"',
        "annotation.module == module",
        "annotation.line == line",
        "annotation.offset == offset")):
    raise SystemExit("selective-import source lookup must match module, logical line, and byte offset")
unknown_siblings = function_source(source, "ic_unknown_import_rows_are_siblings")
if not all(fragment in unknown_siblings for fragment in (
        "pma_import_row_branch_uncertain(annotations, \"__from_member\"",
        'left_marker.name != "__from_member_static_branch"',
        'right_marker.name != "__from_member_static_branch"',
        "continue if left_marker.identity_id == right_marker.identity_id",
        "ic_static_if_chain_head(file, left_marker.identity_id)",
        "ic_static_if_chain_head(file, right_marker.identity_id)",
        "left_chain == right_chain")):
    raise SystemExit("unresolved import conflicts must be suppressed only for distinct branches of one chain")
checker = function_source(source, "check_import_conflict")
if "pma_active_import_annotations(file, table)" not in checker:
    raise SystemExit("selective-import conflicts must use branch-filtered import annotations")
if "from_import_source_of_position(annotations, current.module, current.line, current.offset)" not in checker:
    raise SystemExit("each selective-import row must use its exact source-module annotation")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
if not all(fragment in fixture for fragment in (
        "const USE_FIRST_PROVIDER: bool = true",
        "static if USE_FIRST_PROVIDER:",
        "from FirstProvider import choose",
        "static else:",
        "from SecondProvider import choose")):
    raise SystemExit("static-import conflict fixture must place same-name imports in opposite selected arms")
if not all(fragment in smoke for fragment in (
        "import_conflict_mutually_exclusive_static_branches.elisa",
        "import_conflict_same_logical_line.elisa",
        "import_conflict_unknown_static_siblings.elisa",
        "import_conflict_unknown_static_unconditional.elisa",
        "import_conflict_unknown_static_separate_chains.elisa",
        "ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown",
        'conflicting import: "choose"')):
    raise SystemExit("static-import conflict smoke must cover known/unknown branches, source positions, and competing imports")

same_line_fixture = SAME_LINE_FIXTURE.read_text()
if same_line_fixture.count("#line 400 imports.elisa") != 2 or not all(fragment in same_line_fixture for fragment in (
        "#line 400 imports.elisa",
        "from FirstProvider import choose",
        "from SecondProvider import choose")):
    raise SystemExit("same-logical-line fixture must import the same name from two distinct providers")

unknown_siblings_fixture = UNKNOWN_SIBLINGS_FIXTURE.read_text()
if not all(fragment in unknown_siblings_fixture for fragment in (
        "static if ELISA_TARGET_OS_WASI:",
        "from FirstProvider import choose",
        "static else:",
        "from SecondProvider import choose")):
    raise SystemExit("unknown-branch fixture must place the same import in opposite target-dependent arms")
unknown_unconditional_fixture = UNKNOWN_UNCONDITIONAL_FIXTURE.read_text()
if not all(fragment in unknown_unconditional_fixture for fragment in (
        "static if ELISA_TARGET_OS_WASI:",
        "from FirstProvider import choose",
        "from UnconditionalProvider import choose")):
    raise SystemExit("unknown-branch control must retain a conflict with an unconditional import")
unknown_separate_chains_fixture = UNKNOWN_SEPARATE_CHAINS_FIXTURE.read_text()
if unknown_separate_chains_fixture.count("static if ELISA_TARGET_OS_WASI:") != 2 or not all(fragment in unknown_separate_chains_fixture for fragment in (
        "from FirstProvider import competing",
        "from ThirdProvider import competing")):
    raise SystemExit("separate-chain control must retain conflicts between independent target-dependent chains")

print('{"source_bound": true, "branch_filtered_import_conflicts": true}')
