#!/usr/bin/env python3
"""Compare completed Linux and Mac runs of the same worktree workload."""
import argparse
from html import escape
import json
from pathlib import Path
import statistics


def comparison(linux, mac):
    fields = ('commit', 'node_version', 'pnpm_version', 'import_method',
              'install_scripts', 'cache', 'durability', 'lifecycle',
              'lockfile_sha256_normalized', 'workers', 'runs')
    for field in fields:
        if linux['metadata'][field] != mac['metadata'][field]:
            raise ValueError(f'Mismatched workload setting: {field}')
    for result in (linux, mac):
        if result['status'] != 'complete':
            raise ValueError('Both runs must be complete')
        expected = {(number, workers)
                    for number in range(1, result['metadata']['runs'] + 1)
                    for workers in result['metadata']['workers']}
        actual = [(sample.get('round'), sample['workers']) for sample in result['samples']]
        if len(actual) != len(expected) or set(actual) != expected:
            raise ValueError('Missing, duplicate or unexpected round/worker samples')
        if {s['workers'] for s in result['samples']} != set(result['metadata']['workers']):
            raise ValueError('Unexpected worker counts')
    rows = []
    for workers in sorted(linux['metadata']['workers']):
        row = {'workers': workers}
        for name, result in (('linux', linux), ('mac', mac)):
            samples = [s for s in result['samples'] if s['workers'] == workers]
            if len(samples) != result['metadata']['runs']:
                raise ValueError('Incomplete sample count')
            times = [s['total_seconds'] for s in samples]
            row[name] = {'total': statistics.median(times), 'min': min(times), 'max': max(times),
                         'throughput': statistics.median(workers / t for t in times),
                         **{stage: statistics.median(s[stage]['batch_seconds'] for s in samples)
                            for stage in ('checkout', 'install', 'delete')}}
        row['mac_over_linux'] = row['mac']['total'] / row['linux']['total']
        rows.append(row)
    return rows


def render(linux, rows, mac=None):
    max_time = max(row[host]['total'] for row in rows for host in ('linux', 'mac'))
    chart = ''
    details = ''
    for row in rows:
        chart += f'<div class="group">{row["workers"]} worker(s)</div>'
        for host, label in (('linux', 'Linux PC · Btrfs'), ('mac', 'M4 Pro · APFS')):
            data = row[host]
            chart += f'''<div class="barrow"><span class="label">{label}</span>
            <div class="track"><div class="bar {host}" style="width:{data['total']/max_time*100:.2f}%"></div>
            <span class="value">{data['total']:.3f} s</span></div>
            <span class="rate">{data['throughput']:.3f}/s</span></div>'''
            details += (f'<tr><td>{row["workers"]}</td><td>{label}</td>'
                        + ''.join(f'<td>{data[phase]:.3f}</td>' for phase in ('checkout', 'install', 'delete', 'total'))
                        + f'<td>{data["min"]:.3f} - {data["max"]:.3f}</td></tr>')
    commit = escape(linux['metadata']['commit'][:12])
    discarded = len((mac or {}).get('discarded_attempts', []))
    resume_note = (f'<p>Run reliability: {discarded} failed Mac checkout batch attempt(s) '
                   'are recorded separately and excluded from successful-batch timings. '
                   'The Mac run resumed after a Git worktree metadata read error; '
                   'all 40 successful batches are included.</p>' if discarded else '')
    return f'''<!doctype html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><style>
    body {{margin:0;font-family:var(--font-sans,system-ui);color:var(--foreground,#ddd)}}
    h2 {{margin:0 0 8px;font-size:20px}} p {{font-size:13px;line-height:1.5;color:var(--muted-foreground,#999)}}
    .group {{font-size:13px;margin:18px 0 6px;font-weight:600}}
    .barrow {{display:grid;grid-template-columns:125px 1fr 65px;gap:8px;align-items:center;margin:5px 0}}
    .label,.rate {{font-size:11px}} .rate {{text-align:right}}
    .track {{height:29px;position:relative;background:var(--secondary,#222);border-radius:4px;overflow:hidden}}
    .bar {{height:100%;opacity:.5}} .linux {{background:var(--chart-1,#659bff)}}
    .mac {{background:var(--chart-2,#62caaa)}} .value {{position:absolute;left:7px;top:7px;font-size:12px}}
    .scroll {{overflow:auto;margin-top:22px}} table {{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums}}
    td,th {{text-align:right;padding:8px 4px;border-bottom:1px solid var(--border,#333);white-space:nowrap}}
    td:nth-child(2),th:nth-child(2) {{text-align:left}} th {{font-weight:500;color:var(--muted-foreground,#999)}}
    </style></head><body><h2>Eventpop · Linux PC and MacBook M4 Pro</h2>
    <p>Same commit {commit}, Node 24.22.1 and pnpm 11.18.0. Ten measured batches per worker count.
    Offline installs, scripts disabled, warm caches. Bars show median batch time; lower is faster.
    Right column shows workflows per second.</p>
    {chart}<div class="scroll"><table><thead><tr><th>Workers</th><th>Machine</th>
    <th>Checkout</th><th>Install</th><th>Delete</th><th>Total</th><th>Total range</th></tr></thead>
    <tbody>{details}</tbody></table></div>
    <p>Phase times are medians in seconds. Each batch performs one workflow per worker,
    with barriers between phases. Total is the median of each batch's phase sum.</p>
    {resume_note}
    <p>This compares two complete systems, including CPUs, SSDs, operating systems,
    Git versions, platform-specific optional packages, encryption, free space and native package import behavior.
    It cannot isolate filesystem performance.
    Linux uses Btrfs with zstd:3 and LUKS; the Mac uses APFS with FileVault, AC power,
    and about 37 GiB free at the start. Indexing and background applications remain active.</p>
    </body></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('linux', type=Path)
    parser.add_argument('mac', type=Path)
    parser.add_argument('--output', type=Path, default=Path('comparison.html'))
    args = parser.parse_args()
    linux = json.loads(args.linux.read_text())
    mac = json.loads(args.mac.read_text())
    rows = comparison(linux, mac)
    args.output.write_text(render(linux, rows, mac))
    args.output.with_suffix('.json').write_text(json.dumps(rows, indent=2) + '\n')
    for row in rows:
        print(f'{row["workers"]} workers: Linux {row["linux"]["total"]:.3f}s, '
              f'Mac {row["mac"]["total"]:.3f}s; Mac/Linux {row["mac_over_linux"]:.2f}x')
