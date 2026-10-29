"""Summarize the scoped APFS tuning experiment without conflating hardware runs."""
import argparse
from datetime import datetime
import html
import json
from pathlib import Path
import re
import statistics


def cpu_seconds(value):
    days = 0
    if '-' in value:
        day, value = value.split('-', 1)
        days = int(day)
    parts = [float(p) for p in value.split(':')]
    return days * 86400 + sum(p * 60**i for i, p in enumerate(reversed(parts)))


def process_cpu_totals(text):
    totals = {}
    for line in text.splitlines()[1:]:
        columns = line.split(None, 5)
        if len(columns) != 6:
            continue
        name = Path(columns[5]).name
        if name in ('fseventsd', 'mds', 'mds_stores', 'mdworker', 'mdworker_shared'):
            totals[name] = totals.get(name, 0) + cpu_seconds(columns[2])
    return totals


def event_history_files(text):
    files = {}
    for line in text.splitlines():
        name, size, modified = line.rsplit(' ', 2)
        name = Path(name).name
        if re.fullmatch(r'[0-9a-fA-F]{16}', name):
            files[name] = (int(size), int(modified))
    return files


def vm_counters(text):
    counters = {}
    page_size = re.search(r'page size of (\d+) bytes', text)
    if page_size:
        counters['page_size'] = int(page_size[1])
    for name in ('Swapins', 'Swapouts', 'Pageouts'):
        match = re.search(r'^' + name + r':\s+(\d+)\.', text, re.MULTILINE)
        if match:
            counters[name] = int(match[1])
    return counters


def summarize(runs):
    summaries = {}
    for label, run in runs.items():
        if run['status'] != 'complete':
            raise ValueError(f'Incomplete run: {label}')
        groups = {}
        for sample in run['samples']:
            groups.setdefault(str(sample['workers']), []).append(sample)
        summaries[label] = {}
        for workers, samples in groups.items():
            totals = [s['total_seconds'] for s in samples]
            summaries[label][workers] = {
                'samples': len(samples), 'median_seconds': statistics.median(totals),
                'min_seconds': min(totals), 'max_seconds': max(totals),
                'stage_medians': {stage: statistics.median(s[stage]['batch_seconds'] for s in samples)
                                  for stage in ('checkout', 'install', 'delete')}}
    for groups in summaries.values():
        for workers, row in groups.items():
            row['speedup_vs_A'] = summaries['A'][workers]['median_seconds'] / row['median_seconds']
    return summaries


