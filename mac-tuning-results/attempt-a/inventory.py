#!/usr/bin/env python3
"""Read hardware facts without collecting serial numbers or system UUIDs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import socket
import subprocess


def select_fields(value, allowed):
    if isinstance(value, dict):
        return {k: select_fields(v, allowed) for k, v in value.items() if k in allowed}
    if isinstance(value, list):
        return [select_fields(v, allowed) for v in value]
    return value


def mac_device(df_output):
    lines = (df_output or '').splitlines()
    return lines[-1].split()[0] if len(lines) >= 2 else None


def collect(target):
    target = Path(target).resolve()
    errors = []

    def command(args, structured=False, plist=False):
        try:
            p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if p.returncode:
                errors.append({'command': args, 'error': p.stderr.decode(errors='replace').strip()})
                return None
            if plist:
                return plistlib.loads(p.stdout)
            text = p.stdout.decode(errors='replace').strip()
            return json.loads(text) if structured else text
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            errors.append({'command': args, 'error': str(error)})
            return None

    def read(path):
        try:
            return Path(path).read_text().strip()
        except OSError:
            return None

    result = {'captured_utc': datetime.now(timezone.utc).isoformat(),
              'hostname': socket.gethostname(), 'system': platform.system(),
              'kernel': platform.release(), 'architecture': platform.machine(),
              'python_version': platform.python_version(), 'target': str(target),
              'disk_usage_bytes': dict(zip(('total', 'used', 'free'), shutil.disk_usage(target))),
              'load_average': os.getloadavg(), 'git_version': command(['git', '--version'])}
    if platform.system() == 'Linux':
        dmi_fields = ('sys_vendor', 'product_name', 'product_version', 'board_vendor',
                      'board_name', 'bios_vendor', 'bios_version', 'bios_date')
        result['hardware'] = {k: read('/sys/class/dmi/id/' + k) for k in dmi_fields}
        cpu = command(['lscpu', '-J'], structured=True)
        wanted = {'Architecture:', 'CPU(s):', 'Model name:', 'Socket(s):',
                  'Core(s) per socket:', 'Thread(s) per core:', 'CPU max MHz:', 'CPU min MHz:'}
        result['cpu'] = {r['field'].rstrip(':'): r['data'] for r in (cpu or {}).get('lscpu', [])
                         if r['field'] in wanted}
        result['os_release'] = {line.split('=', 1)[0]: line.split('=', 1)[1].strip('"')
                                for line in (read('/etc/os-release') or '').splitlines()
                                if line.startswith(('NAME=', 'VERSION=', 'PRETTY_NAME='))}
        mem = {}
        for line in (read('/proc/meminfo') or '').splitlines():
            key, value = line.split(':', 1)
            if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
                mem[key] = int(value.split()[0]) * 1024
        result['memory_bytes'] = mem
        result['block_devices'] = command(['lsblk', '-J', '-b', '-o',
                                          'NAME,TYPE,SIZE,FSTYPE,MODEL,ROTA,TRAN,MOUNTPOINTS'], structured=True)
        result['filesystem'] = command(['findmnt', '-T', str(target), '-J', '-o',
                                       'TARGET,SOURCE,FSTYPE,OPTIONS'], structured=True)
        pci = command(['lspci']) or ''
        result['graphics'] = [line for line in pci.splitlines()
                              if any(k in line for k in ('VGA compatible', '3D controller', 'Display controller'))]
        if shutil.which('nvidia-smi'):
            result['nvidia_gpu'] = command(['nvidia-smi', '--query-gpu=name,memory.total,driver_version',
                                            '--format=csv,noheader,nounits'])
        result['power'] = {str(p): read(p) for pattern in ('*/online', '*/status')
                           for p in Path('/sys/class/power_supply').glob(pattern)}
        result['cpu_governor'] = read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')
        result['energy_preference'] = read('/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference')
        result['platform_profile'] = read('/sys/firmware/acpi/platform_profile')
    elif platform.system() == 'Darwin':
        result['os_release'] = command(['sw_vers'])
        result['cpu'] = {key: command(['sysctl', '-n', key]) for key in
                         ('machdep.cpu.brand_string', 'hw.model', 'hw.physicalcpu', 'hw.logicalcpu', 'hw.memsize')}
        profiler = command(['system_profiler', 'SPHardwareDataType', 'SPNVMeDataType',
                            'SPDisplaysDataType', '-json'], structured=True) or {}
        allowed = {'_name', '_items', 'machine_name', 'machine_model', 'model_number',
                   'chip_type', 'number_processors', 'physical_memory', 'device_model',
                   'link_width', 'link_speed', 'size', 'size_in_bytes', 'bsd_name',
                   'spsata_medium_type', 'spnvme_trim_support', 'spdisplays_cores',
                   'sppci_model', 'spdisplays_vendor', 'spdisplays_metal', 'spdisplays_vram_shared',
                   'spdisplays_ndrvs', 'spdisplays_device-id', 'spdisplays_total_number_of_cores',
                   'sppci_cores', 'sppci_device_type'}
        result['hardware'] = select_fields(profiler.get('SPHardwareDataType', []), allowed)
        result['storage'] = select_fields(profiler.get('SPNVMeDataType', []), allowed)
        result['graphics'] = select_fields(profiler.get('SPDisplaysDataType', []), allowed)
        disk_fields = {'DeviceIdentifier', 'DeviceNode', 'MediaName', 'VolumeName',
                       'FilesystemName', 'FilesystemType', 'FileVault', 'Encrypted',
                       'DeviceBlockSize', 'Size', 'TotalSize', 'APFSContainerSize',
                       'APFSContainerFree', 'DiskSize', 'Writable', 'Internal',
                       'SolidState', 'BusProtocol', 'IOKitSize', 'SMARTStatus', 'MediaType'}
        device = mac_device(command(['df', '-P', str(target)]))
        for key, name in (('filesystem', device or '/System/Volumes/Data'), ('physical_disk', 'disk0')):
            disk = command(['diskutil', 'info', '-plist', name], plist=True)
            result[key] = select_fields(disk or {}, disk_fields)
        result['power'] = command(['pmset', '-g', 'batt'])
        result['power_settings'] = command(['pmset', '-g', 'custom'])
    result['collection_errors'] = errors
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', nargs='?', default='.')
    args = parser.parse_args()
    print(json.dumps(collect(args.target), indent=2))
