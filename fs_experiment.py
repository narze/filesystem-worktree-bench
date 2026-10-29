#!/usr/bin/env python3
"""Paired filesystem-image experiment. Never formats a physical block device."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import stat
import subprocess
import sys
import tempfile

import bench
import inventory
from resume import original_batch, recoverable

COMMIT = '0e0499f42444f1e4b2c0a6d11fc8043b42be295a'
RUNNER_SHA = 'a2cb69b94b95c7cbf35a9f0b9f729553051d561785dcc7f32c6b946a2b871e9d'


def require_image(image, root):
    image, root = Path(image), Path(root).resolve()
    if (image.is_symlink() or image.absolute() != image.resolve()
            or image.parent != root or image.suffix != '.img'
            or not image.exists() or not stat.S_ISREG(image.stat().st_mode)
            or image.stat().st_uid != os.getuid()):
        raise ValueError('Format target must be our own regular image file')
    return image


def measured_schedule(cases, rounds):
    worker_rng, case_rng = random.Random(42), random.Random(73)
    schedule = []
    for number in range(1, rounds + 1):
        workers = [1, 2, 3, 4]
        worker_rng.shuffle(workers)
        for count in workers:
            order = list(cases)
            case_rng.shuffle(order)
            schedule.extend((number, count, case) for case in order)
    return schedule


def preallocate_image(image):
    bench.command(['fallocate', '-l', str(image.stat().st_size), image])
    if image.stat().st_blocks * 512 < image.stat().st_size:
        raise ValueError('Backing image is sparse after formatting')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secret-file', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--pnpm', required=True)
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    if hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest() != RUNNER_SHA:
        raise ValueError('Original timing code changed')
    if shutil.disk_usage(workspace).free < 60 * 2**30:
        raise ValueError('At least 60 GiB free space is required')
    output = workspace / 'xfs-results'
    output.mkdir(exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix='fsbench-xfs-compare-', dir=workspace))
    images = root / 'images'; images.mkdir()
    cases = ['native-btrfs', 'image-btrfs', 'image-xfs']
    targets = {case: root / case for case in cases}
    for target in targets.values():target.mkdir()
    session = {'root': str(root), 'started_utc': datetime.now(timezone.utc).isoformat(),
               'commit': COMMIT, 'image_size_bytes': 16 * 2**30, 'loops': {}, 'mounted': [],
               'targets': {case: str(path) for case, path in targets.items()},
               'protocol': 'Paired rounds; worker order seed 42, case order seed 73; original batch code',
               'scope': 'Image-backed XFS and Btrfs over NOCOW files on native Btrfs; not bare-metal filesystem isolation'}
    records, run_roots = {}, {}

    def checkpoint():
        (workspace / '.xfs-session.json').write_text(json.dumps(session, indent=2) + '\n')
        (output / 'session.json').write_text(json.dumps(session, indent=2) + '\n')

    def sudo(*command):
        password = args.secret_file.read_bytes().rstrip(b'\r\n') + b'\n'
        p = subprocess.run(['sudo', '-S', '-p', '', *map(str, command)], input=password,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            raise RuntimeError(f'Privileged command failed: {command}\n{p.stderr.decode(errors="replace")}')
        return p.stdout.decode(errors='replace').strip()

    def persist(case):
        bench.save(run_roots[case], records[case])
        destination = output / case
        destination.mkdir(exist_ok=True)
        for name in ('results.json', 'results.csv', 'prepare.log'):
            path = run_roots[case] / name
            if path.exists():shutil.copy2(path, destination / name)

    checkpoint()
    try:
        host = inventory.collect(workspace)
        host['runner_sha256'] = RUNNER_SHA
        (output / 'host-context.json').write_text(json.dumps(host, indent=2) + '\n')
        session['tool_versions'] = {tool: bench.command(command) for tool, command in {
            'xfsprogs': ['mkfs.xfs', '-V'], 'btrfs_progs': ['mkfs.btrfs', '--version']}.items()}
        for case, filesystem in (('image-btrfs', 'btrfs'), ('image-xfs', 'xfs')):
            image = images / (filesystem + '.img')
            image.touch()
            bench.command(['chattr', '+C', image])
            bench.command(['fallocate', '-l', str(16 * 2**30), image])
            require_image(image, images)
            flags = bench.command(['lsattr', image])
            if 'C' not in flags.split()[0]:raise ValueError('Backing file is not NOCOW')
            command = (['mkfs.xfs', '-f', '-K', '-m', 'crc=1,reflink=1', '-d',
                        f'file=1,name={image},size=16g'] if filesystem == 'xfs'
                       else ['mkfs.btrfs', '-f', '-K', image])
            (output / (filesystem + '-mkfs.txt')).write_text(bench.command(command) + '\n')
            # mkfs.xfs file mode recreates a sparse file; restore matching allocation.
            preallocate_image(image)
            loop = sudo('losetup', '--find', '--show', '--nooverlap', image)
            if not loop.startswith('/dev/loop') or not loop.removeprefix('/dev/loop').isdigit():
                raise ValueError('Unexpected loop-device path')
            session['loops'][case] = {'device': loop, 'image': str(image), 'attributes': flags,
                                      'logical_bytes': image.stat().st_size,
                                      'allocated_bytes_before_mount': image.stat().st_blocks * 512}
            checkpoint()
            options = 'noatime,nodiscard' + (',compress=zstd:3,ssd' if filesystem == 'btrfs' else '')
            sudo('mount', '-t', filesystem, '-o', options, loop, targets[case])
            session['mounted'].append(case);checkpoint()
            sudo('chown', f'{os.getuid()}:{os.getgid()}', targets[case])
        for case in cases:
            target = targets[case]
            mount = json.loads(bench.command(['findmnt', '-T', target, '-J', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS']))
            expected = 'xfs' if case == 'image-xfs' else 'btrfs'
            if mount['filesystems'][0]['fstype'] != expected:raise ValueError('Wrong target filesystem')
            (target / 'host-context.json').write_text(json.dumps({'runner_sha256': RUNNER_SHA}))
            (output / (case + '-mount.json')).write_text(json.dumps(mount, indent=2) + '\n')
            print(f'Preparing and warming {case}; this includes excluded preflight samples.', flush=True)
            subprocess.run([sys.executable, str(Path(bench.__file__)), '--source', str(args.source.resolve()),
                            '--commit', COMMIT, '--target', str(target), '--pnpm', args.pnpm,
                            '--workers', '1', '2', '3', '4', '--runs', '1', '--warmups', '1'], check=True)
            run, = target.glob('fsbench-*')
            run_roots[case] = run
            record = json.loads((run / 'results.json').read_text())
            dest = output / case;dest.mkdir()
            (dest / 'preflight.json').write_text(json.dumps(record, indent=2) + '\n')
            record['samples'] = [];record['status'] = 'running'
            record['metadata'].update({'runs': 10, 'preflight_batches_excluded': 4,
                                       'paired_experiment': True, 'case': case,
                                       'measured_started_utc': datetime.now(timezone.utc).isoformat()})
            records[case] = record;persist(case)
        batch = {case: original_batch(run_roots[case], records[case]) for case in cases}
        schedule = measured_schedule(cases, 10)
        (output / 'schedule.json').write_text(json.dumps(schedule, indent=2) + '\n')
        print('Starting paired measured rounds.', flush=True)
        for number, workers, case in schedule:
            for attempt in range(1, 4):
                try:
                    sample = batch[case](workers, number)
                    break
                except RuntimeError as error:
                    records[case].setdefault('discarded_attempts', []).append({
                        'round': number, 'workers': workers, 'error': str(error)})
                    persist(case)
                    if not recoverable(error) or attempt == 3:raise
            records[case]['samples'].append(sample);persist(case)
            print(f'Round {number}/10, {workers} workers, {case}: {sample["total_seconds"]:.3f}s', flush=True)
        for case in cases:
            records[case]['status'] = 'complete'
            records[case]['metadata']['finished_utc'] = datetime.now(timezone.utc).isoformat()
            persist(case)
        session['status'] = 'complete'
    except BaseException as error:
        session['status'] = 'failed';session['error'] = str(error)
        for case in records:
            records[case]['status'] = 'failed';records[case]['error'] = str(error);persist(case)
        raise
    finally:
        checkpoint()
        print('Preserving evidence and cleaning temporary mounts and images.', flush=True)
        try:
            footprint = int(bench.command(['du', '-skx', root]).split()[0]) * 1024
            for case in list(reversed(session['mounted'])):
                sudo('umount', targets[case]);session['mounted'].remove(case);checkpoint()
            for case, item in session['loops'].items():
                mapping = json.loads(sudo('losetup', '-J', '-O', 'NAME,BACK-FILE', item['device']))
                if Path(mapping['loopdevices'][0]['back-file']).resolve() != Path(item['image']).resolve():
                    raise ValueError('Loop mapping changed; refusing detach')
                sudo('losetup', '-d', item['device'])
            shutil.rmtree(root)
            receipt = {'removed_utc': datetime.now(timezone.utc).isoformat(), 'root': str(root),
                       'exists_after': root.exists(), 'approx_allocated_bytes_removed': footprint,
                       'loops_detached': [item['device'] for item in session['loops'].values()]}
            (output / 'cleanup.json').write_text(json.dumps(receipt, indent=2) + '\n')
            args.secret_file.unlink(missing_ok=True)
            (workspace / '.xfs-session.json').unlink(missing_ok=True)
            print('Temporary filesystems unmounted, loop devices detached, images removed.', flush=True)
        except BaseException as error:
            session['cleanup_error'] = str(error);checkpoint()
            print('Cleanup needs attention; preserving image files and credential for the pending cleanup.', flush=True)
            raise


if __name__ == '__main__':main()
