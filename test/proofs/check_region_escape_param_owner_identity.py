"""Keep `in region_param:` classification inside the owning function's source interval."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WALK = (ROOT / "src/semantic/check_region_escape/walk_recovery.elisa").read_text()
PARSER = (ROOT / "src/parser/parser_types_function.elisa").read_text()
FIXTURE = (ROOT / "test/repro/region_escape_param_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/region_scope_smoke.sh").read_text()


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


walk = compact(WALK)
parser = compact(PARSER)
if "region_escape_has_active_region_param(annotations,clause[0],line.offset)" not in walk:
    raise SystemExit("in-region block classification must query the exact block source offset")
if "annotation.owner_offset<=block_offset" not in walk or \
        "annotation.end_offset!=0" not in walk or \
        "block_offset<annotation.end_offset" not in walk:
    raise SystemExit("region-parameter rows must be active within their own source interval")
if "region_scope_end_offset:u32=parser.lexical_block_end_offset(token.start)" not in parser or \
        "end_offset:region_scope_end_offset" not in parser:
    raise SystemExit("function-owned region parameters must close at the function source boundary")
if FIXTURE.count("#line 0 region-escape-param-owner.elisa") != 2 or \
        "def region_owner[@a](xs: mutable darray[u32] @a) -> void:" not in FIXTURE or \
        "def arena_owner(a: mutable Arena&, xs: mutable darray[u32]&):" not in FIXTURE or \
        "in a:" not in FIXTURE:
    raise SystemExit("owner regression must collide a region parameter with an Arena& block on the same logical line")
if 'clean "$(cat "$REPO_ROOT/test/repro/region_escape_param_owner_line_zero.elisa")"' not in SMOKE or \
        'python3 "$REPO_ROOT/test/proofs/check_region_escape_param_owner_identity.py"' not in SMOKE:
    raise SystemExit("region-scope smoke must retain the owner-collision fixture and source proof")

print("region-escape region-parameter owner checks passed")
