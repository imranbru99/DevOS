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
- Compressed zram swap remains enabled. Its virtual capacity equals RAM; this
  is not preallocated physical RAM or a guaranteed doubling of usable memory.
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