def build(evidence, output):
    evidence, output = Path(evidence), Path(output)
    state = json.loads((evidence / 'experiment.json').read_text())
    runs = {c['label']: json.loads((evidence / (c['label'] + '-results') / 'results.json').read_text())
            for c in state['conditions'] if c.get('status') == 'complete'}
    summaries = summarize(runs)
    result = {'experiment': state, 'summaries': summaries,
              'limitations': ['One sequential block per condition, not randomized crossover; repeated batches are not independent repetitions of a setting change.',
                              'Surfshark antivirus was present but recorded near-zero cumulative CPU during scored intervals; the busy diagnostic snapshot came from an earlier attempt. Blocking or kernel overhead was not measured.',
                              'Spotify used roughly one CPU core during much of the experiment. Active swap-out page volume increased substantially between conditions.',
                              'Warm cache; scripts disabled; offline timed installs; no fsync.',
                              'no_log requests persistent-history suppression; live event processing continues.',
                              'Daemon counters cover the whole machine, with no idle baseline or per-volume attribution; high CPU alone does not establish a workload bottleneck.',
                              'CPU deltas can undercount restarted processes. Raw snapshots include preparation; reported scored intervals exclude setup, warmups and the first batch.',
                              'Spotlight enabled/disabled status was checked, but indexing of representative benchmark files was not verified.',
                              'No build or HMR compatibility validation in this experiment.']}
    probe = evidence / 'no-log-verification.json'
    if probe.exists():
        result['no_log_verification'] = json.loads(probe.read_text())
        result['limitations'].append('One short metadata-only history verification ran during condition D; all samples are retained.')
    verification = evidence / 'cleanup-verification.json'
    if verification.exists():
        result['cleanup_verification'] = json.loads(verification.read_text())
    # Raw process lists and long log-file inventories remain in the evidence files.
    compact_state = {k: v for k, v in state.items() if k != 'resources_before'}
    raw_fields = {'resources_before', 'resources_after', 'event_files_before', 'event_files_after'}
    compact_state['conditions'] = [{k: v for k, v in c.items() if k not in raw_fields}
                                   for c in state['conditions']]
    result['experiment'] = compact_state
    result['raw_evidence_directory'] = str(evidence)
    result['run_metadata'] = {label: run.get('metadata', {}) for label, run in runs.items()}
    result['scored_interval_daemon_cpu'] = {}
    result['scored_interval_memory'] = {}
    result['event_history_observations'] = {}
    for condition in state['conditions']:
        if condition.get('status') == 'complete':
            before = event_history_files(condition.get('event_files_before', ''))
            after = event_history_files(condition.get('event_files_after', ''))
            result['event_history_observations'][condition['label']] = {
                'files_before': len(before), 'files_after': len(after),
                'files_new_or_changed': sum(before.get(k) != v for k, v in after.items()),
                'bytes_before': sum(v[0] for v in before.values()),
                'bytes_after': sum(v[0] for v in after.values())}
    for label in summaries:
        records = [json.loads(line) for line in (evidence / f'{label}-resources.jsonl').read_text().splitlines()]
        records = [r for r in records if r['samples_completed'] > 0]
        if len(records) > 1:
            first, last = records[0], records[-1]
            before, after = process_cpu_totals(first['processes']), process_cpu_totals(last['processes'])
            elapsed = (datetime.fromisoformat(last['utc']) - datetime.fromisoformat(first['utc'])).total_seconds()
            result['scored_interval_daemon_cpu'][label] = {
                'covered_samples': last['samples_completed'] - first['samples_completed'],
                'wall_seconds': elapsed,
                'cpu_seconds_delta': {k: after[k] - before[k] for k in before.keys() & after.keys()}}
            before_vm = vm_counters(first.get('vm_stat', ''))
            after_vm = vm_counters(last.get('vm_stat', ''))
            result['scored_interval_memory'][label] = {
                'swap_start': first.get('swap', ''), 'swap_end': last.get('swap', ''),
                'page_size': before_vm.get('page_size'),
                'counter_deltas': {k: after_vm[k] - before_vm[k]
                                   for k in ('Swapins', 'Swapouts', 'Pageouts')
                                   if k in before_vm and k in after_vm}}
    output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    names = {'A': 'Spotlight on / event log on', 'B': 'Spotlight off / event log on',
             'C': 'Spotlight on / no_log', 'D': 'Spotlight off / no_log'}
    colors = {'A': '#8599b3', 'B': '#52c9ae', 'C': '#d1a5ff', 'D': '#ffc56e'}
    rows, bars = [], []
    max_value = max(r['median_seconds'] for g in summaries.values() for r in g.values())
    y = 30
    for workers in ('1', '2', '3', '4'):
        bars.append(f'<text x="0" y="{y}" fill="#c3d0dc">{workers} worker(s)</text>')
        y += 12
        for label in ('A', 'B', 'C', 'D'):
            if label not in summaries or workers not in summaries[label]:
                continue
            row = summaries[label][workers]
            value = row['median_seconds']
            bars.append(f'<text x="8" y="{y+15}" fill="{colors[label]}">{label}</text>'
                        f'<rect x="30" y="{y}" width="{430*value/max_value:.1f}" height="20" rx="3" fill="{colors[label]}"/>'
                        f'<text x="{40+430*value/max_value:.1f}" y="{y+15}" fill="#eef4fa">{value:.2f}s</text>')
            y += 27
            rows.append(f'<tr><td>{label}</td><td>{workers}</td><td>{value:.3f}</td>'
                        f'<td>{row["min_seconds"]:.2f}–{row["max_seconds"]:.2f}</td>'
                        f'<td>{row["speedup_vs_A"]:.2f}×</td><td>{row["samples"]}</td>'
                        f'<td>{row["stage_medians"]["checkout"]:.3f}</td>'
                        f'<td>{row["stage_medians"]["install"]:.3f}</td>'
                        f'<td>{row["stage_medians"]["delete"]:.3f}</td></tr>')
        y += 20
    legend = ''.join(f'<p style="color:{colors[k]}"><b>{k}</b> · {v}</p>' for k, v in names.items())
    cpu_rows = []
    for label, interval in result['scored_interval_daemon_cpu'].items():
        seconds = interval['cpu_seconds_delta'].get('fseventsd')
        if seconds is not None:
            average = 100 * seconds / interval['wall_seconds']
            cpu_rows.append(f'<tr><td>{label}</td><td>{seconds:.1f}</td><td>{average:.1f}%</td>'
                            f'<td>{interval["covered_samples"]}</td></tr>')
    cpu_table = ('<h2>FSEvents daemon CPU</h2><table><tr><th>Trial</th><th>CPU seconds</th>'
                 '<th>Average CPU, one core = 100%</th><th>Covered batches</th></tr>' + ''.join(cpu_rows) +
                 '</table><p>Intervals run from the first scored snapshot to the last. Setup, warmups and the first batch are excluded. Small gaps between batches are included.</p>')
    history_rows = ''.join(f'<tr><td>{label}</td><td>{observation["files_new_or_changed"]:,}</td>'
                           f'<td>{(observation["bytes_after"]-observation["bytes_before"])/1024**2:.2f}</td></tr>'
                           for label, observation in result['event_history_observations'].items())
    history_table = ('<h2>Persistent event-history writes</h2><table><tr><th>Trial</th>'
                     '<th>History files new or changed</th><th>Net logical size change, MiB</th></tr>' +
                     history_rows + '</table><p>Observations include preparation and warmups. Existing history files remain when no_log is added. File sizes are not a measurement of physical SSD allocation.</p>')
    memory_rows = ''.join(f'<tr><td>{label}</td><td>{m["counter_deltas"].get("Swapins", "?"):,}</td>'
                          f'<td>{m["counter_deltas"].get("Swapouts", "?"):,}</td>'
                          f'<td>{html.escape(m["swap_end"])}</td></tr>'
                          for label, m in result['scored_interval_memory'].items()
                          if 'Swapins' in m['counter_deltas'] and 'Swapouts' in m['counter_deltas'])
    memory_table = ('<h2>Memory pressure during scored intervals</h2><table><tr><th>Trial</th>'
                    '<th>Swap-in pages</th><th>Swap-out pages</th><th>Swap at interval end</th></tr>' +
                    memory_rows + '</table><p>These are VM counter deltas, not physical disk-byte measurements. Active swapping and desktop applications can affect the filesystem timings.</p>')
    limitations = ''.join('<li>' + html.escape(v) + '</li>' for v in result['limitations'])
    cleanup = ('Temporary volume deleted.' if state.get('volume_deleted') else 'Temporary-volume cleanup not verified.')
    interpretation = ''
    if set(summaries) == {'A', 'B', 'C', 'D'}:
        four_change = 100 * (summaries['D']['4']['median_seconds'] / summaries['A']['4']['median_seconds'] - 1)
        one_change = 100 * (summaries['D']['1']['median_seconds'] / summaries['A']['1']['median_seconds'] - 1)
        b_four = sorted((s for s in runs['B']['samples'] if s['workers'] == 4), key=lambda s: s['round'])
        early = statistics.mean(s['total_seconds'] for s in b_four[:len(b_four)//2])
        late = statistics.mean(s['total_seconds'] for s in b_four[len(b_four)//2:])
        interpretation = (f'<h2>Observed result and scrutiny</h2><p>Both-off versus baseline: '
                          f'four-worker median {four_change:+.1f}%; one-worker median {one_change:+.1f}%. '
                          'These are descriptive differences, not established causal effects. '
                          'A benefit at one concurrency level does not require a benefit at every level.</p>'
                          f'<p>Within condition B alone, the first half of four-worker batches averaged {early:.2f}s '
                          f'and the second half {late:.2f}s ({100*(late/early-1):+.1f}%), without a setting change. '
                          'The fixed condition order cannot separate treatment effects from changing machine state.</p><p>'
                          'Both no_log conditions had zero new or changed persistent-history files, '
                          'while fseventsd continued consuming more than one CPU core on average. '
                          'This verifies history suppression; it does not show that live event handling stopped. '
                          'A quiet-machine, repeated crossover is needed to estimate performance effects.</p>')
    machine = state.get('inventory_before', {})
    cpu = machine.get('cpu', {})
    metadata = runs.get('A', {}).get('metadata', {})
    details = html.escape(' | '.join(str(v) for v in (
        cpu.get('machdep.cpu.brand_string', 'M4 Pro'),
        f"{cpu.get('hw.physicalcpu', '?')} physical cores",
        (f"{int(cpu['hw.memsize'])/1024**3:.0f} GiB RAM" if cpu.get('hw.memsize') else 'RAM size unavailable'),
        f"pnpm {metadata.get('pnpm_version', '?')}",
        f"Node on PATH {metadata.get('node_version', '?')}",
        machine.get('os_release', '').replace('\n', ' | '))))
    page = f'''<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>M4 Pro APFS tuning experiment</title><style>
body{{font:15px system-ui;background:#101820;color:#eef4fa;margin:0;padding:28px;max-width:1050px}}
h1{{font-size:26px}}p,li{{line-height:1.5}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{text-align:right;padding:9px;border-bottom:1px solid #354553}}th{{color:#b0c3d4}}
.note{{padding:16px;background:#1d2d3a;border-radius:8px}}svg{{max-width:650px;width:100%;height:auto}}a{{color:#72c9ff}}
</style><h1>M4 Pro: Spotlight and FSEvents</h1><p>Eventpop worktree checkout → offline pnpm install → deletion. Lower time is better.</p>
<p>{details}</p><p>Commit: <code>{html.escape(metadata.get('commit', 'unknown'))}</code></p>
<div class="note">{cleanup} Free space before: {state['free_before']/1024**3:.2f} GiB; after: {state.get('free_after',0)/1024**3:.2f} GiB.
<br>All conditions use the same encrypted, quota-limited native APFS volume and pinned tool versions.
<br>Execution order: A → B → D → C. Worker counts are shuffled within each round.</div>
<p>Free-space counters include unrelated desktop activity and changing swap allocation; they do not measure bytes reclaimed by volume deletion.</p>
{interpretation}
{legend}<svg viewBox="0 0 580 {y+10}" role="img" aria-label="Median batch time by worker count and condition">{''.join(bars)}</svg>
<div style="overflow:auto"><table><tr><th>Trial</th><th>Workers</th><th>Median s</th><th>Range s</th><th>A / trial</th><th>Samples</th><th>Checkout s</th><th>Install s</th><th>Delete s</th></tr>{''.join(rows)}</table></div>
{cpu_table}
{history_table}
{memory_table}
<h2>Interpretation limits</h2><ul>{limitations}</ul><p>The three stage medians are independent and need not sum to the median total.</p>
<p>Raw results and process snapshots are retained alongside this report. The original cross-machine benchmark is a separate experiment.</p></html>'''
    output.write_text(page)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence')
    parser.add_argument('--output', default='mac-tuning-report.html')
    args = parser.parse_args()
    build(args.evidence, args.output)
