#!/bin/bash
# Source this file to locate matching OVMF code and variable-store images.
# Ubuntu 26.04 ships the 4M pair; never substitute a code image for VARS.
devos_find_ovmf() {
    local directory suffix
    local directories=(/usr/share/OVMF /usr/share/edk2/ovmf /usr/share/edk2-ovmf/x64)
    if [ -n "${DEVOS_OVMF_DIR:-}" ]; then
        directories=("$DEVOS_OVMF_DIR")
    fi
    OVMF_CODE=""
    OVMF_VARS_TEMPLATE=""
    for suffix in _4M ""; do
        for directory in "${directories[@]}"; do
            if [ -f "$directory/OVMF_CODE${suffix}.fd" ] && \
               [ -f "$directory/OVMF_VARS${suffix}.fd" ]; then
                OVMF_CODE="$directory/OVMF_CODE${suffix}.fd"
                OVMF_VARS_TEMPLATE="$directory/OVMF_VARS${suffix}.fd"
                return 0
            fi
        done
    done
    echo "ERROR: Matching OVMF_CODE and OVMF_VARS firmware files not found. Install ovmf." >&2
    return 1
}
