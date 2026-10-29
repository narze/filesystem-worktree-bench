#!/usr/bin/env python3
"""Finish a failed run without changing its original batch implementation."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from types import SimpleNamespace

import bench


def pending_samples(result):
    done = {(s['round'], s['workers']) for s in result['samples']}
    if len(done) != len(result['samples']):
        raise ValueError('Duplicate samples')
    rng = random.Random(42)
    pending = []
    for number in range(1, result['metadata']['runs'] + 1):
        order = list(result['metadata']['workers'])
        rng.shuffle(order)
        pending.extend((number, w) for w in order if (number, w) not in done)
    return pending


def recoverable(error):
    message = str(error)
    return all(part in message for part in ("'worktree', 'add'", 'failed to read ', '/commondir:'))


def original_batch(root, result):
    script = Path(bench.__file__)
    context = json.loads((root.parent / 'host-context.json').read_text())
    actual = hashlib.sha256(script.read_bytes()).hexdigest()
    if actual != context['runner_sha256']:
        raise ValueError('Original runner has changed')
    # Compile the original nested function unchanged, supplying its saved closure.
    main = next(n for n in ast.parse(script.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'main')
    batch = next(n for n in ast.walk(main) if isinstance(n, ast.FunctionDef) and n.name == 'batch')
    meta = result['metadata']
    namespace = {**vars(bench), 'args': SimpleNamespace(skip_install=False),
                 'bare': root / 'repo.git', 'trees': root / 'trees', 'commit': meta['commit'],
                 'install_args': [meta['pnpm_executable'], 'install', '--frozen-lockfile',
                                  '--ignore-scripts', '--store-dir', str(root / 'pnpm-store'),
                                  '--package-import-method', meta['import_method'],
                                  '--reporter', 'append-only']}
    exec(compile(ast.Module(body=[batch], type_ignores=[]), str(script), 'exec'), namespace)
    return namespace['batch']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    root = args.run.resolve()
    result = json.loads((root / 'results.json').read_text())
    if result['status'] != 'failed' or not recoverable(RuntimeError(result.get('error', ''))):
        raise ValueError('Only the observed Git commondir read failure can be resumed')
    pending = pending_samples(result)
    batch = original_batch(root, result)
    backup = root / 'results-before-resume.json'
    if not backup.exists():
        backup.write_text(json.dumps(result, indent=2) + '\n')
    first_round, first_workers = pending[0]
    result.setdefault('discarded_attempts', []).append({
        'round': first_round, 'workers': first_workers, 'error': result.pop('error'),
        'note': 'Failed original checkout batch, without a complete timing sample'})
    result['metadata'].setdefault('resumptions_utc', []).append(datetime.now(timezone.utc).isoformat())
    result['status'] = 'running'
    bench.save(root, result)
    try:
        for number, workers in pending:
            for attempt in range(1, 4):
                try:
                    sample = batch(workers, number)
                    break
                except RuntimeError as error:
                    result['discarded_attempts'].append({
                        'round': number, 'workers': workers, 'error': str(error),
                        'note': f'Resume attempt {attempt} failed'})
                    bench.save(root, result)
                    if not recoverable(error) or attempt == 3:
                        raise
                    print(f'Retrying checkout batch: round {number}, {workers} workers', flush=True)
            result['samples'].append(sample)
            bench.save(root, result)
            print(f'Round {number}/10, {workers} workers: {sample["total_seconds"]:.3f}s batch', flush=True)
        result['status'] = 'complete'
    except BaseException as error:
        result['status'] = 'failed'
        result['error'] = str(error)
        raise
    finally:
        result['metadata']['finished_utc'] = datetime.now(timezone.utc).isoformat()
        bench.save(root, result)


if __name__ == '__main__':
    main()
