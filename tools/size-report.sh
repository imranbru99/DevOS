#!/bin/bash
# DevOS Size Audit & Debloat Script
# Reports top installed packages and identifies disk bloat candidates
set -euo pipefail

echo "=========================================================="
echo "          DevOS Package Size & Debloat Audit              "
echo "=========================================================="

if ! command -v dpkg-query >/dev/null 2>&1; then
    echo "This script is designed to run on the DevOS system or inside chroot."
    exit 0
fi

echo "Top 30 Largest Installed Packages:"
echo "----------------------------------------------------------"
dpkg-query -Wf '${Installed-Size}\t${Package}\n' | sort -n -r | head -n 30 | awk '{printf "%.2f MB\t%s\n", $1/1024, $2}'
echo "----------------------------------------------------------"

echo "Checking for unneeded documentation..."
DOC_SIZE=$(du -sh /usr/share/doc 2>/dev/null | cut -f1 || echo "0")
echo "  /usr/share/doc: ${DOC_SIZE}"

echo "Checking for APT cache..."
APT_SIZE=$(du -sh /var/cache/apt 2>/dev/null | cut -f1 || echo "0")
echo "  /var/cache/apt: ${APT_SIZE}"

echo "Audit complete."
