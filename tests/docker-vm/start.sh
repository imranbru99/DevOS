#!/usr/bin/env bash
# Sourced by the VM image before it builds the QEMU command.
set -Eeuo pipefail

# A hybrid ISO is attached as a removable USB disk. Linux resets that USB
# port while booting, the drive then reports an empty tray, and every read
# of the live system fails with "access beyond end of device".
# The stick stays a USB disk, which is how a real PC boots it, and it can
# no longer be ejected out from under the running system.
if [ -f /run/disk.sh ]; then
    sed -i 's/,removable=on/,removable=off/g' /run/disk.sh
fi

return 0
