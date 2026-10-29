#!/usr/bin/env python3
"""Build the standalone report from preserved timings, inventories and cleanup receipts."""
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

from compare import comparison


HOSTS = [('desktop', 'Ryzen desktop', 'desktop-results'),
         ('m4', 'MacBook M4 Pro', 'mac-results'),
         ('thinkpad', 'ThinkPad L570', 'thinkpad-results'),
         ('debian', 'Dell / debianarze', 'debianarze-results'),
         ('m1', 'MacBook M1 Pro', 'm1-pro-results')]


def drive_for_target(inventory):
    if inventory['system'] == 'Darwin':
        disk = inventory['physical_disk']
        return {'model': disk.get('MediaName', 'Apple SSD'),
                'size_bytes': disk.get('TotalSize', disk.get('Size', 0)),
                'interface': 'NVMe / ' + disk.get('BusProtocol', 'Apple Fabric'),
                'medium': 'SSD', 'encryption': 'FileVault / APFS'
                if inventory['filesystem'].get('FileVault') else 'FileVault not reported'}
    source = inventory['filesystem']['filesystems'][0]['source']
    name = source.split('[')[0].split('/')[-1]
    def ancestors(node, chain):
        chain = [*chain, node]
        if node['name'] == name:
            return chain
        for child in node.get('children', []):
            found = ancestors(child, chain)
            if found:
                return found
        return None
    for disk in inventory['block_devices']['blockdevices']:
        if disk['type'] != 'disk' or disk['name'].startswith(('zram', 'loop', 'ram')):
            continue
        chain = ancestors(disk, [])
        if chain:
            return {'model': (disk.get('model') or disk['name']).strip(),
                    'size_bytes': disk['size'], 'interface': disk.get('tran') or 'unknown',
                    'medium': 'HDD' if disk.get('rota') else 'SSD',
                    'encryption': 'LUKS / dm-crypt' if any(n['type'] == 'crypt' for n in chain)
                    else 'No block-encryption layer shown'}
    raise ValueError('Could not identify the benchmark physical disk')


def machine_summary(inv, result):
    drive = drive_for_target(inv)
    if inv['system'] == 'Darwin':
        hw = inv['hardware'][0]
        model = hw.get('machine_name', 'MacBook Pro') + ' / ' + hw['machine_model']
        cpu = inv['cpu']['machdep.cpu.brand_string']
        cores = inv['cpu']['hw.physicalcpu'] + ' CPU cores'
        ram = f"{int(inv['cpu']['hw.memsize']) / 2**30:g} GiB unified memory"
        gpu = inv['graphics'][0]
        graphics = gpu.get('sppci_model', gpu.get('_name', 'Apple GPU'))
        if gpu.get('sppci_cores'):
            graphics += f" / {gpu['sppci_cores']} GPU cores"
        os_version = next((line.split(':', 1)[1].strip() for line in inv['os_release'].splitlines()
                           if line.startswith('ProductVersion:')), 'unknown')
        os_name = 'macOS ' + os_version
        fs = inv['filesystem']['FilesystemType']
        options = 'Apple native mount settings'
        power = 'AC power' if 'AC Power' in inv.get('power', '') else inv.get('power', 'unknown')
    else:
        hw, fields = inv['hardware'], inv['cpu']
        model = hw.get('product_version') or hw.get('product_name') or 'Unknown model'
        if model in ('System Version', 'System Product Name'):
            model = 'Custom desktop / ' + (hw.get('board_name') or 'unknown board')
        elif hw.get('product_name') and hw['product_name'] != model:
            model += ' / ' + hw['product_name']
        cpu = fields['Model name']
        physical = int(fields['Core(s) per socket']) * int(fields['Socket(s)'])
        cores = f"{physical} cores / {fields['CPU(s)']} threads"
        ram = f"{inv['memory_bytes']['MemTotal'] / 2**30:.1f} GiB OS-visible"
        graphics = '; '.join(g.split('controller:', 1)[-1].strip() for g in inv['graphics'])
        if inv.get('nvidia_gpu'):
            gpu_fields = inv['nvidia_gpu'].splitlines()[0].split(',')
            if len(gpu_fields) >= 3:
                graphics += f' / {gpu_fields[1].strip()} MiB reported VRAM / driver {gpu_fields[2].strip()}'
        os_name = inv['os_release']['PRETTY_NAME']
        mount = inv['filesystem']['filesystems'][0]
        fs, options = mount['fstype'], mount['options']
        power = 'CPU governor: ' + (inv.get('cpu_governor') or 'unavailable')
        if any('/AC' in k and k.endswith('/online') and v == '1' for k, v in inv.get('power', {}).items()):
            power = 'AC power / ' + power
    return {'model': model, 'cpu': cpu, 'cores': cores, 'memory': ram, 'graphics': graphics,
            'os': os_name, 'kernel': inv['kernel'], 'filesystem': fs, 'mount_options': options,
            'power': power, 'drive': drive,
            'free_at_benchmark_gib': result['metadata']['free_bytes_before'] / 2**30,
            'inventory_utc': inv['captured_utc']}


