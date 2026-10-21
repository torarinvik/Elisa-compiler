#!/usr/bin/env python3
"""Check that profiling controls change optimization attributes, not LLVM bodies."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('authority_probe_ir.py')
IR = '''define void @Semantic.ga_walk() #0 {
  ret void
}
define ptr @ctx_aos_store_record(ptr %p, i64 %i) #0 {
  ret ptr %p
}
define ptr @ctx_aos_store_sized_record(ptr %p, i64 %i) #0 {
  ret ptr %p
}
define void @other() #0 {
  ret void
}
define void @special() #1 {
  ret void
}
attributes #0 = { nounwind "target-cpu"="apple-m5" }
attributes #1 = { alwaysinline nounwind }
'''


class AuthorityProbeTest(unittest.TestCase):
    def run_probe(self, source, *flags):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'in.ll'
            output_path = Path(directory) / 'out.ll'
            source_path.write_text(source)
            result = subprocess.run([sys.executable, str(SCRIPT), str(source_path), str(output_path), *flags], capture_output=True, text=True, timeout=30)
            return result, output_path.read_text() if output_path.exists() else None

    def test_default_preserves_target_attributes_special_groups_and_bodies(self):
        result, output = self.run_probe(IR)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = IR.replace('@ctx_aos_store_record(ptr %p, i64 %i) #0', '@ctx_aos_store_record(ptr %p, i64 %i) #2').replace(
            '@ctx_aos_store_sized_record(ptr %p, i64 %i) #0', '@ctx_aos_store_sized_record(ptr %p, i64 %i) #2').replace('@other() #0', '@other() #2')
        self.assertEqual(output, expected + '\nattributes #2 = { nounwind "target-cpu"="apple-m5" optnone noinline }\n')

    def test_packed_reads_only_reenables_exact_helpers(self):
        result, output = self.run_probe(IR, '--packed-reads')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, IR.replace('@other() #0', '@other() #2') + '\nattributes #2 = { nounwind "target-cpu"="apple-m5" optnone noinline }\n')

    def test_helpers_alone_do_not_count_as_an_authority_probe(self):
        result, output = self.run_probe(IR.replace('@Semantic.ga_walk', '@ordinary'), '--packed-reads')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)

    def test_context_lookup_flag_preserves_bodies_and_exact_names(self):
        helpers = ''.join(f'define i64 @{name}(i64 %n) #0 {{\n  ret i64 %n\n}}\n' for name in (
            'ctx_unhash_u64', 'ctx_unhash_xor_31', 'ctx_hash_u64',
            'string_view_index', 'ctx_string_view_index', 'ctx_hash_u64_other'))
        source = IR.replace('attributes #0 =', helpers + 'attributes #0 =')
        result, output = self.run_probe(source, '--packed-reads', '--context-lookups')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = source.replace('@other() #0', '@other() #2').replace('@ctx_hash_u64_other(i64 %n) #0', '@ctx_hash_u64_other(i64 %n) #2')
        self.assertEqual(output, expected + '\nattributes #2 = { nounwind "target-cpu"="apple-m5" optnone noinline }\n')

    def test_refuses_group_that_already_disables_optimization(self):
        result, output = self.run_probe(IR.replace('attributes #0 = { nounwind', 'attributes #0 = { optnone nounwind'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)

    def test_lookup_tables_preserve_generic_and_exact_helper_bodies(self):
        helpers = ''.join(f'define i64 @{name}(i64 %n) #0 {{\n  ret i64 %n\n}}\n' for name in (
            '"arena_dict_find_index$generic_v1$abc"', 'ctx_string_views_eq',
            'Semantic.name_hash', 'Semantic.name_hash_other'))
        source = IR.replace('attributes #0 =', helpers + 'attributes #0 =')
        result, output = self.run_probe(source, '--packed-reads', '--lookup-tables')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = source.replace('@other() #0', '@other() #2').replace('@Semantic.name_hash_other(i64 %n) #0', '@Semantic.name_hash_other(i64 %n) #2')
        self.assertEqual(output, expected + '\nattributes #2 = { nounwind "target-cpu"="apple-m5" optnone noinline }\n')


if __name__ == '__main__':
    unittest.main()
