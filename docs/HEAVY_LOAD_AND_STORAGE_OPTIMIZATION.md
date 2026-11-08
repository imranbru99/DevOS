# Responsiveness and disk-space care

DevOS aims to keep interactive work responsive while builds, browsers, video
exports and local AI compete for resources. It cannot guarantee uninterrupted
operation or unlimited throughput. Power loss, thermal limits, driver faults,
full disks and hardware failures remain possible. No before/after performance
improvement is claimed without measurements on the target hardware.

## Resource policy

- One boot-time hardware policy selects supported CPU governors, keeps an
  adaptive energy preference, uses small read-ahead on SSD/NVMe and a separate
  HDD policy. It does not force maximum clocks, deep disk queues or PCIe power
  settings. User-selected power profiles remain available in Power Settings.
- Compressed zram swap remains enabled at 50% of physical RAM (about 15–16 GiB
  on a 32 GiB PC), matching the daily install. A disk `/swap/swapfile` of the
  same size (capped at 16 GiB) is created at install time for overflow. Zram
  capacity is virtual, not preallocated RAM or a guaranteed memory multiplier.
- Pending buffered writes are capped at 64 MiB for background writeback and
  256 MiB for writer throttling, instead of growing to gigabytes on large PCs.
  Writes can still block on a saturated or failing device.
- systemd-oomd monitors application and background slices separately, rather
  than treating the full user session as a kill candidate. Under sustained
  memory pressure it can forcibly terminate an application group; unsaved work
  in that group can be lost. The kernel OOM killer remains the last resort.
  The competing earlyoom daemon is disabled by default.
- Session CPU/I/O weights exceed background weights. These are relative
  preferences during contention, not guaranteed frame rates or CPU reservations.
- AI services run in a dedicated monitored slice. Default concurrent slots
  share CPU threads, model pages remain reclaimable, and the service yields
  CPU/I/O priority to interactive work. MemoryHigh is 60% and MemoryMax is 75%
  of physical RAM; the latter can terminate an overlarge model workload. Restart
  attempts are limited to three per five minutes. This prioritizes keeping the
  rest of the computer usable over completing an impossible model allocation.
- AI does not override the user's power governor unless DEVOS_AI_CPU_BOOST=1
  was explicitly configured. Existing explicit AI thread settings still work.

The kernel chooses its free-memory reserve; DevOS no longer forces a 128 MiB
reserve or extreme multi-billion mapping limits on every PC.

## Automatic cache care

The Optimizer runs a per-user daily maintenance timer with idle I/O priority,
low CPU weight, a CPU quota, a 96 MiB memory limit and a 45-second service timeout.
It starts only in the installed OS, never the live installer. The tray menu's
**Automatic cache care** toggle disables scheduled deletion.

Only these disposable locations are eligible:

| Location in the user's home | Minimum inactivity |
| --- | --- |
| `.cache/thumbnails` | 30 days |
| `.cache/devos/temporary` | 14 days |
| `.cache/devos/previews` | 30 days |

Modification, access and metadata-change times must all be older than the
threshold. Open files, hardlinks, symlinks, mounted filesystems and foreign-owned
entries are skipped. Every directory is opened relative to an anchored directory
file descriptor. If active file handles cannot be checked, the run skips cleanup.
Each pass examines at most 5,000 entries, spends at most five seconds scanning
and deletes at most 512 MiB of allocated file blocks. It does not remove folders.

Downloads, documents, recordings, Trash, account/session data, offline models,
unknown app caches, package/build caches and GPU shader caches are not automatic
targets. Rebuilding useful caches uses CPU, causes stutter and may require a
network connection, so deleting all caches would harm the desired experience.
Manual cleanup remains available with a preview for broader categories.

Preview using `python3 /usr/local/share/devos/components/optimizer/optimizer.py --auto-scan`.
The last automatic result replaces `.local/state/devos/optimizer/auto-clean-last.json`;
reports do not accumulate indefinitely. The timer can be inspected using
`systemctl --user status devos-optimizer-clean.timer`.

OS storage is also bounded: system journal 200 MiB, runtime journal 64 MiB, crash
storage 200 MiB, and existing rotated security/snapshot logs. Journal/crash storage
reserves 1 GiB of free space when possible. Limits do not reserve space against
other writers, and a large already-open log may exceed its limit temporarily.
APT does not retain successful package downloads; its normal maintenance cycle
removes obsolete cached package files weekly. Installed packages, rollback
snapshots and downloaded AI models are not silently removed.

