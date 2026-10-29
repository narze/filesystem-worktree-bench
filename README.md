# Filesystem worktree benchmark

The completed M4 Pro Spotlight/FSEvents follow-up is `mac-tuning-report.html`,
with structured results in `mac-tuning-report.json` and raw evidence in
`mac-tuning-evidence.zip`. All four conditions completed 40 scored batches each.
Both-off had a 7% lower four-worker median and an 8% higher one-worker median.
These differences do not establish causal effects: conditions ran once each in
a fixed order, with active desktop apps and changing swap pressure. Four-worker
times drifted 9% within one unchanged condition. `no_log` suppressed persistent
history writes while the global daemon remained active. The antivirus process
was present but recorded near-zero CPU during scored intervals.
The temporary encrypted APFS volume was deleted; independent verification is in
`mac-tuning-results/main/cleanup-verification.json`. The startup and Data volume
Spotlight settings match the pre-test settings. Free-space differences include
unrelated activity and swap allocation, so they do not measure reclaimed space.
Earlier failed attempts are retained separately and excluded from the analysis.

```sh
python3 mac_tuning_report.py mac-tuning-results/main
```

Rebuild every report and evidence bundle with `python3 rebuild_reports.py`.
Run the checks with `python3 -m unittest -q`. Rebuilding uses retained evidence;
it does not run new benchmarks or change machine settings. The later global
Spotlight change is not a new performance measurement.

The publication snapshot omits private Git history, credentials, private/service
URLs, network addresses and inventory hostnames. Public documentation and package
links remain. `publication-audit.json` lists redacted files. Bundle manifests hash
the published files; original cleanup-receipt hashes refer to the original evidence.
To prepare a fresh sanitized copy, use `python3 publication.py /path/to/new-copy`,
then run `python3 rebuild_reports.py` from that copy before publication.

The unified entry point is `combined-benchmark-report.html`. It contains all
eight datasets from both studies: five original machine runs and the three
paired onarchy cases. The older and fresh native Btrfs runs remain separate.
`combined-results.csv` contains all 320 successful batch samples; the structured
summary and provenance are in `combined-results.json`. The report and all prior
evidence are packaged together in `combined-evidence.zip`.

```sh
python3 combine_results.py
```

The interactive report can show all datasets, the original machine study, or
the paired onarchy experiment. Cross-study placement is for reference; the
image-backed cases are not treated as bare-metal filesystem measurements.

The completed report is `benchmark-report.html`; `benchmark-report.json` contains
its structured hardware and summary data. `benchmark-evidence.zip` packages the
report, raw timings, inventories, cleanup receipts, logs, and runner source.

All temporary benchmark data on the five machines has been removed. The desktop
evidence was copied from its original run into `desktop-results/` before cleanup.
The other retained result directories are `mac-results/`, `thinkpad-results/`,
`debianarze-results/`, and `m1-pro-results/`. These small evidence files remain local.
The source repositories and package contents are excluded from the evidence bundle.

To rebuild the final report from the retained evidence:

```sh
python3 benchmark_report.py
```

The hardware inventory excludes serial numbers and hardware UUIDs. Each cleanup
receipt records the removed path, the SHA-256 of its archived result, an approximate
allocated footprint, and filesystem free-space counters before and after removal.

This is a portable Python standard-library runner for Linux and macOS.
The first dataset is `eventpop/eventpop`, commit
`0e0499f42444f1e4b2c0a6d11fc8043b42be295a` (10,055 tracked files).
The source checkout is read only. A separate bare clone, package store,
and disposable worktrees are created under a unique `fsbench-*` directory.
No Rails services, database provisioning, or dependency lifecycle scripts run.

## Run

Use the Node and pnpm versions in the representative repository. This commit
pins Node 24.22.1 and pnpm 11.18.0. Put the selected Node on PATH and pass the
selected pnpm executable. A version mismatch stops the run.

```sh
python3 bench.py --source /path/to/eventpop \
  --commit 0e0499f42444f1e4b2c0a6d11fc8043b42be295a \
  --target /path/on/filesystem/to/test \
  --pnpm /path/to/pnpm-11.18.0 \
  --workers 1 2 3 4 --warmups 1 --runs 10

python3 report.py /path/on/filesystem/to/test/fsbench-XXXX/results.json
python3 -m unittest -q
```

The target needs room for the Git objects, dependency store, and four installed
worktrees. Every invocation creates a new directory. The setup install can use
the network. All warmups and measurements use `--offline --frozen-lockfile
--ignore-scripts`. Both development and production JavaScript dependencies are
included. Ruby dependencies are not installed.

Use `--skip-install` for a checkout/deletion-only benchmark. Use
`--seed-store /path/to/existing/store --offline-setup` to copy an existing pnpm
store into the dedicated store before setup. The original store is never used
for a timed install. The default import method is `auto`, so filesystem-specific
clone/link behavior is part of the result. Use `--import-method copy` for a
separate experiment that forces copies. Do not combine results from these modes.

## Measurement

Each batch starts N checkouts concurrently, waits for all checkouts, starts N
installs concurrently, waits for all installs, then deletes N complete trees
concurrently with Python's `shutil.rmtree`. Git worktree metadata is pruned
outside the timer. This is filesystem tree deletion, not application teardown
or the runtime of `git worktree remove`.

Workers wait on a barrier before each phase. Record batch wall time and each
worker's elapsed time with a monotonic clock. Total is the sum of phase wall
times. Throughput is N / total. N workers perform N workflows, so total time
alone does not measure scaling. Independent worker lifecycle timings are not
the same as this phase-barrier experiment.

