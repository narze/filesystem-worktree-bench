#!/usr/bin/env python3
"""One report and normalized dataset covering both benchmark studies."""
import csv
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import statistics

from benchmark_report import HOSTS, machine_summary
from compare import comparison
from report_fs_experiment import summarize as paired_summary


DATASETS = {
    'desktop': ('onarchy · Btrfs, original', 'machines', 'desktop', 'desktop-results'),
    'm4': ('MacBook M4 Pro · APFS', 'machines', 'm4', 'mac-results'),
    'thinkpad': ('ThinkPad L570 · Btrfs', 'machines', 'thinkpad', 'thinkpad-results'),
    'debian': ('debianarze · ext4 HDD', 'machines', 'debian', 'debianarze-results'),
    'm1': ('MacBook M1 Pro · APFS', 'machines', 'm1', 'm1-pro-results'),
    'native-btrfs': ('onarchy · Btrfs, fresh control', 'paired', 'desktop', 'xfs-results/native-btrfs'),
    'image-btrfs': ('onarchy · Btrfs image', 'paired', 'desktop', 'xfs-results/image-btrfs'),
    'image-xfs': ('onarchy · XFS image', 'paired', 'desktop', 'xfs-results/image-xfs'),
}


def combine(raw):
    if set(raw) != set(DATASETS):
        raise ValueError('All eight datasets are required')
    combined = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'datasets': {},
                'successful_batches': 0, 'measured_workflows': 0, 'failed_attempts': 0}
    for key, result in raw.items():
        comparison(raw['desktop'], result)
        label, study, machine, directory = DATASETS[key]
        count = len(result['samples'])
        failures = result.get('discarded_attempts', [])
        data = {'label': label, 'study': study, 'machine': machine, 'source': directory + '/results.json',
                'successful_batches': count, 'failed_attempts': failures,
                'metadata': result['metadata'], 'workers': {}}
        for workers in result['metadata']['workers']:
            samples = [s for s in result['samples'] if s['workers'] == workers]
            times = [s['total_seconds'] for s in samples]
            data['workers'][workers] = {'median': statistics.median(times), 'min': min(times), 'max': max(times),
                                       'throughput': statistics.median(workers / value for value in times),
                                       **{phase: statistics.median(s[phase]['batch_seconds'] for s in samples)
                                          for phase in ('checkout', 'install', 'delete')}}
        combined['datasets'][key] = data
        combined['successful_batches'] += count
        combined['measured_workflows'] += sum(s['workers'] for s in result['samples'])
        combined['failed_attempts'] += len(failures)
    combined['paired_onarchy'] = paired_summary({case: raw[case] for case in
                                                ('native-btrfs', 'image-btrfs', 'image-xfs')})
    return combined


