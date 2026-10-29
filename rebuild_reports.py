"""Rebuild all retained reports and SHA-256-verified evidence bundles offline."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from publication import EVIDENCE_DIRS


def retained(paths):
    return sorted({p for p in paths if p.is_file() and not p.is_symlink()
                   and not p.name.startswith('._') and '__pycache__' not in p.parts})


def bundle(root, name, paths, metadata):
    paths = retained(paths)
    manifest_path = root / f'{name}-manifest.json'
    manifest = {**metadata, 'files': {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    archive_path = root / f'{name}.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths + [manifest_path]:
            # Fixed timestamps make repeated packaging independent of file mtimes.
            info = zipfile.ZipInfo(str(path.relative_to(root)), (2026, 10, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f'Invalid ZIP: {archive_path.name}')
        for path, digest in manifest['files'].items():
            if hashlib.sha256(archive.read(path)).hexdigest() != digest:
                raise ValueError(f'Archive checksum mismatch: {path}')
    print(f'{archive_path.name}: verified {len(paths)} files')


def rebuild(root):
    def run(*args):
        subprocess.run([sys.executable, *map(str, args)], cwd=root, check=True)
    machine_dirs = EVIDENCE_DIRS[:5]
    for directory in machine_dirs:
        run('report.py', f'{directory}/results.json')
    run('compare.py', 'desktop-results/results.json', 'mac-results/results.json')
    run('compare_all.py', 'desktop-results/results.json', 'mac-results/results.json',
        'thinkpad-results/results.json', '--debianarze', 'debianarze-results/results.json',
        '--m1-pro', 'm1-pro-results/results.json')
    run('benchmark_report.py')
    run('report_fs_experiment.py')
    run('mac_tuning_report.py', 'mac-tuning-results/main')
    run('combine_results.py')
    common = list(root.glob('*.py')) + [root / 'README.md', root / '.gitignore']
    common += list((root / '.github').rglob('*.yml'))
    if (root / 'publication-audit.json').exists():
        common.append(root / 'publication-audit.json')
    def evidence(directories):
        return [p for directory in directories for p in (root / directory).rglob('*')]
    machine_files = common + evidence(machine_dirs) + [root / name for name in (
        'benchmark-report.html', 'benchmark-report.json', 'comparison.html',
        'comparison.json', 'comparison-all.html', 'comparison-all.json', 'final-cleanup-verification.json')]
    bundle(root, 'benchmark-evidence', machine_files,
           {'successful_batches': 200, 'measured_workflows': 500, 'failed_measured_attempts': 1})
    paired_files = common + evidence(EVIDENCE_DIRS[5:7]) + [root / name for name in (
        'xfs-experiment-report.html', 'xfs-experiment-summary.json')]
    bundle(root, 'xfs-experiment-evidence', paired_files,
           {'successful_measured_batches': 120, 'excluded_sparse_image_pilot': True,
            'scope': 'Image-backed XFS and Btrfs over native Btrfs, plus native control; no VDO'})
    tuning_files = common + evidence(['mac-tuning-results']) + [root / name for name in (
        'mac-tuning-report.html', 'mac-tuning-report.json',
        'mac-tuning-no-log-verification.json', 'mac-tuning-runtime-diagnostic.txt')]
    bundle(root, 'mac-tuning-evidence', tuning_files,
           {'successful_measured_batches': 160, 'primary_evidence': 'mac-tuning-results/main',
            'excluded_attempts': ['attempt-a', 'attempt-b', 'top-level incomplete attempt']})
    all_files = common + machine_files + paired_files + tuning_files + [root / name for name in (
        'combined-benchmark-report.html', 'combined-results.json', 'combined-results.csv',
        'benchmark-evidence.zip', 'benchmark-evidence-manifest.json',
        'xfs-experiment-evidence.zip', 'xfs-experiment-evidence-manifest.json',
        'mac-tuning-evidence.zip', 'mac-tuning-evidence-manifest.json')]
    # Keep the established XFS manifest filename as a convenient alias.
    (root / 'xfs-experiment-manifest.json').write_bytes((root / 'xfs-experiment-evidence-manifest.json').read_bytes())
    all_files.append(root / 'xfs-experiment-manifest.json')
    bundle(root, 'combined-evidence', all_files,
           {'datasets_in_main_comparison': 8, 'successful_measured_batches': 320,
            'measured_workflows': 800, 'separate_tuning_batches': 160,
            'total_successful_measured_batches': 480})


if __name__ == '__main__':
    rebuild(Path(__file__).resolve().parent)
