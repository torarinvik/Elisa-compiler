"""Stage1 product provenance must notice source, build-recipe, and binary changes."""
from pathlib import Path
import tempfile

import stage1_provenance


original_revision = stage1_provenance.source_revision
stage1_provenance.source_revision = lambda _root: "test-revision"

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    for name in stage1_provenance.SOURCE_DIRS:
        (root / name).mkdir(parents=True)
        (root / name / "unit.elisa").write_text("module Unit:\n    pass\n")
    for name in stage1_provenance.BUILD_RECIPES:
        recipe = root / name
        recipe.parent.mkdir(parents=True, exist_ok=True)
        recipe.write_text("build recipe\n")
    product = root / "bin" / "elisac-stage1"
    product.parent.mkdir()
    product.write_bytes(b"stage1 product")

    stage1_provenance.record(root, product)
    assert stage1_provenance.check(root, product) == 0

    (root / "src" / "unit.elisa").write_text("module Unit:\n    def changed() -> i64: return 1\n")
    assert stage1_provenance.check(root, product) == 2

    (root / "src" / "unit.elisa").write_text("module Unit:\n    pass\n")
    (root / "scripts" / "elisac_stage1_seed.sh").write_text("changed build recipe\n")
    assert stage1_provenance.check(root, product) == 2

    (root / "scripts" / "elisac_stage1_seed.sh").write_text("build recipe\n")
    product.write_bytes(b"replaced product")
    assert stage1_provenance.check(root, product) == 2

stage1_provenance.source_revision = original_revision
print("stage1 provenance: exact source, recipe and product fingerprints verified")