def build(root):
    records, summaries, stats = {}, {}, {}
    for key, label, directory in HOSTS:
        folder = root / directory
        result, inv, cleanup = [json.loads((folder / f'{name}.json').read_text())
                                for name in ('results', 'inventory', 'cleanup')]
        if cleanup['exists_after'] is not False:
            raise ValueError(f'Cleanup not verified: {key}')
        records[key] = {'label': label, 'directory': directory, 'result': result,
                        'inventory': inv, 'cleanup': cleanup}
        summaries[key] = machine_summary(inv, result)
    base = records['desktop']['result']
    for key, record in records.items():
        comparison(base, record['result'])
        stats[key] = {}
        for workers in base['metadata']['workers']:
            samples = [s for s in record['result']['samples'] if s['workers'] == workers]
            total = [s['total_seconds'] for s in samples]
            stats[key][workers] = {'median': statistics.median(total), 'min': min(total), 'max': max(total),
                                   'throughput': statistics.median(workers / t for t in total),
                                   **{phase: statistics.median(s[phase]['batch_seconds'] for s in samples)
                                      for phase in ('checkout', 'install', 'delete')}}
    e = lambda value: escape(str(value))
    medians = ''.join('<tr><th>' + e(r['label']) + '</th>'
                      + ''.join(f'<td>{stats[k][w]["median"]:.3f}</td>' for w in (1, 2, 3, 4)) + '</tr>'
                      for k, r in records.items())
    hardware_rows, hardware_details, phase_rows, cleanup_rows = '', '', '', ''
    for key, record in records.items():
        s, d = summaries[key], summaries[key]['drive']
        disk = f"{d['model']} / {d['size_bytes']/10**9:.1f} GB / {d['interface']} {d['medium']}"
        hardware_rows += (f'<tr><th>{e(record["label"])}</th><td>{e(s["cpu"])}<small>{e(s["cores"])}</small></td>'
                          f'<td>{e(s["memory"])}</td><td>{e(disk)}</td><td>{e(s["filesystem"])}<small>{e(d["encryption"])}</small></td></tr>')
        details = {**{name: s[name] for name in ('model', 'graphics', 'os', 'kernel', 'power', 'mount_options')},
                   'free space at benchmark start': f'{s["free_at_benchmark_gib"]:.1f} GiB',
                   'Git': record['result']['metadata']['git_version'],
                   'Python': record['result']['metadata']['python_version'],
                   'hardware inventory captured (UTC)': s['inventory_utc']}
        hardware_details += ('<details><summary>' + e(record['label']) + ' - system details</summary><dl>'
                             + ''.join(f'<dt>{e(name)}</dt><dd>{e(value)}</dd>' for name, value in details.items())
                             + f'</dl><a href="{e(record["directory"])}/inventory.json">Full filtered inventory JSON</a></details>')
        for w in (1, 2, 3, 4):
            data = stats[key][w]
            phase_rows += (f'<tr><th>{e(record["label"])}</th><td>{w}</td>'
                           + ''.join(f'<td>{data[name]:.3f}</td>' for name in ('checkout', 'install', 'delete', 'median'))
                           + f'<td>{data["min"]:.3f}-{data["max"]:.3f}</td><td>{data["throughput"]:.4f}</td></tr>')
        c = record['cleanup']
        cleanup_rows += (f'<tr><th>{e(record["label"])}</th><td>{c["approx_allocated_bytes_removed"]/2**30:.2f} GiB</td>'
                         f'<td>Verified removed</td><td><a href="{e(record["directory"])}/cleanup.json">Receipt</a></td></tr>')
    removed = sum(r['cleanup']['approx_allocated_bytes_removed'] for r in records.values()) / 2**30
    started = min(r['result']['metadata']['started_utc'] for r in records.values())
    finished = max(r['result']['metadata']['finished_utc'] for r in records.values())
    def bangkok(value):
        return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Bangkok')).strftime('%d %b %Y %H:%M')
    plot_data = [{'label': r['label'], 'key': k, 'stats': stats[k]} for k, r in records.items()]
    report_data = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'machines': summaries,
                   'statistics': stats, 'cleanup_allocated_gib': removed,
                   'measurement_window_utc': [started, finished]}
    (root / 'benchmark-report.json').write_text(json.dumps(report_data, indent=2) + '\n')
    artifact_links = ' · '.join(f'<a href="{e(r["directory"])}/results.json">{e(r["label"])}</a>' for r in records.values())
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>Eventpop benchmark report</title>
    <style>
    :root{{color-scheme:light dark}} body{{margin:0;font:14px/1.5 var(--font-sans,system-ui);color:var(--foreground,CanvasText)}}
    main{{max-width:1100px;margin:auto}} h1{{font-size:25px;line-height:1.2;margin:0 0 8px}} h2{{font-size:18px;margin:25px 0 10px}}
    p{{margin:8px 0}} small,.muted{{display:block;color:var(--muted-foreground,GrayText);font-size:12px}}
    .kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}} .kpi{{flex:1;min-width:110px;background:var(--secondary,color-mix(in srgb,CanvasText 7%,Canvas));padding:12px;border-radius:var(--radius,8px)}}
    .kpi strong{{display:block;font-size:23px}} .scroll{{overflow:auto}} table{{border-collapse:collapse;width:100%;font-size:12px}}
    th,td{{padding:8px 7px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border,color-mix(in srgb,CanvasText 20%,Canvas))}}
    .numbers td{{text-align:right;font-variant-numeric:tabular-nums}} thead th{{font-weight:500;color:var(--muted-foreground,GrayText)}}
    .controls{{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}} button{{font:inherit;border:1px solid var(--border,GrayText);border-radius:6px;padding:5px 10px;cursor:pointer;background:transparent;color:inherit}}
    button[aria-pressed=true]{{background:var(--secondary,color-mix(in srgb,CanvasText 14%,Canvas));font-weight:700}}
    #bars{{height:210px}} .barrow{{display:grid;grid-template-columns:140px 1fr;gap:8px;align-items:center;height:39px;font-size:12px}}
    .track{{position:relative;height:28px;background:var(--secondary,color-mix(in srgb,CanvasText 7%,Canvas));border-radius:4px;overflow:hidden}}
    .bar{{height:100%;opacity:.48;transition:width .18s}} .value{{position:absolute;left:7px;top:5px;font-variant-numeric:tabular-nums}}
    details{{border-bottom:1px solid var(--border,color-mix(in srgb,CanvasText 20%,Canvas));padding:9px 0}} summary{{cursor:pointer;font-weight:550}}
    dl{{display:grid;grid-template-columns:180px 1fr;gap:6px;font-size:12px}} dt{{color:var(--muted-foreground,GrayText)}} dd{{margin:0;overflow-wrap:anywhere}}
    a{{color:var(--primary,LinkText)}} li{{margin:5px 0}} code{{font:12px var(--font-mono,monospace);overflow-wrap:anywhere}}
    @media(max-width:500px){{h1{{font-size:21px}}.barrow{{grid-template-columns:112px 1fr}} dl{{grid-template-columns:1fr}}dt{{margin-top:6px}}}}
    @media print{{.controls{{display:none}}details{{break-inside:avoid}} .bar{{print-color-adjust:exact}}}}
    </style></head><body><main>
    <h1>Eventpop benchmark report</h1>
    <p class="muted">Five systems, one fixed development workload. Measured {bangkok(started)} to {bangkok(finished)} (Asia/Bangkok).
    Hardware inventory and cleanup were collected afterward.</p>
    <div class="kpis"><div class="kpi"><strong>200</strong><small>successful measured batches</small></div>
    <div class="kpi"><strong>500</strong><small>completed measured workflows</small></div>
    <div class="kpi"><strong>{removed:.2f} GiB</strong><small>allocated scratch data removed</small></div></div>
    <h2>Results</h2>
    <p>The Ryzen desktop was fastest at every worker count. The ThinkPad finished one workflow faster than either Mac;
    both Macs finished batches of three and four workflows faster than the ThinkPad. Debian had the widest timing range.</p>
    <div class="controls" id="workers">''' + ''.join(f'<button type="button" data-workers="{w}" aria-pressed="{str(w==1).lower()}">{w} worker(s)</button>' for w in (1,2,3,4)) + f'''</div>
    <div class="controls" id="metrics"><button type="button" data-metric="median" aria-pressed="true">Batch seconds - lower is faster</button>
    <button type="button" data-metric="throughput" aria-pressed="false">Workflows/s - higher is faster</button></div>
    <div id="bars" aria-live="polite"></div>
    <div class="scroll"><table class="numbers"><thead><tr><th>Median batch time, seconds</th><th>1 worker</th><th>2 workers</th><th>3 workers</th><th>4 workers</th></tr></thead><tbody>{medians}</tbody></table></div>
    <p class="muted">N workers perform N complete workflows. Compare throughput as well as elapsed batch time.
    Ten successful batches per worker count; values are medians, not best runs.</p>
    <details><summary>Phase timings, observed ranges and throughput</summary><div class="scroll"><table class="numbers"><thead><tr>
    <th>Machine</th><th>Workers</th><th>Checkout</th><th>Install</th><th>Delete</th><th>Total</th><th>Total range</th><th>Workflows/s</th>
    </tr></thead><tbody>{phase_rows}</tbody></table></div><p class="muted">Phase columns are medians and need not sum to the median total. Ranges are minimum to maximum among ten successful batches.</p></details>
    <h2>Hardware and system details</h2>
    <div class="scroll"><table><thead><tr><th>Machine</th><th>CPU</th><th>Memory</th><th>Benchmark physical drive</th><th>Filesystem / encryption</th></tr></thead><tbody>{hardware_rows}</tbody></table></div>
    <p class="muted">Linux memory is OS-visible MemTotal; Mac memory is physical hw.memsize. Disk capacities use decimal GB.
    Serial numbers and hardware UUIDs are excluded from this report and the new filtered inventories.</p>
    {hardware_details}
    <h2>Method and limits</h2>
    <details><summary>Reproducible workload and timing</summary><ul>
    <li>Repository: eventpop/eventpop, commit <code>0e0499f42444f1e4b2c0a6d11fc8043b42be295a</code>, 10,055 tracked files.</li>
    <li>pnpm 11.18.0; Node on PATH 24.22.1. pnpm carries a separate packaged runtime; the Linux wrapper's embedded Node v26.0.0 was verified. PATH Node is not the pnpm runtime.</li>
    <li>One warmup batch for each worker count, followed by ten measured rounds. Worker-count order is shuffled each round with seed 42.</li>
    <li>Each batch runs parallel detached Git worktree creation, waits, runs parallel offline dependency installs, waits, then deletes all trees concurrently with Python shutil.rmtree. Git metadata pruning and setup are outside the timers.</li>
    <li>Timed installs use <code>--offline --frozen-lockfile --ignore-scripts</code> and a dedicated warm package store on the target filesystem. Internet downloads and SSH latency are outside the timers. App/database provisioning, Ruby dependencies and native build scripts are excluded.</li>
    <li>Automatic imports used clones on Btrfs/APFS and hard links on ext4. Linux installed 1,318 packages; macOS installed 1,319 due to platform-specific dependencies.</li>
    <li>Workers start each phase behind a barrier. Times use the machine's monotonic clock. Total is the sum of phase wall times. Throughput is workers divided by total, summarized per batch.</li>
    </ul></details>
    <details><summary>Interpretation and reliability</summary><ul>
    <li>This is a whole-system comparison. Different CPUs, RAM, drives, OS/Git/Python versions, power states, free space and background activity prevent attributing a result to APFS, Btrfs or ext4 alone.</li>
    <li>Caches were warm and uncontrolled. There was no cache eviction or fsync/storage flush; these are command-completion latencies, not durable-write latencies.</li>
    <li>Both Btrfs mounts use zstd:3 and LUKS, but the desktop uses noatime and the ThinkPad uses relatime. The Macs use APFS/FileVault. Debian uses ext4/relatime on a rotational HDD.</li>
    <li>Desktop applications and services remained active. Debian had swap in use before setup; a warmup snapshot showed 92% I/O wait, blocked tasks and active swap-out. This is observed context, not proof that any single factor caused its timings.</li>
    <li>The M4 Pro had one failed parallel Git checkout in round 9: a commondir metadata read error. Its first 33 successful samples were preserved and seven missing samples resumed using the original batch function. Failed-attempt timing is excluded; the original error is retained separately. All three new machines and the desktop had no failed measured batches.</li>
    <li>Ten samples describe these runs. Ranges are observed extremes, and small differences are not evidence of statistical significance. Inventory power/memory snapshots were collected after benchmarking; benchmark-start free space comes from each original result.</li>
    </ul></details>
    <h2>Cleanup and evidence</h2>
    <p>All five temporary benchmark datasets and dedicated stores are removed. Results, logs, hardware inventories and the runner are retained locally. Original Eventpop checkouts were not modified, and SSH sessions are closed.</p>
    <div class="scroll"><table><thead><tr><th>Machine</th><th>Approx. allocated files removed</th><th>Verification</th><th>Audit</th></tr></thead><tbody>{cleanup_rows}</tbody></table></div>
    <p class="muted">Removed footprint is du allocation, not a guaranteed change in physical free space: copy-on-write sharing, snapshots, compression and unrelated activity can affect the observed change. Receipts contain before/after filesystem counters and archived-result hashes.</p>
    <p>Raw timing JSON: {artifact_links}.</p>
    <p><a href="benchmark-evidence.zip">Download the report, evidence and runner bundle</a> · <a href="README.md">Runner instructions</a></p>
    </main><script>
    const data={json.dumps(plot_data)};
    const colors=['var(--chart-1,#659bff)','var(--chart-2,#62caaa)','var(--chart-3,#d9b463)','var(--chart-4,#b98ada)','var(--chart-5,#e78d79)'];
    let workers=1,metric='median';
    function draw(){{
      const max=Math.max(...data.map(d=>d.stats[workers][metric]));
      document.getElementById('bars').innerHTML=data.map((d,i)=>{{const s=d.stats[workers],v=s[metric];
        return `<div class="barrow"><span>${{d.label}}</span><div class="track" title="Observed batch range: ${{s.min.toFixed(3)}}-${{s.max.toFixed(3)}} seconds"><div class="bar" style="width:${{100*v/max}}%;background:${{colors[i]}}"></div><span class="value">${{v.toFixed(metric==='median'?3:4)}} ${{metric==='median'?'s':'workflows/s'}}</span></div></div>`;
      }}).join('');
      document.querySelectorAll('[data-workers]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.workers===workers)));
      document.querySelectorAll('[data-metric]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.metric===metric)));
    }}
    document.querySelectorAll('[data-workers]').forEach(b=>b.onclick=()=>{{workers=+b.dataset.workers;draw()}});
    document.querySelectorAll('[data-metric]').forEach(b=>b.onclick=()=>{{metric=b.dataset.metric;draw()}});
    draw();
    </script></body></html>'''


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    (root / 'benchmark-report.html').write_text(build(root))
    print(root / 'benchmark-report.html')
