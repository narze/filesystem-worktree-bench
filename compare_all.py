#!/usr/bin/env python3
"""Compare matching runs on the desktop, M4 Pro, ThinkPad, Debian host and M1 Pro."""
import argparse
from html import escape
import json
from pathlib import Path

from compare import comparison


def combined(desktop, mac, thinkpad, debianarze=None, m1_pro=None):
    pairs = {'mac': comparison(desktop, mac), 'thinkpad': comparison(desktop, thinkpad)}
    if debianarze is not None:
        pairs['debianarze'] = comparison(desktop, debianarze)
    if m1_pro is not None:
        pairs['m1_pro'] = comparison(desktop, m1_pro)
    rows = []
    for index, first in enumerate(pairs['mac']):
        row = {'workers': first['workers'], 'desktop': first['linux']}
        row.update({host: data[index]['mac'] for host, data in pairs.items()})
        rows.append(row)
    return rows


def filesystem(result):
    try:
        return json.loads(result['metadata']['mount'])['filesystems'][0]['fstype']
    except (KeyError, TypeError, ValueError):
        return 'apfs' if result['metadata']['platform'].startswith(('Darwin', 'macOS')) else 'unknown'


def render(results, rows):
    names = {'desktop': 'Ryzen desktop', 'mac': 'MacBook M4 Pro',
             'thinkpad': 'ThinkPad i5-7300U', 'debianarze': 'debianarze i5-7500T',
             'm1_pro': 'MacBook M1 Pro'}
    labels = {host: f'{names[host]} · {filesystem(result)}' for host, result in results.items()}
    largest = max(row[host]['total'] for row in rows for host in results)
    bars = ''
    table = ''
    for row in rows:
        bars += f'<h3>{row["workers"]} worker(s)</h3>'
        for host in results:
            value = row[host]
            bars += f'''<div class="barrow"><span class="label">{escape(labels[host])}</span>
            <div class="track"><div class="bar {host}" style="width:{value['total']/largest*100:.2f}%"></div>
            <span class="value">{value['total']:.3f} s</span></div>
            <span class="rate">{value['throughput']:.3f}/s</span></div>'''
            table += (f'<tr><td>{row["workers"]}</td><td>{escape(names[host])}</td>'
                      + ''.join(f'<td>{value[k]:.3f}</td>' for k in ('checkout', 'install', 'delete', 'total'))
                      + f'<td>{value["min"]:.3f} - {value["max"]:.3f}</td></tr>')
    failure_notes = ''
    for host, result in results.items():
        count = len(result.get('discarded_attempts', []))
        if count:
            failure_notes += (f'<p>{escape(names[host])}: {count} failed attempt(s) recorded separately. '
                              'The run resumed; timings include only successful batches.</p>')
    import_note = ('Automatic package imports use clones on Btrfs/APFS and hard links on ext4.'
                   if 'debianarze' in results else '')
    return f'''<!doctype html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><style>
    body {{margin:0;font-family:var(--font-sans,system-ui);color:var(--foreground,#ddd)}}
    h2 {{margin:0 0 8px;font-size:20px}} h3 {{font-size:13px;margin:18px 0 7px}}
    p {{font-size:12px;line-height:1.5;color:var(--muted-foreground,#999)}}
    .barrow {{display:grid;grid-template-columns:155px 1fr 63px;gap:8px;align-items:center;margin:5px 0}}
    .label,.rate {{font-size:10px}} .rate {{text-align:right}}
    .track {{height:27px;position:relative;background:var(--secondary,#222);border-radius:4px;overflow:hidden}}
    .bar {{height:100%;opacity:.5}} .desktop {{background:var(--chart-1,#659bff)}}
    .mac {{background:var(--chart-2,#62caaa)}} .thinkpad {{background:var(--chart-3,#d9b463)}}
    .debianarze {{background:var(--chart-4,#b98ada)}}
    .m1_pro {{background:var(--chart-5,#e78d79)}}
    .value {{position:absolute;left:6px;top:6px;font-size:12px}}
    .scroll {{overflow:auto;margin-top:20px}} table {{width:100%;border-collapse:collapse;font-size:10px;font-variant-numeric:tabular-nums}}
    td,th {{text-align:right;padding:7px 4px;border-bottom:1px solid var(--border,#333);white-space:nowrap}}
    td:nth-child(2),th:nth-child(2) {{text-align:left}} th {{font-weight:500;color:var(--muted-foreground,#999)}}
    @media(max-width:450px) {{.barrow {{grid-template-columns:118px 1fr 52px;gap:5px}}}}
    </style></head><body><h2>Eventpop · matched development workload</h2>
    <p>Commit 0e0499f42444 · pnpm 11.18.0 · Node on PATH 24.22.1 · ten measured batches per worker count.
    Warm cache, offline installs, build scripts disabled, automatic package import mode.
    Bars: median batch time, lower is faster. Right: workflows per second.</p>
    {bars}<div class="scroll"><table><thead><tr><th>Workers</th><th>Machine</th>
    <th>Checkout</th><th>Install</th><th>Delete</th><th>Total</th><th>Total range</th></tr></thead>
    <tbody>{table}</tbody></table></div>
    <p>Times in seconds. Each batch does one workflow per worker with barriers between phases.
    Phase medians need not sum to the median total. Measures command completion without fsync.</p>
    {failure_notes}
    <p>This compares complete systems. CPUs, RAM, SSD/HDD hardware, filesystem settings,
    encryption, Git versions and background activity differ. Platform-specific optional dependencies also differ.
    {import_note}
    Both Linux Btrfs machines use zstd:3 and LUKS; the desktop uses noatime, the ThinkPad uses relatime.
    The M4 Pro uses APFS and FileVault. The Debian host uses ext4 on a rotational HDD.
    Full host settings are recorded alongside each raw result.</p>
    </body></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('desktop', type=Path)
    parser.add_argument('mac', type=Path)
    parser.add_argument('thinkpad', type=Path)
    parser.add_argument('--debianarze', type=Path)
    parser.add_argument('--m1-pro', type=Path)
    parser.add_argument('--output', type=Path, default=Path('comparison-all.html'))
    args = parser.parse_args()
    results = {host: json.loads(getattr(args, host).read_text())
               for host in ('desktop', 'mac', 'thinkpad', 'debianarze', 'm1_pro') if getattr(args, host) is not None}
    rows = combined(**results)
    args.output.write_text(render(results, rows))
    args.output.with_suffix('.json').write_text(json.dumps(rows, indent=2) + '\n')
    for row in rows:
        print(row['workers'], {host: round(row[host]['total'], 3) for host in results})
