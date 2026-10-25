# DevOS Filesystem Recovery & Btrfs Troubleshooting Guide

This guide explains the root cause, immediate recovery steps, and built-in protections for Btrfs tree-log and free space cache issues.

---

## 1. Symptoms & Error Messages

If a system suffers an abrupt power cut, battery drain, or kernel abort during intensive disk writes, you may see kernel messages like:

```text
[ 2.010246] BTRFS info (device nvme0n1p2): start tree-log replay
[ 2.397399] BTRFS error (device nvme0n1p2): incorrect extent count for 40832598016: counted 1476, expected 1475
[ 2.401984] BTRFS error (device nvme0n1p2 state A): Transaction aborted (error -5)
[ 2.401985] BTRFS: error (device nvme0n1p2 state A) in btrfs_convert_free_space_to_extents: errno=-5 IO failure
[ 2.401995] BTRFS error (device nvme0n1p2 state EA): failed to recover log trees with error: -5
[ 2.405749] BTRFS error (device nvme0n1p2 state EA): open_ctree failed: -5
(initramfs) _
```

---

## 2. Why Does This Happen?

1. **Tree-Log Mechanism:**
   Btrfs uses an intent tree log (`tree-log`) to quickly commit file operations (`fsync`) without flushing entire disk metadata structures.
2. **Abrupt Power Loss / Transaction Abort:**
   When power is cut or an in-memory transaction aborts (e.g. from an extent counter discrepancy in `space_cache=v2`), the log tree left on the SSD is incomplete or dirty.
3. **Replay Failure During Boot:**
   On the next boot, the kernel attempts `start tree-log replay`. When it encounters uncommitted/invalid references, it safely fails with error code `-5` (`-EIO`) to prevent filesystem corruption.
4. **Initramfs Drop:**
   Because root (`/`) cannot be mounted, the initramfs cannot hand control over to `/sbin/init`, dropping to the emergency BusyBox shell.

---

## 3. Important Notes for the `(initramfs)` Shell

Inside `(initramfs)`:
* **No `sudo` or `apt`:** You are already operating as `root` inside a minimal rescue ramdisk.
* **Command Syntax:** The unmount command is `umount` (without an `n`).

---

## 4. Step-by-Step Resolution from `(initramfs)`

### Step 1: Clear the Interrupted Tree-Log
Clearing the tree-log is safe and forces Btrfs to mount using the last clean committed transaction:

```bash
btrfs rescue zero-log /dev/nvme0n1p2
```
*(Replace `/dev/nvme0n1p2` with your root device name shown in the error lines)*

Output should confirm:
```text
Clearing log on /dev/nvme0n1p2, previous log_root ...
```

### Step 2: Clear Corrupted Free Space Cache
If an extent count mismatch occurred (`incorrect extent count`):

```bash
btrfs rescue clear-space-cache v2 /dev/nvme0n1p2
```

### Step 3: Verify Subvolumes Mount Correctly
Test mounting the root subvolume:

```bash
mkdir -p /mnt/devos
mount -o subvol=@,clear_cache /dev/nvme0n1p2 /mnt/devos
ls /mnt/devos
umount /mnt/devos
sync
```

### Step 4: Resume Boot
Reboot into your normal desktop session:

```bash
reboot -f
```

---

## 5. Built-in DevOS Automatic Protections

DevOS includes multi-layer safeguards so users never get stranded by tree-log corruption:

1. **Automatic Initramfs Self-Healing (`devos-btrfs-heal`):**
   Located in `/etc/initramfs-tools/scripts/local-bottom/devos-btrfs-heal`. If Btrfs root fails to mount due to log tree replay errors, it automatically runs `btrfs rescue zero-log` and remounts with `clear_cache,space_cache=v2`, recovering and continuing boot automatically within 2 seconds.
2. **Panic Guidance Screen (`devos-panic-guide`):**
   If an unexpected failure drops into the shell, a formatted DevOS Emergency Rescue screen displays the exact commands needed.
3. **GRUB Recovery Menu Display:**
   On failed boot detection, GRUB surfaces recovery choices for 5 seconds (`GRUB_RECORDFAIL_TIMEOUT=5`).
4. **Fast & Clean Systemd Shutdown:**
   Default stop timeout is set to 15s (`DefaultTimeoutStopSec=15s`) to prevent hang delays and ensure NVMe write caches flush completely to disk before power cuts.
5. **Periodic Scrubbing & Health Diagnostics:**
   Run `devos doctor` from the terminal to inspect device error counters, or trigger a scrub:
   ```bash
   sudo btrfs scrub start /
   sudo btrfs device stats /
   ```
