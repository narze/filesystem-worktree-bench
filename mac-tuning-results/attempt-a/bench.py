#!/usr/bin/env python3
"""Warm-cache worktree lifecycle benchmark, using only the Python standard library."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import tempfile
import threading
import time


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def command(args, cwd=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env={**os.environ, 'CI': 'true', 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode:
        raise RuntimeError(f'Command failed: {args}\n{result.stdout[-8000:]}')
    return result.stdout.strip()


def git(*args, cwd=None):
    return command(['git', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'core.fsmonitor=false', *args], cwd)


def parallel_phase(paths, action):
    barrier = threading.Barrier(len(paths) + 1)
    def worker(path):
        barrier.wait()
        start = time.perf_counter()
        action(path)
        return time.perf_counter() - start
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        futures = [pool.submit(worker, path) for path in paths]
        start = time.perf_counter()
        barrier.wait()
        durations = [future.result() for future in futures]
        wall = time.perf_counter() - start
    return {'batch_seconds': wall, 'worker_seconds': durations}


def save(root, result):
    temporary = root / 'results.json.tmp'
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(root / 'results.json')
    with (root / 'results.csv').open('w', newline='') as handle:
        fields = ['round', 'workers', 'checkout_seconds', 'install_seconds',
                  'delete_seconds', 'total_seconds', 'workflows_per_second']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in result['samples']:
            writer.writerow({
                'round': sample['round'], 'workers': sample['workers'],
                **{f'{stage}_seconds': sample.get(stage, {}).get('batch_seconds', '')
                   for stage in ('checkout', 'install', 'delete')},
                'total_seconds': sample['total_seconds'],
                'workflows_per_second': sample['workers'] / sample['total_seconds'],
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, default=Path.cwd())
    parser.add_argument('--commit', default='HEAD')
    parser.add_argument('--workers', nargs='+', type=positive, default=[1, 2, 3, 4])
    parser.add_argument('--runs', type=positive, default=10)
    parser.add_argument('--warmups', type=positive, default=1)
    parser.add_argument('--pnpm', default='pnpm')
    parser.add_argument('--import-method', choices=['auto', 'copy', 'hardlink', 'clone'], default='auto')
    parser.add_argument('--skip-install', action='store_true')
    parser.add_argument('--offline-setup', action='store_true',
                        help='seed the dedicated store from an existing store using --seed-store')
    parser.add_argument('--seed-store', type=Path,
                        help='copy an existing pnpm store into the dedicated store before setup')
    args = parser.parse_args()
    source = args.source.resolve()
    commit = git('-C', source, 'rev-parse', '--verify', args.commit + '^{commit}')
    args.target.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='fsbench-', dir=args.target.resolve()))
    print(f'Results: {root}', flush=True)
    bare = root / 'repo.git'
    trees = root / 'trees'
    trees.mkdir()
    store = root / 'pnpm-store'
    result = {'schema_version': 1, 'status': 'running', 'samples': [], 'metadata': {
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'source': str(source), 'commit': commit, 'target': str(root),
        'platform': platform.platform(), 'machine': platform.machine(),
        'cpu_count': os.cpu_count(), 'git_version': command(['git', '--version']),
        'python_version': platform.python_version(), 'workers': args.workers,
        'runs': args.runs, 'warmups_per_worker_count': args.warmups,
        'cache': 'warm / uncontrolled OS cache; no cache eviction',
        'durability': 'command completion; no fsync or cache flush',
        'import_method': args.import_method, 'install_scripts': False,
        'lifecycle': 'stage barriers: all checkouts, all installs, all deletions',
        'seed_store': str(args.seed_store) if args.seed_store else None,
        'free_bytes_before': shutil.disk_usage(root).free,
    }}
    if shutil.which('findmnt'):
        result['metadata']['mount'] = command(['findmnt', '-T', str(root), '-J',
                                                  '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'])
    else:
        result['metadata']['mount'] = command(['df', '-P', str(root)])
    save(root, result)
    try:
        git('clone', '--bare', '--no-hardlinks', source, bare)
        git('--git-dir', bare, 'cat-file', '-e', commit)
        result['metadata']['tracked_files'] = len(git('--git-dir', bare, 'ls-tree',
                                                        '-r', '--name-only', commit).splitlines())
        # Pin and verify the executable rather than letting pnpm download another version.
        pnpm = shutil.which(args.pnpm)
        install_args = []
        if not args.skip_install:
            if pnpm is None:
                raise RuntimeError('pnpm not found; use --pnpm /path/to/pnpm')
            manifest = json.loads(git('--git-dir', bare, 'show', f'{commit}:package.json'))
            expected = manifest.get('packageManager', '').split('+')[0]
            actual = command([pnpm, '--version'], cwd=root)
            if expected and expected != f'pnpm@{actual}':
                raise RuntimeError(f'Repo requires {expected}, found pnpm@{actual}. Use --pnpm.')
            result['metadata']['pnpm_version'] = actual
            result['metadata']['node_version'] = command(['node', '--version'])
            result['metadata']['pnpm_executable'] = pnpm
            lock = git('--git-dir', bare, 'show', f'{commit}:pnpm-lock.yaml')
            result['metadata']['lockfile_sha256_normalized'] = hashlib.sha256(lock.encode()).hexdigest()
            if args.seed_store:
                print('Copying seed store (outside timings)...', flush=True)
                shutil.copytree(args.seed_store.resolve(), store)
            install_args = [pnpm, 'install', '--frozen-lockfile', '--ignore-scripts',
                            '--store-dir', str(store), '--package-import-method', args.import_method,
                            '--reporter', 'append-only']
            prep = root / 'prepare'
            git('--git-dir', bare, 'worktree', 'add', '--detach', prep, commit)
            try:
                print('Preparing dedicated dependency store (outside timings)...', flush=True)
                output = command([*install_args, *(['--offline'] if args.offline_setup else [])], cwd=prep)
                (root / 'prepare.log').write_text(output + '\n')
            finally:
                shutil.rmtree(prep)
                git('--git-dir', bare, 'worktree', 'prune')
        save(root, result)

        def batch(workers, round_number):
            paths = [trees / f'worker-{i}' for i in range(workers)]
            sample = {'workers': workers, 'round': round_number}
            try:
                sample['checkout'] = parallel_phase(paths, lambda p: git(
                    '--git-dir', bare, 'worktree', 'add', '--detach', p, commit))
                if not args.skip_install:
                    sample['install'] = parallel_phase(paths, lambda p: command(
                        [*install_args, '--offline'], cwd=p))
                sample['delete'] = parallel_phase(paths, shutil.rmtree)
            finally:
                for path in paths:
                    if path.exists():
                        shutil.rmtree(path)
                git('--git-dir', bare, 'worktree', 'prune')
            sample['total_seconds'] = sum(sample[stage]['batch_seconds']
                                          for stage in ('checkout', 'install', 'delete') if stage in sample)
            return sample

        for workers in args.workers:
            for warmup in range(args.warmups):
                print(f'Warmup {warmup + 1}: {workers} workers', flush=True)
                batch(workers, 0)
        rng = random.Random(42)
        for round_number in range(1, args.runs + 1):
            order = list(args.workers)
            rng.shuffle(order)
            for workers in order:
                sample = batch(workers, round_number)
                result['samples'].append(sample)
                save(root, result)
                print(f'Round {round_number}/{args.runs}, {workers} workers: '
                      f'{sample["total_seconds"]:.3f}s batch', flush=True)
        result['status'] = 'complete'
    except BaseException as error:
        result['status'] = 'failed'
        result['error'] = str(error)
        raise
    finally:
        result['metadata']['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save(root, result)
    for workers in args.workers:
        times = [s['total_seconds'] for s in result['samples'] if s['workers'] == workers]
        print(f'{workers} workers: median {statistics.median(times):.3f}s, '
              f'range {min(times):.3f}-{max(times):.3f}s')


if __name__ == '__main__':
    main()
