#!/usr/bin/env python3
"""Exploratory paired full-process warm incremental checks; never cold compile timing."""
import argparse, csv, hashlib, json, math, os, platform, re, resource, signal, statistics, subprocess, time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("parent_root", type=Path)
parser.add_argument("parent_binary", type=Path)
parser.add_argument("candidate_root", type=Path)
parser.add_argument("candidate_binary", type=Path)
parser.add_argument("corpus", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--pairs", type=int, default=7)
parser.add_argument("--timeout-seconds", type=int, default=900,
                    help="per-compiler-process timeout; kills its process group")
args = parser.parse_args()
if args.pairs < 1: parser.error("pairs must be positive")
if args.timeout_seconds < 1: parser.error("timeout-seconds must be positive")
args.output = args.output.resolve()
args.output.mkdir(parents=True, exist_ok=True)
products = {"parent": (args.parent_root.resolve(), args.parent_binary.resolve()), "candidate": (args.candidate_root.resolve(), args.candidate_binary.resolve())}
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def checked(command): return subprocess.check_output(command, text=True).strip()
def inputs(root): return checked(["python3", str(root / "scripts/stage1_provenance.py"), "inputs", str(root)])
def linked_llvm(binary):
    rows = checked(["otool", "-L", str(binary)]).splitlines()
    return Path(next(row.strip().split(" (", 1)[0] for row in rows if "libLLVM" in row)).resolve()
pins, fingerprints, libraries = {}, {}, {}
for arm, (root, binary) in products.items():
    subprocess.run(["python3", str(root / "scripts/stage1_provenance.py"), "check", str(root), str(binary)], check=True)
    fingerprints[arm] = inputs(root)
    libraries[arm] = linked_llvm(binary)
    for path in [binary, Path(str(binary) + ".provenance.json")]: pins[str(path)] = digest(path)
assert libraries['parent'] == libraries['candidate'], libraries
pins[str(libraries['parent'])] = digest(libraries['parent'])
manifest = json.loads((args.corpus / "manifest.json").read_text())
pins[str((args.corpus / 'manifest.json').resolve())] = digest(args.corpus / 'manifest.json')
for workload in manifest['workloads']:
    for filename in workload['sha256']:
        path = (args.corpus / workload['directory'] / filename).resolve()
        pins[str(path)] = digest(path)
metadata = {
    "status": "exploratory shared-Mac opt-in warm semantic-cache only",
    "platform": platform.platform(),
    "pairs": args.pairs,
    "compiler_process_timeout_seconds": args.timeout_seconds,
    "elisa_force_contracts_inherited": "set" if "ELISACORE_FORCE_CONTRACTS" in os.environ else "unset",
    "elisa_force_contracts_effective": "unset for prime and measured invocations",
    "source_inputs": fingerprints,
    "product_and_llvm_hashes": pins,
    "corpus": manifest,
}
(args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

def run_compiler(command, env, cwd):
    proc = subprocess.Popen(
        command, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(command, args.timeout_seconds, stdout, stderr) from error
    result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command, stdout, stderr)
    return result

rows = []
report_pattern = re.compile(r"^incremental-ga-cache:.*$", re.MULTILINE)
for workload in manifest['workloads']:
    name = workload['directory']
    source_directory = args.corpus / name
    original = (source_directory / 'program.elisa').read_bytes()
    edited = (source_directory / 'program.body-edit.elisa').read_bytes()
    for filename, expected in workload['sha256'].items(): assert digest(source_directory / filename) == expected
    directory = args.output / name
    directory.mkdir(exist_ok=True)
    source = directory / 'program.elisa'
    for pair in range(args.pairs):
        evidence = {}
        for arm in (['parent', 'candidate'] if pair % 2 == 0 else ['candidate', 'parent']):
            root, binary = products[arm]
            env = os.environ.copy()
            for key in ['ELISA_STAGE1_PERMISSIVE', 'ELISA_STAGE1_TIMINGS', 'ELISA_INCREMENTAL_SHADOW', 'ELISA_INCREMENTAL_SHADOW_REPORT', 'ELISA_SEMANTIC_SERIAL', 'ELISACORE_FORCE_CONTRACTS']: env.pop(key, None)
            env['ELISA_STAGE1_INCREMENTAL_CACHE_DIR'] = str(directory / ('cache-' + arm))
            env['ELISA_STAGE1_INCREMENTAL_CACHE_REPORT'] = '1'
            command = [str(binary), '-emit', 'check', str(source)]
            source.write_bytes(original)
            primed = run_compiler(command, env, root)
            (directory / f'{arm}-{pair}-prime.stderr').write_bytes(primed.stderr)
            prior_files = list((directory / ('cache-' + arm)).glob('*.elisa-semantic'))
            assert len(prior_files) == 1, prior_files
            prior_bytes = prior_files[0].read_bytes()
            prior_hash = hashlib.sha256(prior_bytes).hexdigest()
            (directory / f'{arm}-{pair}-prior.elisa-semantic').write_bytes(prior_bytes)
            source.write_bytes(edited)
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            load_before = os.getloadavg()
            start = time.perf_counter_ns()
            result = run_compiler(command, env, root)
            wall = (time.perf_counter_ns() - start) / 1e9
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            stderr = result.stderr.decode()
            reports = report_pattern.findall(stderr)
            assert len(reports) == 1 and 'prior=valid' in reports[0] and 'published=yes' in reports[0], reports
            expected_matches = 1 if 'supported_helpers' in workload else workload['helpers']
            assert re.search(r' matched=' + str(expected_matches) + r' visited=' + str(workload['functions']) + r' ', reports[0]), reports
            clean = report_pattern.sub('', stderr)
            evidence[arm] = (result.stdout, clean, reports, prior_hash)
            (directory / f'{arm}-{pair}.stderr').write_bytes(result.stderr)
            (directory / f'{arm}-{pair}.stdout').write_bytes(result.stdout)
            rows.append({"workload": name, "pair": pair, "arm": arm, "wall_seconds": wall, "cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime, "load_before": load_before[0], "load_after": os.getloadavg()[0], "report": reports[0], "prior_snapshot_sha256": prior_hash})
        assert evidence['parent'] == evidence['candidate'], evidence
    print('completed ' + name, flush=True)
for path, expected in pins.items(): assert digest(Path(path)) == expected, path
for arm, (root, binary) in products.items(): assert inputs(root) == fingerprints[arm], arm
with (args.output / 'samples.csv').open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
summaries = {}
for workload in manifest['workloads']:
    name = workload['directory']
    samples = [row for row in rows if row['workload'] == name]
    ratios = [next(r['wall_seconds'] for r in samples if r['pair'] == pair and r['arm'] == 'parent') / next(r['wall_seconds'] for r in samples if r['pair'] == pair and r['arm'] == 'candidate') for pair in range(args.pairs)]
    summaries[name] = {"median_paired_wall_speedup_parent_over_candidate": statistics.median(ratios), "geomean_paired_wall_speedup_parent_over_candidate": math.exp(sum(map(math.log, ratios)) / len(ratios)), "candidate_wins": sum(r > 1 for r in ratios)}
(args.output / 'summary.json').write_text(json.dumps(summaries, indent=2) + "\n")
