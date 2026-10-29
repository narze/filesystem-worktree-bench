#!/usr/bin/env python3
"""Generate a self-contained HTML report from a completed bench.py run."""
import argparse
from html import escape
import json
from pathlib import Path
import statistics


def render(result):
    if result['status'] != 'complete' or not result['samples']:
        raise ValueError('A complete benchmark with samples is required')
    groups = []
    for workers in sorted({s['workers'] for s in result['samples']}):
        samples = [s for s in result['samples'] if s['workers'] == workers]
        total = [s['total_seconds'] for s in samples]
        groups.append({'workers': workers, 'count': len(samples),
                       'total': statistics.median(total), 'min': min(total), 'max': max(total),
                       'throughput': statistics.median(workers / t for t in total),
                       **{stage: statistics.median(s[stage]['batch_seconds'] for s in samples)
                          if stage in samples[0] else None
                          for stage in ('checkout', 'install', 'delete')}})
    max_time = max(g['total'] for g in groups)
    max_rate = max(g['throughput'] for g in groups)
    bars = ''
    rows = ''
    for g in groups:
        bars += f'''<div class="worker">{g['workers']} worker{'s' if g['workers'] != 1 else ''}</div>
        <div class="track"><div class="bar time" style="width:{g['total']/max_time*100:.2f}%"></div>
        <span>{g['total']:.3f} s / batch</span></div>
        <div class="track"><div class="bar rate" style="width:{g['throughput']/max_rate*100:.2f}%"></div>
        <span>{g['throughput']:.2f} workflows/s</span></div>'''
        phases = ''.join(f'<td>{g[stage]:.3f}</td>' if g[stage] is not None else '<td>skipped</td>'
                         for stage in ('checkout', 'install', 'delete'))
        rows += (f"<tr><td>{g['workers']}</td>{phases}<td>{g['total']:.3f}</td>"
                 f"<td>{g['min']:.3f} - {g['max']:.3f}</td></tr>")
    meta = result['metadata']
    commit = escape(meta['commit'][:12])
    return f'''<!doctype html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><style>
    body {{margin:0;font-family:var(--font-sans,system-ui);color:var(--foreground,#ddd)}}
    h2 {{font-size:20px;margin:0 0 8px}} p {{font-size:13px;color:var(--muted-foreground,#999);line-height:1.5}}
    .chart {{display:grid;grid-template-columns:70px 1fr 1fr;gap:12px 10px;align-items:center;margin:22px 0}}
    .label {{font-size:12px;color:var(--muted-foreground,#999)}} .worker {{font-size:12px}}
    .track {{height:38px;position:relative;background:var(--secondary,#20252a);border-radius:4px;overflow:hidden}}
    .bar {{height:100%;opacity:.4}} .time {{background:var(--chart-1,#69aaff)}}
    .rate {{background:var(--chart-2,#50cfaa)}} .track span {{position:absolute;left:8px;top:11px;font-size:12px}}
    .scroll {{overflow-x:auto}} table {{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums}}
    th,td {{text-align:right;padding:9px 5px;border-bottom:1px solid var(--border,#353535)}}
    th {{color:var(--muted-foreground,#999);font-weight:500}} th:first-child,td:first-child {{text-align:left}}
    </style></head><body>
    <h2>Eventpop · local filesystem baseline</h2>
    <p>Commit {commit} · {meta['runs']} measured batches per worker count · warm cache</p>
    <div class="chart"><div></div><div class="label">Median batch time · lower is faster</div>
    <div class="label">Median throughput · higher is faster</div>{bars}</div>
    <div class="scroll"><table><thead><tr><th>Workers</th><th>Checkout</th><th>Install</th><th>Delete</th>
    <th>Total</th><th>Total range</th></tr></thead><tbody>{rows}</tbody></table></div>
    <p>All times in seconds. Phase columns show medians; total is the median of each batch's sum.
    Each batch contains one workflow per worker, with stage barriers between checkout, install, and deletion.
    More workers means more work. Setup and Git metadata pruning are outside the timers.</p>
    <p>Offline pnpm installs · scripts disabled · import method: {escape(meta.get('import_method', 'auto'))}.
    Measures command completion without a storage flush. This run does not compare APFS.</p>
    </body></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    output = args.results.with_name('report.html')
    output.write_text(render(json.loads(args.results.read_text())))
    print(output.resolve())
