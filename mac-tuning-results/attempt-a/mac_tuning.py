"""Scoped macOS tuning experiment. Never changes the startup volume's settings."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import time


def validate_volume(info, uuid, name):
    if (not uuid or info.get('VolumeUUID') != uuid
            or not name.startswith('FSBenchTuning-') or info.get('VolumeName') != name
            or info.get('MountPoint') != '/Volumes/' + name
            or not re.fullmatch(r'disk\d+s\d+', info.get('DeviceIdentifier', ''))):
        raise ValueError('Refusing operation on an unrecognized experiment volume')


def require_encrypted(info):
    if not info.get('Encryption'):
        raise ValueError('Experiment volume must be encrypted')


def main():
    import bench
    import inventory
    os.environ['PATH'] = '/Users/narze/.local/share/mise/installs/node/24.22.1/bin:' + os.environ['PATH']
    password = sys.stdin.buffer.readline().rstrip(b'\r\n') + b'\n'
    evidence = Path(__file__).resolve().parent
    name = 'FSBenchTuning-' + evidence.name.rsplit('-', 1)[-1]
    mount = Path('/Volumes') / name
    state = {'started_utc': datetime.now(timezone.utc).isoformat(), 'name': name,
             'status': 'starting', 'conditions': [], 'free_before': shutil.disk_usage('/Users/narze').free,
             'protocol': 'A/B/C/D, 10 randomized worker rounds each; warm cache; pnpm 11.18.0'}

    def save():
        tmp = evidence / 'experiment.json.tmp'
        tmp.write_text(json.dumps(state, indent=2) + '\n')
        tmp.replace(evidence / 'experiment.json')

    def command(args, privileged=False, data=None):
        if privileged:
            args = ['sudo', '-S', '-p', '', *args]
            data = password if data is None else password + data
        p = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode:
            raise RuntimeError(f'{args[:5]}: {p.stdout.decode(errors="replace")[-4000:]}')
        return p.stdout

    def info(device):
        return plistlib.loads(command(['diskutil', 'info', '-plist', str(device)]))

    def snapshot():
        return {'utc': datetime.now(timezone.utc).isoformat(),
                'processes': command(['ps', '-axo', 'pid,ppid,time,pcpu,rss,comm']).decode(),
                'vm_stat': command(['vm_stat']).decode(),
                'swap': command(['sysctl', 'vm.swapusage']).decode(),
                'free_bytes': shutil.disk_usage('/Users/narze').free}

    def event_files():
        return command(['find', str(mount / '.fseventsd'), '-maxdepth', '1', '-type', 'f',
                        '-exec', 'stat', '-f', '%N %z %m', '{}', ';'], privileged=True).decode()

    uuid = None
    device = None
    save()
    if state['free_before'] < 30 * 1024**3:
        raise RuntimeError('Less than 30 GiB free; no volume created')
    state['inventory_before'] = inventory.collect('/Users/narze')
    state['startup_spotlight'] = command(['mdutil', '-s', '/']).decode()
    state['data_spotlight'] = command(['mdutil', '-s', '/System/Volumes/Data']).decode()
    state['resources_before'] = snapshot()
    data_info = info('/System/Volumes/Data')
    save()
    try:
        if mount.exists():
            raise RuntimeError('Experiment mount already exists')
        # The random disposable-volume key never enters argv or an output file.
        key = secrets.token_urlsafe(36).encode() + b'\n'
        state['create_output'] = command(['diskutil', 'apfs', 'addVolume',
            data_info['APFSContainerReference'], 'APFS', name, '-quota', '16g',
            '-stdinpassphrase'], data=key).decode()
        created = info(mount)
        uuid, device = created['VolumeUUID'], created['DeviceIdentifier']
        state['volume_uuid'], state['device'] = uuid, device
        save()
        validate_volume(created, uuid, name)
        require_encrypted(created)
        state['volume_info'] = created
        command(['chown', str(os.getuid()) + ':' + str(os.getgid()), str(mount)], privileged=True)
        command(['diskutil', 'enableOwnership', device], privileged=True)
        seed = mount / 'seed-store'
        # Alternate the two toggles, changing one at a time. A repeat baseline follows
        # only if an additional run is requested; all background activity is retained.
        for label, spotlight, logging in [('A', True, True), ('B', False, True),
                                           ('D', False, False), ('C', True, False)]:
            validate_volume(info(device), uuid, name)
            marker = mount / '.fseventsd' / 'no_log'
            command(['mkdir', '-p', str(marker.parent)], privileged=True)
            if logging:
                command(['rm', '-f', str(marker)], privileged=True)
            else:
                command(['touch', str(marker)], privileged=True)
            command(['diskutil', 'unmount', device])
            command(['diskutil', 'mount', device])
            validate_volume(info(device), uuid, name)
            require_encrypted(info(device))
            status = command(['mdutil', '-i', 'on' if spotlight else 'off', str(mount)], privileged=True).decode()
            condition = {'label': label, 'spotlight_requested': spotlight,
                         'persistent_logging_requested': logging, 'mdutil_toggle': status}
            state['conditions'].append(condition)
            save()
            print(f'Condition {label}: Spotlight={spotlight}, persistent log={logging}; settling 60s', flush=True)
            for _ in range(4):
                time.sleep(15)
                print('Settling...', flush=True)
            condition['mdutil_status'] = command(['mdutil', '-s', str(mount)]).decode()
            if ('Indexing enabled' in condition['mdutil_status']) != spotlight:
                raise RuntimeError('Spotlight state does not match the requested condition')
            condition['mounts'] = command(['mount']).decode()
            condition['event_files_before'] = event_files()
            condition['resources_before'] = snapshot()
            before = set(mount.glob('fsbench-*'))
            original_argv = sys.argv
            original_save = bench.save
            last_sample_count = -1

            def observed_save(root, result):
                nonlocal last_sample_count
                original_save(root, result)
                count = len(result['samples'])
                if count != last_sample_count:
                    last_sample_count = count
                    with (evidence / f'{label}-resources.jsonl').open('a') as f:
                        f.write(json.dumps({'samples_completed': count, **snapshot()}) + '\n')

            sys.argv = ['bench.py', '--source', '/Users/narze/Code/github.com/eventpop/eventpop',
                        '--target', str(mount), '--commit', '0e0499f42444f1e4b2c0a6d11fc8043b42be295a',
                        '--runs', '10', '--pnpm', '/Users/narze/.local/share/mise/installs/pnpm/11.18.0/pnpm']
            if seed.exists():
                sys.argv += ['--seed-store', str(seed), '--offline-setup']
            bench.save = observed_save
            try:
                bench.main()
            finally:
                sys.argv, bench.save = original_argv, original_save
                runs = set(mount.glob('fsbench-*')) - before
                for run in runs:
                    destination = evidence / (label + '-results')
                    destination.mkdir(exist_ok=True)
                    for file in run.iterdir():
                        if file.is_file():
                            shutil.copy2(file, destination / file.name)
            if len(runs) != 1:
                raise RuntimeError('Unexpected run directories')
            run = runs.pop()
            result = json.loads((run / 'results.json').read_text())
            if result['status'] != 'complete' or len(result['samples']) != 40:
                raise RuntimeError('Incomplete condition')
            condition['resources_after'] = snapshot()
            condition['event_files_after'] = event_files()
            condition['status'] = 'complete'
            save()
            if seed.exists():
                shutil.rmtree(seed)
            (run / 'pnpm-store').rename(seed)
            shutil.rmtree(run)
        state['status'] = 'complete'
    except BaseException as error:
        state['status'], state['error'] = 'failed', repr(error)
        raise
    finally:
        if uuid:
            try:
                current = info(device)
                validate_volume(current, uuid, name)
                # Delete only the exact volume created by this run, never its container.
                state['delete_output'] = command(['diskutil', 'apfs', 'deleteVolume', device]).decode()
                state['volume_deleted'] = True
            except BaseException as error:
                state['cleanup_error'] = repr(error)
        state['free_after'] = shutil.disk_usage('/Users/narze').free
        state['finished_utc'] = datetime.now(timezone.utc).isoformat()
        state['startup_spotlight_after'] = command(['mdutil', '-s', '/']).decode()
        save()
        print(json.dumps({k: state[k] for k in ('status', 'free_after', 'volume_deleted', 'cleanup_error') if k in state}), flush=True)


if __name__ == '__main__':
    main()
