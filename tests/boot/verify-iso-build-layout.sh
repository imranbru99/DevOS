#!/bin/bash
# DevOS ISO pipeline layout checks without building an ISO.
# Validates build scripts, boot mastering sources, and image payload paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
fail() { echo "  FAIL: $*" >&2; FAIL=$((FAIL + 1)); }
pass() { echo "  PASS: $*"; PASS=$((PASS + 1)); }
require_file() {
  if [ -f "$1" ]; then pass "$1"
  else fail "missing file: $1"
  fi
}
require_exec() {
  if [ ! -f "$1" ]; then
    fail "missing script: $1"
    return
  fi
  if bash -n "$1"; then
    pass "syntax: $1"
  else
    fail "syntax error: $1"
  fi
}

echo "==> ISO build layout dry checks (source tree)"

for script in \
  build/build-iso.sh \
  build/lib-boot-iso.sh \
  build/rebuild_iso.sh \
  build/setup-build-env.sh \
  tests/boot/verify-iso-bootability.sh; do
  require_exec "$script"
done

require_file build/embedded_grub.cfg
require_file build/verify-package-binaries.py
require_file build/verify-base-release.py
require_file build/versions.lock
require_file build/docker/Dockerfile.build

hook_count="$(find build/hooks -maxdepth 1 -name '*.hook.chroot' 2>/dev/null | wc -l)"
if [ "${hook_count}" -ge 1 ]; then
  pass "chroot hooks present (${hook_count})"
else
  fail "no build/hooks/*.hook.chroot files"
fi

for path in \
  build/includes.chroot/usr/local/bin/devos \
  components/devos_cli.py \
  components/optimizer/responsiveness.py \
  build/includes.chroot/etc/calamares/settings.conf; do
  require_file "$path"
done

if grep -q 'devos_prepare_boot_tree' build/lib-boot-iso.sh && \
   grep -q 'devos_master_iso' build/lib-boot-iso.sh; then
  pass "lib-boot-iso exports hybrid mastering helpers"
else
  fail "lib-boot-iso missing hybrid boot helpers"
fi

if python3 -m py_compile build/verify-package-binaries.py build/verify-base-release.py; then
  pass "build verification Python modules compile"
else
  fail "build verification Python modules failed py_compile"
fi

echo "==> Summary: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
