#!/usr/bin/env python3
"""Report the paired onarchy XFS/Btrfs image experiment without bare-metal claims."""
from html import escape
import json
from pathlib import Path
import statistics

from compare import comparison

CASES = {'native-btrfs': 'Native Btrfs control', 'image-btrfs': 'Btrfs image · zstd:3',
         'image-xfs': 'XFS image · reflink'}


def summarize(results):
    base = results['native-btrfs']
    for result in results.values():comparison(base, result)
    rows = []
    for workers in base['metadata']['workers']:
        row = {'workers': workers}
        for case, result in results.items():
            samples = [s for s in result['samples'] if s['workers'] == workers]
            times = [s['total_seconds'] for s in samples]
            row[case] = {'median': statistics.median(times), 'min': min(times), 'max': max(times),
                         'throughput': statistics.median(workers / value for value in times),
                         **{phase: statistics.median(s[phase]['batch_seconds'] for s in samples)
                            for phase in ('checkout', 'install', 'delete')}}
        btrfs = {s['round']: s['total_seconds'] for s in results['image-btrfs']['samples'] if s['workers'] == workers}
        xfs = {s['round']: s['total_seconds'] for s in results['image-xfs']['samples'] if s['workers'] == workers}
        ratios = [xfs[number] / btrfs[number] for number in sorted(btrfs)]
        row['paired_xfs_over_btrfs'] = statistics.median(ratios)
        row['xfs_faster_pairs'] = sum(ratio < 1 for ratio in ratios)
        rows.append(row)
    return rows


