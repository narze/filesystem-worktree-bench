#!/usr/bin/env python3
"""Delete only a known completed benchmark run with an archived matching result."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def validate_run(run, parent, expected_sha256, commit):
    run, parent = Path(run), Path(parent).resolve()
    if run.is_symlink() or run.absolute() != run.resolve() or run.parent != parent:
        raise ValueError('Unexpected run path, parent or symlink')
    if not run.name.startswith('fsbench-'):
        raise ValueError('Unexpected run name')
    path = run / 'results.json'
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('Result does not match the preserved archive')
    result = json.loads(path.read_text())
    expected = {(n, w) for n in range(1, result['metadata']['runs'] + 1)
                for w in result['metadata']['workers']}
    actual = [(s['round'], s['workers']) for s in result['samples']]
    if result['status'] != 'complete' or result['metadata']['commit'] != commit:
        raise ValueError('Run is unfinished or has a different commit')
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Incomplete or duplicate samples')
    if any((run / 'trees').iterdir()):
        raise ValueError('Remaining worktrees need investigation')
    return run


def remove_completed(directory, run, expected_sha256, commit, whole_directory=False):
    directory, run = Path(directory), Path(run)
    validated = validate_run(run, directory if whole_directory else directory.parent,
                             expected_sha256, commit)
    victim = directory if whole_directory else validated
    if whole_directory:
        allowed_parent = Path.home() / 'fsbench'
        if (directory.is_symlink() or directory.resolve() != directory.absolute()
                or directory.parent != allowed_parent or not directory.name.startswith('eventpop-')):
            raise ValueError('Refusing to delete outside the known benchmark scratch parent')
        runner = directory / 'bench.py'
        if hashlib.sha256(runner.read_bytes()).hexdigest() != 'a2cb69b94b95c7cbf35a9f0b9f729553051d561785dcc7f32c6b946a2b871e9d':
            raise ValueError('Unexpected benchmark runner')
    before = shutil.disk_usage(victim.parent)._asdict()
    footprint = int(subprocess.check_output(['du', '-sk', str(victim)], text=True).split()[0]) * 1024
    shutil.rmtree(victim)
    return {'completed_utc': datetime.now(timezone.utc).isoformat(), 'removed_path': str(victim),
            'result_sha256': expected_sha256, 'approx_allocated_bytes_removed': footprint,
            'exists_after': victim.exists(), 'filesystem_bytes_before': before,
            'filesystem_bytes_after': shutil.disk_usage(victim.parent)._asdict()}