def render(data, profiles, cleanups):
    e = lambda value: escape(str(value))
    matrix, phases = '', ''
    for key, item in data['datasets'].items():
        study = 'Original machine study' if item['study'] == 'machines' else 'Paired onarchy study'
        matrix += (f'<tr data-study="{item["study"]}"><th>{e(item["label"])}</th><td>{study}</td>'
                   + ''.join(f'<td>{item["workers"][w]["median"]:.3f}</td>' for w in (1, 2, 3, 4)) + '</tr>')
        for workers, s in item['workers'].items():
            phases += (f'<tr><th>{e(item["label"])}</th><td>{workers}</td>'
                       + ''.join(f'<td>{s[name]:.3f}</td>' for name in ('checkout', 'install', 'delete', 'median'))
                       + f'<td>{s["min"]:.3f}-{s["max"]:.3f}</td><td>{s["throughput"]:.4f}</td></tr>')
    pairs = ''.join(f'<tr><th>{r["workers"]}</th><td>{r["paired_xfs_over_btrfs"]:.3f}×</td>'
                    f'<td>{r["xfs_faster_pairs"]}/10</td></tr>' for r in data['paired_onarchy'])
    hardware = ''
    for key, label, directory in HOSTS:
        p = profiles[key];drive = p['drive']
        fields = {'Model': p['model'], 'CPU': p['cpu'] + ' / ' + p['cores'], 'Memory': p['memory'],
                  'Graphics': p['graphics'], 'Benchmark drive': f'{drive["model"]} / {drive["size_bytes"]/10**9:.1f} GB / {drive["interface"]} {drive["medium"]}',
                  'Original filesystem': p['filesystem'], 'Encryption': drive['encryption'],
                  'OS': p['os'], 'Kernel': p['kernel'], 'Power snapshot': p['power'],
                  'Mount options': p['mount_options'], 'Inventory captured UTC': p['inventory_utc']}
        hardware += (f'<details><summary>{e(label)} - {e(p["cpu"])} / {e(p["memory"])}</summary><dl>'
                     + ''.join(f'<dt>{e(name)}</dt><dd>{e(value)}</dd>' for name, value in fields.items())
                     + f'</dl><a href="{directory}/inventory.json">Filtered inventory JSON</a></details>')
    cleanup_rows = ''.join(f'<tr><th>{e(c["label"])}</th><td>Verified removed</td><td><a href="{e(c["receipt"])}">Receipt</a></td></tr>' for c in cleanups)
    plot = [{name: value for name, value in item.items() if name in ('label', 'study', 'workers')}
            for item in data['datasets'].values()]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Combined Eventpop benchmark results</title><style>
    :root{{color-scheme:light dark}}body{{margin:0;font:13px/1.5 var(--font-sans,system-ui);color:var(--foreground,CanvasText)}}main{{max-width:1200px;margin:auto}}
    h1{{font-size:24px;margin:0 0 8px}}h2{{font-size:18px;margin:23px 0 9px}}p{{margin:8px 0}}.muted,small{{color:var(--muted-foreground,GrayText);font-size:12px}}
    .kpis{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}.kpi{{flex:1;min-width:110px;padding:10px;background:var(--secondary,color-mix(in srgb,CanvasText 7%,Canvas));border-radius:var(--radius,8px)}}.kpi strong{{display:block;font-size:22px}}
    .controls{{display:flex;gap:6px;flex-wrap:wrap;margin:9px 0}}button{{font:inherit;border:1px solid var(--border,GrayText);border-radius:6px;padding:5px 9px;background:transparent;color:inherit;cursor:pointer}}button[aria-pressed=true]{{font-weight:700;background:var(--secondary,color-mix(in srgb,CanvasText 12%,Canvas))}}
    #bars{{min-height:135px}}.barrow{{display:grid;grid-template-columns:205px 1fr;gap:8px;align-items:center;min-height:38px;font-size:11px}}.track{{height:28px;position:relative;overflow:hidden;border-radius:4px;background:var(--secondary,color-mix(in srgb,CanvasText 7%,Canvas))}}.bar{{height:100%;opacity:.5}}.value{{position:absolute;left:7px;top:5px;font-size:12px}}
    .scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:11px;font-variant-numeric:tabular-nums}}td,th{{padding:7px 5px;border-bottom:1px solid var(--border,color-mix(in srgb,CanvasText 20%,Canvas));text-align:right;vertical-align:top}}th:first-child,td:nth-child(2){{text-align:left}}thead th{{font-weight:500;color:var(--muted-foreground,GrayText)}}
    details{{padding:9px 0;border-bottom:1px solid var(--border,color-mix(in srgb,CanvasText 20%,Canvas))}}summary{{cursor:pointer;font-weight:550}}dl{{display:grid;grid-template-columns:140px 1fr;gap:6px}}dt{{color:var(--muted-foreground,GrayText)}}dd{{margin:0;overflow-wrap:anywhere}}li{{margin:6px 0}}a{{color:var(--primary,LinkText)}}code{{font-size:11px;overflow-wrap:anywhere}}
    @media(max-width:500px){{.barrow{{grid-template-columns:140px 1fr}}dl{{grid-template-columns:1fr}}dt{{margin-top:5px}}h1{{font-size:21px}}}}
    </style></head><body><main><h1>Combined Eventpop benchmark results</h1>
    <p>Original five-machine study and the later paired onarchy XFS/Btrfs experiment, measured 28-29 October 2026.</p>
    <div class="kpis"><div class="kpi"><strong>5</strong><small>physical machines</small></div><div class="kpi"><strong>8</strong><small>separate datasets</small></div>
    <div class="kpi"><strong>{data['successful_batches']}</strong><small>successful measured batches</small></div><div class="kpi"><strong>{data['measured_workflows']}</strong><small>measured workflows</small></div></div>
    <p><strong>Keep the study labels when interpreting the results.</strong> The original machine runs compare complete systems. The XFS follow-up uses images over Btrfs and a fresh native control. The older and fresh onarchy Btrfs runs are separate datasets, not pooled samples.</p>
    <h2>All results</h2>
    <div class="controls"><button data-study="all" aria-pressed="true">All eight datasets</button><button data-study="machines" aria-pressed="false">Original five machines</button><button data-study="paired" aria-pressed="false">Paired onarchy study</button></div>
    <div class="controls">''' + ''.join(f'<button data-workers="{w}" aria-pressed="{str(w==4).lower()}">{w} worker(s)</button>' for w in (1,2,3,4)) + f'''</div>
    <div class="controls"><button data-metric="median" aria-pressed="true">Median batch seconds</button><button data-metric="throughput" aria-pressed="false">Median workflows/s</button></div>
    <div id="bars" aria-live="polite"></div><p class="muted">Lower batch time is faster; higher throughput is faster. Each N-worker batch completes N workflows. Cross-study placement is for reference and is not a filesystem-only ranking.</p>
    <div class="scroll"><table><thead><tr><th>Dataset</th><th>Study</th><th>1 worker (s)</th><th>2 workers (s)</th><th>3 workers (s)</th><th>4 workers (s)</th></tr></thead><tbody id="matrix">{matrix}</tbody></table></div>
    <details><summary>All phase medians, observed ranges and throughput</summary><div class="scroll"><table><thead><tr><th>Dataset</th><th>Workers</th><th>Checkout</th><th>Install</th><th>Delete</th><th>Total</th><th>Total range</th><th>Workflows/s</th></tr></thead><tbody>{phases}</tbody></table></div><p class="muted">Phase medians need not sum to the median total. Ranges are min-max among ten successful batches.</p></details>
    <h2>Within-study findings</h2><ul>
    <li>Across the original five machines, the Ryzen desktop was fastest at every worker count. The ThinkPad finished one workflow faster than either Mac, while both Macs were faster at three and four workers.</li>
    <li>In the paired image experiment, XFS was faster than the Btrfs image in all ten pairs at both three and four workers. The Btrfs image won all ten one-worker pairs. The two-worker difference was small.</li>
    <li>At four workers: XFS image 12.945 s, Btrfs image 22.236 s, and fresh native Btrfs control 16.334 s. The image-backed Btrfs penalty is a material reason not to treat this as a bare-metal XFS speedup.</li>
    </ul><details><summary>Paired XFS versus Btrfs-image ratios</summary><div class="scroll"><table><thead><tr><th>Workers</th><th>Median paired XFS/Btrfs time</th><th>XFS faster pairs</th></tr></thead><tbody>{pairs}</tbody></table></div><p class="muted">Each ratio compares matching round and worker count. Less than 1 means lower XFS time. Median paired ratios differ from ratios of overall medians.</p></details>
    <h2>Five-machine hardware reference</h2>{hardware}
    <p class="muted">Linux memory is OS-visible MemTotal; Mac memory is physical hw.memsize. Storage capacities use decimal GB. Inventories were collected after benchmarking; they are not continuous measurements. New filtered inventories and this report exclude serial numbers and hardware UUIDs.</p>
    <h2>Shared workload and study differences</h2>
    <details><summary>Reproduction and timing protocol</summary><ul>
    <li>Repository <code>eventpop/eventpop</code>, commit <code>0e0499f42444f1e4b2c0a6d11fc8043b42be295a</code>, 10,055 tracked files. pnpm 11.18.0, PATH Node 24.22.1. pnpm has its own packaged runtime; embedded Node v26.0.0 was verified for the identical Linux wrapper.</li>
    <li>All eight datasets have ten measured batches at each of 1, 2, 3 and 4 workers. The source commit, lockfile hash, tool versions and workload settings were validated before combining. Raw samples are preserved without pooling datasets.</li>
    <li>Per batch: parallel detached Git checkout, barrier, parallel offline frozen dependency installation with build scripts disabled, barrier, parallel tree deletion. The original batch implementation is reused in the follow-up.</li>
    <li>Per-machine monotonic clocks measure phase wall times. Total is the sum of phase wall times. Git metadata pruning, downloads, provisioning and SSH latency are outside the timers. Ruby dependencies, Rails/database setup and native install scripts are excluded.</li>
    <li>Original study: one warmup batch per worker count, then ten measured rounds with worker order seed 42, independently on each machine.</li>
    <li>Onarchy follow-up: one warmup plus one excluded preflight per worker count, then ten paired rounds. Worker order seed 42; filesystem-case order seed 73 at each worker count. Cases run sequentially.</li>
    <li>Both 16 GiB image files were verified fully preallocated, with outer NOCOW/NODATASUM on Btrfs. Guest Btrfs uses noatime, zstd:3, ssd and nodiscard. Guest XFS uses noatime/nodiscard with metadata CRC and reflinks enabled. Both remain layered over Btrfs/LUKS/NVMe; no existing partition was reformatted.</li>
    <li>Automatic package imports used clones on Btrfs/APFS/XFS and hard links on ext4. Platform-specific optional dependencies differ: 1,318 installed packages on Linux and 1,319 on macOS.</li>
    <li>Plain XFS was measured. VDO, the separate block-level compression/deduplication layer discussed in the video, was not tested. <a href="https://docs.kernel.org/admin-guide/device-mapper/vdo.html">Linux VDO documentation</a>.</li>
    </ul></details>
    <details><summary>Reliability, excluded data and interpretation limits</summary><ul>
    <li>{data['successful_batches']} successful measured batches and {data['failed_attempts']} failed measured attempt across the eight datasets. The M4 Pro's parallel Git commondir read failure was saved after 33 successful batches; seven missing samples were resumed using the original batch function. Failed-attempt latency is excluded from successful timings, and the error remains in the evidence.</li>
    <li>The first XFS pilot had unequal backing allocation because mkfs.xfs recreated a sparse file. It was stopped, cleaned up and excluded in full. Corrected allocation checks and pilot records are retained separately. Pilot and preflight timings are not part of the 320-batch summary.</li>
    <li>This is a warm, uncontrolled-cache workload with no fsync, durability test or cache eviction. No flush separates paired cases, so asynchronous writeback from earlier cases can overlap later cases.</li>
    <li>CPUs, RAM, SSD/HDD hardware, compression, encryption, mount options, free space, power states, OS/Git/Python versions and background activity differ. The cross-machine results cannot isolate APFS, Btrfs or ext4. The layered follow-up cannot establish bare-metal XFS performance.</li>
    <li>Debian's HDD run showed high I/O wait, active swapping and wide variation. A Mac snapshot showed fseventsd CPU activity. These are observed contexts, not causal proof. Ten samples per worker count support descriptive medians and ranges; small differences are not proof of statistical significance.</li>
    </ul></details>
    <h2>Cleanup and evidence</h2><p>Temporary stores, dataset copies, mounts and images from both studies are removed. Original Eventpop checkouts were preserved. Raw timings, inventories, logs, cleanup receipts and source remain available; xfsprogs/liburcu were installed for the XFS follow-up.</p>
    <details><summary>Verified cleanup receipts, including the excluded pilot</summary><div class="scroll"><table><thead><tr><th>Run</th><th>Status</th><th>Audit</th></tr></thead><tbody>{cleanup_rows}</tbody></table></div></details>
    <p><a href="combined-results.csv">All 320 successful batch samples (CSV)</a> · <a href="combined-results.json">Structured summary and provenance (JSON)</a> · <a href="combined-evidence.zip">Complete report and evidence bundle</a></p>
    <p>Separate follow-up: <a href="mac-tuning-report.html">M4 Pro Spotlight/FSEvents tuning, 160 scored batches and interpretation limits</a>. These sequential tuning trials are not pooled with the eight datasets above.</p>
    </main><script>
    const data={json.dumps(plot)};
    const colors=['var(--chart-1,#659bff)','var(--chart-2,#62caaa)','var(--chart-3,#d9b463)','var(--chart-4,#b98ada)','var(--chart-5,#e78d79)','var(--chart-1,#659bff)','var(--chart-6,#68b3bf)','var(--chart-3,#d9b463)'];
    let study='all',workers=4,metric='median';
    function draw(){{const visible=data.map((d,i)=>({{...d,index:i}})).filter(d=>study==='all'||d.study===study);const max=Math.max(...visible.map(d=>d.workers[workers][metric]));
      document.getElementById('bars').innerHTML=visible.map(d=>{{const s=d.workers[workers],v=s[metric];return `<div class="barrow"><span>${{d.label}}</span><div class="track" title="Observed batch range: ${{s.min.toFixed(3)}}-${{s.max.toFixed(3)}} seconds"><div class="bar" style="width:${{100*v/max}}%;background:${{colors[d.index]}}"></div><span class="value">${{v.toFixed(metric==='median'?3:4)}} ${{metric==='median'?'s':'workflows/s'}}</span></div></div>`}}).join('');
      document.querySelectorAll('button[data-study]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.study===study)));
      document.querySelectorAll('button[data-workers]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.workers===workers)));
      document.querySelectorAll('button[data-metric]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.metric===metric)));
      document.querySelectorAll('#matrix tr').forEach(r=>r.hidden=study!=='all'&&r.dataset.study!==study);
    }}
    document.querySelectorAll('button[data-study]').forEach(b=>b.onclick=()=>{{study=b.dataset.study;draw()}});
    document.querySelectorAll('button[data-workers]').forEach(b=>b.onclick=()=>{{workers=+b.dataset.workers;draw()}});
    document.querySelectorAll('button[data-metric]').forEach(b=>b.onclick=()=>{{metric=b.dataset.metric;draw()}});
    draw();</script></body></html>'''


def build(root):
    raw = {key: json.loads((root / definition[3] / 'results.json').read_text()) for key,definition in DATASETS.items()}
    data = combine(raw)
    profiles = {key:machine_summary(json.loads((root/directory/'inventory.json').read_text()),raw[key])
                for key, _, directory in HOSTS}
    data['machines'] = profiles
    cleanups = []
    for key,label,directory in HOSTS:
        receipt = json.loads((root/directory/'cleanup.json').read_text())
        if receipt['exists_after'] is not False:raise ValueError('Original cleanup is not verified')
        cleanups.append({'label':label,'receipt':directory+'/cleanup.json'})
    for directory,label in (('xfs-results','Corrected XFS experiment'),('xfs-pilot-results','Excluded sparse-image pilot')):
        if json.loads((root/directory/'cleanup.json').read_text())['exists_after'] is not False:
            raise ValueError('Follow-up cleanup is not verified')
        cleanups.append({'label':label,'receipt':directory+'/cleanup.json'})
    data['cleanup_receipts'] = cleanups
    (root/'combined-results.json').write_text(json.dumps(data,indent=2)+'\n')
    with (root/'combined-results.csv').open('w',newline='') as handle:
        fields=['dataset','study','machine','round','workers','checkout_seconds','install_seconds','delete_seconds','total_seconds','workflows_per_second']
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for key,result in raw.items():
            for sample in result['samples']:
                writer.writerow({'dataset':key,'study':DATASETS[key][1],'machine':DATASETS[key][2],
                                 'round':sample['round'],'workers':sample['workers'],
                                 **{phase+'_seconds':sample[phase]['batch_seconds'] for phase in ('checkout','install','delete')},
                                 'total_seconds':sample['total_seconds'],'workflows_per_second':sample['workers']/sample['total_seconds']})
    (root/'combined-benchmark-report.html').write_text(render(data,profiles,cleanups))
    return data


if __name__=='__main__':
    data=build(Path(__file__).resolve().parent)
    print(f"Combined {len(data['datasets'])} datasets, {data['successful_batches']} batches, {data['measured_workflows']} workflows; {data['failed_attempts']} failed attempt kept separately.")