Run one warmup batch for each worker count, then ten measured rounds. Worker
counts are shuffled within each round with seed 42. No cache eviction occurs;
the dependency store and source objects are warm. No fsync or storage flush
occurs. This measures command completion on the current live desktop, not
durable-write latency or an idle dedicated test machine.

Results are saved after each successful batch in JSON and CSV. Failures mark
the JSON run as failed. The report accepts only complete runs. Per-command
errors are retained in the JSON error field. All benchmark trees are cleaned
on handled errors; an uncatchable process kill can leave scratch data.

The bare clone and dedicated package store remain for inspection. Remove only
the generated run directory when it is no longer needed.

## Comparing machines

Copy the runner and tests to a Mac and use the same Eventpop commit, Node/pnpm
versions, worker counts, and import mode on a local APFS volume. Results measure
the whole machine and OS, including hardware and native filesystem behavior.
Platform-specific optional packages can differ between Linux and macOS.

For Linux filesystem comparisons, place the target on a dedicated device
formatted as Btrfs, ext4, or XFS, keeping the device and other settings constant.
Filesystems mounted from images inside Btrfs introduce an extra storage layer.
Record compression, encryption, snapshots, free space, CPU power settings,
background work, and indexing settings alongside results. Btrfs compression
and LUKS encryption remain active in this machine's baseline.

For these two machines, generate a comparison after both runs finish:

```sh
python3 compare.py desktop-results/results.json mac-results/results.json
```

The comparison rejects incomplete runs and mismatched workload settings,
including repository commit, lockfile hash, Node/pnpm versions, import method,
worker counts, and measured sample counts. It produces `comparison.html` and
`comparison.json`. The HTML labels describe the Linux PC and MacBook used here.
Different CPUs, SSDs, Git versions, OS behavior, and optional native packages
remain part of the comparison. SSH transports output; all timing uses the
remote machine's monotonic clock, so network latency is outside the timers.

## Recorded Mac interruption

The Mac run stopped after 33 successful batches when concurrent `git worktree add`
failed to read another worktree's `commondir` file. Its original failed result is
preserved as `results-before-resume.json`. `resume.py` schedules only missing
samples and compiles the original runner's batch function without changing it.
It verifies the runner against the SHA-256 recorded in the Mac host context.
Only this specific checkout metadata read failure can be retried, with a maximum
of three attempts per missing batch. Failed attempts are recorded separately.
Completed timing samples exclude failed attempts. Resumption times and errors
remain in the results, and the comparison report discloses the interruption.

## Additional Linux hosts

The ThinkPad uses an i5-7300U, a SATA SSD, and Btrfs with zstd:3 over LUKS.
Its home mount uses `relatime`; the Ryzen desktop uses `noatime`.
The Debian host uses an i5-7500T, 8 GB RAM, and ext4 on an HGST rotational HDD.
These are hardware and OS comparisons, not isolated filesystem measurements.

```sh
python3 compare_all.py desktop-results/results.json mac-results/results.json \
  thinkpad-results/results.json --debianarze debianarze-results/results.json \
  --m1-pro m1-pro-results/results.json
```

The comparison checks matching workload settings and complete sample counts
for every machine. It retains the earlier two-machine report separately.
Node on PATH is pinned to 24.22.1; pnpm 11.18.0 also carries its own embedded
Node runtime, so the PATH Node version is not the pnpm runtime version.
The setup logs show automatic package imports using clones on Btrfs/APFS and
hard links on the Debian host's ext4 filesystem. That native tool behavior is
part of this workload. The Debian host also had swap in use before setup.

The additional M1 Pro is a 10-core Apple M1 Pro with 32 GiB RAM, macOS 26.6.2,
APFS with FileVault, AC power, and about 97 GiB free at the start. Its runner,
commit, PATH Node version, pnpm version, and worker settings match the other runs.

## Onarchy XFS follow-up

`fs_experiment.py` runs a paired experiment on the same desktop and NVMe:
native Btrfs, Btrfs in a 16 GiB image, and plain XFS in a matched 16 GiB image.
The image files use NOCOW on the outer Btrfs filesystem. Full preallocation is
restored and checked after formatting, because mkfs.xfs file mode recreates a
sparse file. Existing partitions are never formatted. Privileged operations
are limited to mounting and detaching the new loop devices and owning their
filesystem roots. Dependencies are xfsprogs, btrfs-progs, util-linux and sudo.

Each case has its own Git copy and package store. The original runner performs
warmups and one excluded preflight round. The original batch function then runs
ten measured rounds, alternating filesystem cases at each worker count in a
fixed randomized order. The worker order uses seed 42; case order uses seed 73.
The initial pilot had a sparse XFS backing file, was stopped and cleaned, and is
preserved under `xfs-pilot-results/` as excluded evidence.

```sh
python3 report_fs_experiment.py
```

The follow-up outputs are `xfs-experiment-report.html`,
`xfs-experiment-summary.json`, and `xfs-experiment-evidence.zip`. Raw paired
timings, preflight records, mount/format settings and cleanup receipts are in
`xfs-results/`. The tools retain the installed xfsprogs/liburcu packages, while
temporary mounts, loop devices, images and benchmark data are cleaned afterward.

Both guest filesystems still sit over native Btrfs. This is an exploratory
comparison, not a bare-metal filesystem ranking. The video also discusses XFS
with VDO; VDO is a separate block-level deduplication/compression layer and is
not part of this plain-XFS test.
