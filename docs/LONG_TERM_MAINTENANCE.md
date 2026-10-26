# DevOS long-term maintenance

Maintainer: Imran Ahmed <me@imrandev.bd> — https://imrandev.bd

Ten years of daily use requires ongoing security fixes, tested OS upgrades,
recoverable backups, and suitable hardware. It is a maintenance goal, not a
guarantee of uninterrupted operation or support for every third-party app.

## Current improvements

- Automatic security updates select Ubuntu archive origins while retaining the
  DevOS identity. Existing generated origin templates are repaired at the next
  security-service boot without turning on updates that a user disabled.
- A manual security update refreshes package lists before installing security
  fixes. Missing update tools and refresh failures no longer look successful.
  Automatic reboots remain disabled; restart when notified to finish updates.
- Pre-package snapshots run only on btrfs and have a 30-second execution limit
  plus a five-second termination grace period. Snapshot failure does not block
  apt's automatic security updates. The explicit Security update action still
  stops if its requested snapshot fails.
- Snapper cleanup is enabled; existing numbered-snapshot retention settings
  remain in force. Raw fallback btrfs snapshots are not managed by Snapper's
  retention policy and need separate inspection. No user files are automatically
  deleted by these changes.
- Journald is configured for 300 MB persistent use, 64 MB runtime use, 256 MB of
  free-space reserve, and 30-day retention. Security and snapshot helper logs
  rotate weekly or when above 1 MB at the next logrotate run, with four rotations.
  These are periodic cleanup policies, not hard instantaneous disk quotas.
- The installer requires a target with at least 32 GB of disk space. Allow at
  least 64 GB for daily use and more for AI models, Windows apps, games and
  personal files. The documented daily-use minimum remains 4 GB RAM; the
  installer's lower 2 GB gate permits constrained installations.
- Installer animations can be disabled for the session. Background graphics use
  a small vector asset, navigation supports keyboard focus, and the welcome page
  scrolls on shorter displays. These changes do not imply benchmarked speedups.

## Disk write access and formatting

The installer checks home/settings write access as the actual desktop user
before reporting completion. A login check can report permission denial,
read-only filesystems, full blocks/inodes, quota exhaustion and I/O failures.
New ext4/btrfs data-volume roots are assigned to the invoking or installed user;
system-root ownership is not changed. The check never recursively changes
permissions or forces damaged filesystems writable. This prevents specific known
bugs; it cannot promise that permissions, storage or hardware will never fail.

The additional Data drives page starts with formatting off. It can prepare
explicitly selected additional drives with ext4 A/B/C volumes after Install.
The partition job remains responsible for the OS disk and manual layouts.
See [Storage management](STORAGE_MANAGEMENT.md). The existing boot helper is now
diagnostic only: automatic Btrfs log clearing could discard recent changes.

## Recovery and backups

The default automatic filesystem is ext4. DevOS's built-in Snapper restore-point
backend requires btrfs; it is unavailable on ext4. Choose btrfs if that recovery
method suits the installation, or configure a separate ext4-compatible backup
method. Do not treat a snapshot stored on the same disk as a backup against disk
failure. Keep an independent backup and actually restore sample files from it.

The installer starts with manual partitioning selected. Click Next to edit each
drive, select exactly which partitions to format, and assign the installation
mount points. Leave other partitions unchanged to preserve their data. Erase disk
remains available and erases every partition on the selected physical disk.
Review the summary before applying changes.

## Support boundaries and remaining release work

Ubuntu publishes standard maintenance for the 26.04 base through May 2031 and
expanded maintenance through May 2036. These dates do not automatically provide
Canonical support or extended-subscription coverage for DevOS. DevOS components,
third-party applications and repositories require their own maintenance.
See https://ubuntu.com/about/release-cycle.

The existing OS upgrade helper supports only the 24.04-to-26.04 transition. A
future supported LTS migration must be implemented and tested when available;
there is no current promise of ten years of in-place DevOS upgrades. Release
bundle signing and key rotation also remain outstanding; the existing SHA-256
checksums protect integrity but are downloaded from the same publisher channel.

CI now gates installer/update tests and ISO boot-layout validation. The bounded
QEMU observation distinguishes a normal timeout from a QEMU error, but does not
assert that the desktop or installed system is ready. ShellCheck remains
advisory. Actual installation, data preservation on a second disk, first reboot,
recovery, encryption and representative hardware testing are still required.

Rebuild the ISO to deliver these changes. The development preview uses mock
Calamares data and does not replace a runtime test with the real installer.
