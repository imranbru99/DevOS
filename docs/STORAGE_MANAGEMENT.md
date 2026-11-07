# Storage management

DevOS supports SSDs, hard disks and supported USB storage through the Linux
storage stack. Hardware, controller and filesystem compatibility still need
validation on the actual machine. Volume labels A, B and C are names shown in
Files; they are not Windows drive letters.

## During installation

1. In **Partitions**, choose the OS disk. **Erase disk** automatically prepares
   that disk using ext4 by default and the firmware's required boot layout.
   **Manual partitioning → Next** lets you create/delete/format partitions and
   choose their sizes and installation mount points across detected disks.
2. In **Data drives**, keep additional disks unchanged or explicitly select
   writable, unmounted data disks. **Select all eligible drives** selects all
   such drives except the installer USB. Choose one volume or an A/B/C layout,
   edit sizes in GiB, and leave the last volume to use remaining capacity.
3. Read the disk names and proposed layout. Tick the erase confirmation only
   when the listed additional-drive data has been backed up. Without that
   confirmation, additional-drive formatting stays off.
4. Review the installer and confirm **Install**. Calamares handles the OS disk
   and manually configured layouts. The additional-drive job skips disks
   already claimed/mounted by Calamares, validates the other choices and
   prepares only those selected data disks as ext4. It uses the new desktop
   account's ownership so freshly formatted Linux data volumes are writable.

This is a whole-disk replacement operation for additional data disks, not an
in-place shrink. Do not select a disk whose existing partitions you want to
preserve: use manual partitioning instead. Automatic ext4 data layouts do not
add encrypted data volumes. The OS encryption option belongs to the Partitions
step. Zstd is a compression algorithm, not an alternative filesystem to Btrfs.

All additional-drive plans are checked before the first additional disk is
modified. A missing/changed/protected disk or missing formatting tool stops that
phase. Each operation rechecks its target; no force/lazy unmount is performed.
Formatting several disks is not an atomic transaction: a later hardware failure
can leave earlier chosen disks already changed. The error reports that no
rollback was performed. Never assume a formatting failure preserved the selected
disk's original layout or data.

## From the desktop

Open **Storage & Boot Doctor** (`devos-disk-gui`). Each drive has a capacity map,
its media/model, labels, filesystem, used/free space and mount state. The running
system disk, live USB and read-only targets are protected from these formatting
actions. Size values derived from partition capacities do not establish that a
filesystem or drive is healthy.

**Create A / B / C volumes…** opens a planner for one to eight named volumes.
Choose the filesystem and size, inspect the preview and type the exact disk path
to enable erasing that disk. It replaces that disk's partition table. To resize
an existing partition or create partitions inside existing unallocated space,
use **Partition editor…**, which opens KDE Partition Manager with its own review
and apply process. Some resizing needs a live USB and unmounted filesystems.

The **Setup for DevOS** preparation action creates an EFI partition in UEFI mode
or BIOS boot space in legacy BIOS mode, plus the system partition. It prepares
the selected disk but does not itself install DevOS.

- **ext4:** automatic DevOS/data default; no built-in Snapper rollback.
- **exFAT:** data exchange with Windows/macOS; no Unix on-disk ownership.
- **NTFS:** Windows-compatible data storage; support depends on drive state.
- **Btrfs:** advanced optional Linux filesystem; snapshot/recovery limitations
  still apply. No filesystem is immune to damage or power-loss effects.

After formatting, mount the data volume from Files or the Mount button. The app
no longer mounts it as the privileged formatter account. Formatting runs on a
worker thread and the window waits for it to finish rather than freezing or
allowing another overlapping action. Do not power off during an operation.

## Write problems

Run `devos-storage-check` as your regular desktop account. It makes/removes small
probe files in your home and existing settings/cache/data directories. It reports
the specific failing path and error category, without changing ownership or
mount flags. The installer runs it as the new account before marking completion;
a login check can notify you of later problems. A root probe does not demonstrate
that an ordinary user can write.

Do not apply recursive chmod/chown to the whole disk or force a filesystem
read-write in response to an unknown error. Follow the [filesystem recovery
guide](BTRFS_RECOVERY.md) when the underlying filesystem or hardware is failing.

## Validation status

These changes require a rebuilt ISO and installation tests before release.
Automated tests use synthetic disk inventories and mock all mutation commands;
no physical disk was formatted during development. Visual previews use mock
installer data. Test actual multi-disk selection, preservation of an unselected
disk, first boot, volume write access, failure handling and recovery in an
isolated VM and on representative hardware.

The automatic OS layout follows firmware: GPT/EFI on UEFI computers and MBR on
legacy BIOS computers. A legacy BIOS installation on a disk exceeding MBR's
addressable range needs an appropriate manual GPT layout and BIOS boot partition.
The separate Storage & Boot Doctor preparation action can create GPT BIOS boot
space. Review the installer Summary before applying any layout.

The Data drives review lists device paths, volume labels, requested GiB sizes and
remaining space in readable text. Disk model/serial/capacity facts stay in a
root-owned scan snapshot and are compared with fresh hardware facts before any
additional drive is modified. Installer retries refresh this scan. Missing or
changed facts stop the operation rather than silently choosing another disk.

## Keeping C: lean (vs Windows-looking usage)

This PC shows one Used bar like Windows. That bar is **not** “OS size.” On a
typical DevOS desktop:

| Slice | Typical size | Notes |
| --- | --- | --- |
| DevOS system (`/usr`, boot) | ~12–18 GB | Already leaner than Windows 11 |
| Your files (projects, Downloads) | varies | Move large projects to **D:** |
| Apps & containers (Flatpak, Podman) | varies | Prune unused images/runtimes |
| AI models | 1–10+ GB | Prefer **D:/data/DevOS/models** |
| Freeable caches | often several GB | Optimizer / Disk Cleanup |

Actions shipped with DevOS:

1. **This PC → drive Properties → What’s using space** — OS vs files vs freeable.
2. **Right-click drive → Free up space…** — opens Optimizer (browser caches, Trash, temp).
3. **Btrfs root** uses `compress=zstd:3`. Data disks remount with the same via udisks.
4. **Snapper** keeps fewer restore points by default (`NUMBER_LIMIT=8`) so snapshots do not inflate C:.
5. **AI model downloads** prefer a mounted secondary drive when one is available.

Do not wipe `~/.config` browsers or running container storage roots — reclaim caches
and unused images instead.

## Recovery on ext4

If the root filesystem is **ext4** (installer default), Snapper/Btrfs snapshots are unavailable.
Use **Timeshift** (rsync mode) or a scheduled `rsync` backup before major upgrades.
Prefer **Btrfs + Snapper** at install time when you want one-click restore points.