def render(rows, session, cleanup):
    largest = max(row[case]['median'] for row in rows for case in CASES)
    bars, table, phases = '', '', ''
    for row in rows:
        bars += f'<h3>{row["workers"]} worker(s)</h3>'
        for index, (case, label) in enumerate(CASES.items(), 1):
            data = row[case]
            color = ['#659bff', '#62caaa', '#d9b463'][index-1]
            bars += f'''<div class="row"><span>{label}</span><div class="track"><div class="bar" style="width:{data['median']/largest*100:.2f}%;background:var(--chart-{index},{color})"></div><span class="value">{data['median']:.3f} s · {data['throughput']:.3f} workflows/s</span></div></div>'''
            phases += (f'<tr><th>{label}</th><td>{row["workers"]}</td>'
                       + ''.join(f'<td>{data[k]:.3f}</td>' for k in ('checkout', 'install', 'delete', 'median'))
                       + f'<td>{data["min"]:.3f}-{data["max"]:.3f}</td></tr>')
        ratio = row['paired_xfs_over_btrfs']
        table += (f'<tr><th>{row["workers"]}</th>'
                  + ''.join(f'<td>{row[case]["median"]:.3f}</td>' for case in CASES)
                  + f'<td>{ratio:.3f}×</td><td>{row["xfs_faster_pairs"]}/10</td></tr>')
    ratios = [row['paired_xfs_over_btrfs'] for row in rows]
    reliability = '; '.join(f'{CASES[case]}: {count}' for case,count in session.get('failed_batch_attempts', {}).items())
    versions = '; '.join(f'{name}: {version.splitlines()[0]}' for name,version in session['tool_versions'].items())
    finding = ('XFS had lower successful-batch latency than image-backed Btrfs at every worker count.'
               if all(r < 1 for r in ratios) else
               'XFS had higher successful-batch latency than image-backed Btrfs at every worker count.'
               if all(r > 1 for r in ratios) else
               'In the paired medians, XFS was faster at worker counts '
               + ', '.join(str(row['workers']) for row in rows if row['paired_xfs_over_btrfs'] < 1)
               + '; Btrfs was faster at '
               + ', '.join(str(row['workers']) for row in rows if row['paired_xfs_over_btrfs'] > 1) + '.')
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Onarchy XFS experiment</title><style>
    :root{{color-scheme:light dark}}body{{margin:0;font:13px/1.5 var(--font-sans,system-ui);color:var(--foreground,CanvasText)}}
    main{{max-width:1100px;margin:auto}}h1{{font-size:23px;margin:0 0 8px}}h2{{font-size:18px;margin-top:24px}}h3{{font-size:13px;margin:15px 0 6px}}
    .row{{display:grid;grid-template-columns:155px 1fr;align-items:center;gap:8px;margin:5px 0;font-size:11px}}
    .track{{position:relative;height:27px;background:var(--secondary,color-mix(in srgb,CanvasText 8%,Canvas));border-radius:4px;overflow:hidden}}
    .bar{{height:100%;opacity:.5}}.value{{position:absolute;left:7px;top:5px;font-size:12px}}
    table{{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums}}th,td{{text-align:right;padding:7px 5px;border-bottom:1px solid var(--border,GrayText)}}th:first-child{{text-align:left}}
    .scroll{{overflow:auto}}p,li{{margin:8px 0}}.muted{{color:var(--muted-foreground,GrayText);font-size:12px}}summary{{cursor:pointer}}details{{margin:14px 0}}a{{color:var(--primary,LinkText)}}
    </style></head><body><main><h1>Onarchy · XFS and Btrfs experiment</h1>
    <p>{finding}</p><p><strong>Scope: this is an exploratory image-backed comparison, not a bare-metal XFS ranking or a reproduction of XFS plus VDO.</strong></p>
    <p class="muted">Same Ryzen 7 5800X desktop, Samsung 960 EVO NVMe, OS and tools. Ten paired measured rounds, 1-4 workers, 120 successful batches total. Lower time is faster.</p>
    {bars}<div class="scroll"><table><thead><tr><th>Workers</th><th>Native Btrfs (s)</th><th>Btrfs image (s)</th><th>XFS image (s)</th><th>Median paired XFS/Btrfs</th><th>XFS faster pairs</th></tr></thead><tbody>{table}</tbody></table></div>
    <p class="muted">Paired ratio is the median of XFS time divided by Btrfs-image time in the same round and worker count. Less than 1 means faster XFS. Phase medians need not sum to the median total. Failed attempts, recorded separately and excluded from successful timings: {reliability}.</p>
    <details><summary>Phase times and observed ranges</summary><div class="scroll"><table><thead><tr><th>Case</th><th>Workers</th><th>Checkout</th><th>Install</th><th>Delete</th><th>Total</th><th>Total range</th></tr></thead><tbody>{phases}</tbody></table></div></details>
    <h2>Protocol and configuration</h2><ul>
    <li>Original Eventpop commit <code>0e0499f42444f1e4b2c0a6d11fc8043b42be295a</code>, pnpm 11.18.0, PATH Node 24.22.1. The original batch timing function is unchanged and verified by SHA-256.</li>
    <li>Each target gets its own Git copy and package store. One warmup plus one excluded preflight batch per worker count precedes measurements. All setup downloads and preflight samples are outside this table.</li>
    <li>Within each measured round, worker-count order uses seed 42. At each worker count, the three filesystem cases run sequentially in randomized order using seed 73. No simultaneous benchmark cases compete for disk access.</li>
    <li>Workload: parallel detached worktree creation, parallel offline frozen dependency installs with scripts disabled, then parallel deletion. Measures command completion with no fsync or cache eviction.</li>
    <li>Two 16 GiB preallocated regular image files on the same native Btrfs/LUKS/NVMe volume. Their outer backing files have NOCOW/NODATASUM, which also prevents outer compression. Both still use the host Btrfs allocation and storage stack.</li>
    <li>An earlier pilot was stopped after detecting that mkfs.xfs had recreated a sparse image. Its data is excluded. The corrected experiment restores and verifies full preallocation after formatting; the allocation evidence and excluded pilot records are preserved.</li>
    <li>Guest Btrfs: noatime, zstd:3, ssd, nodiscard, mkfs defaults. Guest XFS: noatime, nodiscard, metadata CRC and reflink enabled, no VDO. Native Btrfs is a fresh control, not the older desktop timing run.</li>
    <li>Formatting tools: {escape(versions)}. Full mkfs output, mount options, schedule, host inventory, raw timings, and preflight records are retained in <code>xfs-results/</code>.</li>
    </ul><h2>Interpretation limits</h2><ul>
    <li>Matched images reduce the difference in layering, but loop-device caching, host Btrfs metadata, allocation, compression and guest filesystem defaults remain part of the result. Native Btrfs versus guest XFS is not a symmetric bare-metal comparison.</li>
    <li>No storage flush separates cases. Asynchronous writeback from an earlier case can overlap later cases; randomized ordering reduces bias but does not remove this source of variation.</li>
    <li>This tests plain XFS. Theo also discusses XFS with VDO, a separate block-level deduplication and compression layer. That configuration is not measured here. <a href="https://docs.kernel.org/admin-guide/device-mapper/vdo.html">Linux VDO documentation</a>.</li>
    <li>Automatic package import behavior and foreground/background load are included. Ten samples per worker count provide descriptive medians and ranges; small differences are not proof of statistical significance.</li>
    <li>A stronger filesystem-only conclusion requires a dedicated disposable device or raw partition, tested sequentially on the same hardware. No existing partition was reformatted for this experiment.</li>
    </ul><h2>Cleanup</h2><p>All temporary filesystems were unmounted, loop devices detached, and images and datasets removed. Allocated scratch footprint removed: {cleanup['approx_allocated_bytes_removed']/2**30:.2f} GiB. Installed xfsprogs/liburcu tools remain available.</p>
    <p><a href="xfs-results/cleanup.json">Cleanup receipt</a> · <a href="xfs-experiment-summary.json">Summary JSON</a> · <a href="xfs-experiment-evidence.zip">Evidence bundle</a></p>
    </main></body></html>'''


if __name__ == '__main__':
    root = Path(__file__).resolve().parent;folder = root / 'xfs-results'
    results = {case: json.loads((folder / case / 'results.json').read_text()) for case in CASES}
    session = json.loads((folder / 'session.json').read_text());cleanup = json.loads((folder / 'cleanup.json').read_text())
    session['failed_batch_attempts'] = {case:len(result.get('discarded_attempts',[])) for case,result in results.items()}
    if cleanup['exists_after'] is not False:raise ValueError('Cleanup is not verified')
    rows = summarize(results)
    (root / 'xfs-experiment-summary.json').write_text(json.dumps(rows, indent=2) + '\n')
    (root / 'xfs-experiment-report.html').write_text(render(rows, session, cleanup))
    for row in rows:
        print(row['workers'], {case: round(row[case]['median'],3) for case in CASES},
              'paired XFS/Btrfs', round(row['paired_xfs_over_btrfs'],3))
