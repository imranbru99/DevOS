# DevOS filesystem recovery

A failure to boot or save a file does not identify a single cause. Distinguish
permission errors (EACCES/EPERM), read-only filesystems (EROFS), full disks or
inodes (ENOSPC), and hardware I/O errors (EIO) before changing anything.

## Diagnose and preserve data

Boot the live USB if the installed system cannot start. Identify the correct
drive and filesystem with `lsblk -f` and inspect `dmesg` for the actual error.
Record the messages and copy important files to another disk when possible.
For a failing physical drive, preserve/image it before performing write repairs.

If the desktop still works, check `df -h` and `df -i` for block and inode usage,
`findmnt -no SOURCE,FSTYPE,OPTIONS /` for the root mount, and ownership of the
specific folder that cannot be written. Permission changes do not repair a
read-only filesystem or hardware fault. Do not use recursive chmod/chown on `/`
or set every directory world-writable.

Btrfs can intentionally stop writes after errors to protect data. A root mounted
read-only in the early initramfs stage can also be normal; the regular boot
sequence remounts it later. DevOS does not infer corruption from a failed touch,
force it writable, or claim recovery just because an init executable exists.

## Targeted Btrfs recovery

The retained `devos-btrfs-heal` initramfs filename now supplies diagnostics only.
It performs no automatic repair writes. The panic guide identifies diagnostic
steps instead of prescribing one repair for every boot failure.

`btrfs rescue zero-log` is applicable to specific failures during log replay.
It can discard changes since the last committed transaction. Clearing the free
space cache is a separate, targeted operation, not a routine next step for all
failures. Diagnose using the kernel trace, verify the device and its mount state,
preserve the data, and consult the upstream instructions before choosing either
operation. Do not run `btrfs check --repair` as a general-purpose fix.

See [upstream btrfs-rescue documentation](https://btrfs.readthedocs.io/en/latest/btrfs-rescue.html)
for conditions and limitations. A short shutdown timeout does not guarantee
that a drive's write cache was flushed or make sudden power loss safe.

## Prevention and qualification

Keep independent backups and test restoration. Keep free space for updates and
snapshots, use the appropriate filesystem, monitor drive errors and use reliable
power. Never assume an SSD, HDD or filesystem is immune to failure. Test the
rebuilt ISO and the installed system's first boot and recovery behavior before
publishing changes to these boot scripts.