## Filesystems and verification

Automatic installation uses ext4. Btrfs is an explicit alternative; its optional
zstd compression is workload-dependent and does not guarantee smaller games,
media or application installations. zstd is a compressor, not a filesystem.

Unit and synthetic-media tests cover cleanup boundaries, concurrent AI budgets,
clip exports and installation storage safeguards. A hardware acceptance test
should run the intended browser/build/video/AI workload for at least an hour,
observe compositor responsiveness, temperatures, memory and `/proc/pressure/*`,
and inspect `journalctl -p warning` and `oomctl`. Repeat on SSD and HDD machines
and under low-memory conditions. These are acceptance steps, not results claimed
for every machine or a proof of ten-year reliability.

References: [Linux VM controls](https://docs.kernel.org/admin-guide/sysctl/vm.html),
[systemd resource control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html),
[systemd-oomd](https://www.freedesktop.org/software/systemd/man/latest/systemd-oomd.service.html).

Developer: Imran Ahmed <me@imrandev.bd> — https://imrandev.bd


## Desktop responsiveness controls (November 2026)

`devos smooth status` reports live CPU/memory/I/O pressure, available memory,
systemd-oomd status, and the configured and kernel-visible slice settings. Missing
D-Bus access or controllers are reported as unavailable, not as working protection.

`devos smooth apply --priority-only` installs only CPU/I/O contention weights,
without new memory thresholds or OOM actions. It writes `90-devos-priority.conf`.

`devos smooth apply` installs the full policy for the current user and applies it to
running slices without restarting applications. Source-tree equivalent:

```sh
python3 components/optimizer/responsiveness.py apply
```

The session CPU weight is 400, normal apps 100, and background work 20. These are
relative contention weights, not a fixed CPU quota. Apps retain access to idle CPU.
The application slice starts reclaim/throttling above 85% of physical RAM; this is
a soft threshold, not a guaranteed reserve. Existing pressure monitoring remains,
and app/background slices additionally participate in systemd-oomd swap pressure
recovery. The system daemon must be running for this recovery to work. I/O weights
only work when the controller is delegated and the storage stack supports them.
No live swap resize, forced cache purge or compositor restart is performed.

For a large build, conversion or local computation:

```sh
devos smooth run -- make -j8
# From the source tree:
python3 components/optimizer/responsiveness.py run -- make -j8
```

Each job receives its own background scope. MemoryHigh is the smaller of 50% of
physical RAM and 60% of currently available RAM; MemoryMax is the smaller of 70%
and 80% respectively. Below 512 MiB available memory, the command refuses to start.
The hard limit can terminate the entire job, so use it for restartable workloads.
These are launch-time budgets, not reservations against future allocations by
other apps. The scope limits process count to 2,048. It never silently runs the
command without protection if systemd-run fails. Apps that delegate work to an
already-running process may escape the scope and are not covered by these limits.

The apply command writes only `90-devos-responsiveness.conf` in the three user
slice drop-in folders, saving a pre-existing file as `.conf.before-devos`. It also
sets runtime properties; if applying a property fails it reports failure and may
leave earlier properties applied. To undo, restore the saved drop-ins (or remove
only these new files if no backup exists), remove the matching runtime property
overrides with `systemctl --user revert app.slice background.slice session.slice`
only after checking for unrelated overrides, then reload the user manager and
log out/in. The runtime overrides disappear at user-manager restart.

This is a resource policy, not evidence that all applications run smoothly.
Validate the actual workload and GPU/driver behavior on the target machine.

## Hang soak harness

On a machine running the target workload (browser, build, video export, or AI),
sample PSI and kernel hung-task warnings for at least an hour:

```sh
chmod +x tools/hang-soak.sh
./tools/hang-soak.sh --minutes 60
```

Use `--dry-run` for a single sampling cycle (sanity check). Defaults:

- Sample every 10 seconds for 60 minutes (`--minutes`, `--interval`).
- Fail if `journalctl` reports `hung task` or `Blocked for more than` since soak start.
- Fail if memory pressure `some avg10` stays at or above **80.0** for **3** consecutive
  samples (~30s at the default interval). Override with `DEVOS_SOAK_MEM_AVG10_FAIL` and
  `DEVOS_SOAK_MEM_CONSEC`.

When `devos` is on `PATH`, each cycle also prints `devos smooth status`; from the
source tree, `python3 components/optimizer/responsiveness.py status` is used instead.
