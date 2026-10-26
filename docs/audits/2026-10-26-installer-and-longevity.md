# Installer and OS longevity audit

Date: 2026-10-26 (Asia/Dhaka)
Developer: Imran Ahmed <me@imrandev.bd> — https://imrandev.bd

## Follow-up source changes

The subsequent improvement pass fixes the generated security-update origins and
adds a boot-time migration preserving user preferences. It also fixes the 7z
fallback, adds installer/update and ISO-layout CI gates, reports QEMU startup
errors, bounds pre-package snapshots, enables snapshot cleanup, rotates helper
logs, increases the storage gate, and improves installer accessibility and motion.
The historical findings below describe the audited starting state. Future LTS
migrations, independent release signatures and full runtime qualification remain
outstanding. The follow-up also adds explicit installer data-drive plans, volume
ownership and user write-access checks, protects active/unknown/read-only drives,
and replaces automatic destructive Btrfs repair with diagnostics. See
[the maintenance guide](../LONG_TERM_MAINTENANCE.md) and
[storage management](../STORAGE_MANAGEMENT.md).

## Assessment

Ten years of supported daily use is a feasible maintenance goal, but the current
DevOS source and existing ISO do not demonstrate that readiness. This audit is a
source/configuration review and bounded automated test run, not a complete
hardware qualification or a ten-year reliability certification. No production
disks were formatted, no release upgrade was executed, and no ISO was rebuilt.

Ubuntu 26.04 is the configured base. Canonical lists standard security maintenance
through May 2031, expanded maintenance through May 2036, and a Legacy add-on
through May 2041. These are Ubuntu lifecycle dates, not a promise that Canonical
supports DevOS or its custom components. Ten years from this audit ends in October
2036, beyond the expanded-maintenance date. A maintained migration path is needed;
any extended subscription coverage and derivative eligibility must be established
separately.

Source: https://ubuntu.com/about/release-cycle

## Findings requiring work

1. **High: automatic security-update origins do not match the branded system.**
   `components/security/updates.py:52` uses `${distro_id}` in every allowed origin.
   The actual build-tree unattended-upgrade program obtains that value using
   `lsb_release -i -s`. Running the build-tree lsb_release with the source
   os-release file returned `DevOS`; Ubuntu repository origins use `Ubuntu`.
   The generated rules therefore select `DevOS:resolute-security`, rather than
   `Ubuntu:resolute-security`. Explicitly match Ubuntu archive origins while
   preserving the DevOS identity; verify with an installed-system unattended
   upgrade dry run. This mismatch was reproduced at identification/substitution
   level; a package transaction was not run.

2. **High: the supported OS upgrade helper ends at 26.04.**
   `build/includes.chroot/usr/local/sbin/devos-upgrade-os:17` exits successfully
   when already on 26.04, and otherwise accepts only 24.04. Component updates
   do not replace the base-distribution upgrade path. Future supported LTS
   transitions need implementation and migration tests when available; do not
   force a development release or assume a future release is already supported.

3. **Medium: default installations do not have built-in system snapshots.**
   `partition.conf` defaults to ext4. `SnapshotManager.create_restore_point()`
   returns UNAVAILABLE for filesystems other than btrfs. Updating can proceed
   without this protection. Either provide and test an ext4 recovery method or
   clearly expose the recovery difference before filesystem selection. Btrfs
   snapshots also do not replace off-device backups or a tested recovery boot.

4. **High: CI can report success without a successful boot test.**
   `.github/workflows/build-iso.yml` ignores shellcheck failures and ignores the
   exit status of a 60-second QEMU invocation using `|| true`. The QEMU step has
   no assertion that the desktop, installer, or installed system actually starts.
   CI needs explicit success signals and automated installation/reboot checks,
   including two-drive data-preservation checks and UEFI/BIOS coverage.

5. **Medium: ISO verification has a broken 7z fallback.**
   `tests/boot/verify-iso-bootability.sh` compares slash-prefixed required paths
   against 7z output without a leading slash. It reported 11 missing files in
   this environment. Independent `7z l -slt` inspection found all 11. These
   failures are verifier errors, not evidence that the boot files are absent.
   Checks requiring xorriso/lsinitramfs were skipped and remain unverified.

6. **Release validation: recent installer changes are not in the build tree.**
   The existing `build_work/resolute/chroot` still defaults to erase mode and
   differs from source for the sidebar and Plymouth theme. Source changes must
   be rebuilt into an ISO and visually/runtime tested. The existing ISO cannot
   be used as evidence that the new partition default or animations work.

7. **Update trust needs strengthening for a long-lived distribution.**
   The component updater checks SHA-256 checksums and validates bundle paths,
   but the checksum is downloaded from the same release as the bundle, with no
   separate signature verification or pinned release-signing key. This detects
   corruption but is not independent publisher authentication if release assets
   are compromised. The bootstrap script downloads executable code from main.
   Define signing, key rotation, and a recovery procedure before promising a
   decade of custom component maintenance.

## Checks performed

- Python syntax: 133 source/test/tool files parsed successfully.
- Shell syntax: 30 scripts/hooks passed `bash -n`.
- Installer checks: all 13 tests in test_install_branding and test_installer_boot passed.
- All 32 unit-test modules were attempted separately with pytest, an offscreen Qt
  backend, and a 30-second per-module timeout: 25 modules passed completely;
  five modules had local-socket permission failures; two timed out.
- Completed-module summaries report 463 passed tests, five failures and 16 errors.
  All five failures and 16 errors in those summaries are local socket creation
  denied by this environment. AI-agent and theme-switcher modules timed out;
  their partial tests are not included in these totals. Subtest counts are
  excluded. These results do not establish that the remaining tests pass.
- The initial unittest run was stopped after stalling; isolated pytest runs were
  used because some repository tests are pytest functions. An isolated unittest
  watchdog run also exposed a test import dependency on unittest.mock; the
  pytest watchdog run passed.
- Existing ISO: MBR code/signature, bootable entry, GPT header and ESP type passed
  the supplied verifier (five checks). All 11 required ISO files were separately
  confirmed present using normalized 7z paths.
- `git diff --check` passed for current tracked changes.

## Positive provisions already present

Automatic security-update configuration and restart notifications exist; automatic
reboots are disabled. Journald has a 300 MB cap. SSD trimming is enabled by a build
hook. Several services restart on failure. Disk Guard monitors space growth and
protects package managers from automatic pausing. Btrfs snapshot support and
optional user backups exist. These are useful mechanisms, not evidence that every
failure or restoration path has been exercised.

## Required qualification before claiming long-term readiness

Rebuild the current source and test actual installation and first boot on blank
and previously partitioned disks, including a second disk whose contents are
verified unchanged. Cover BIOS, UEFI, Secure Boot as claimed, disk encryption,
ext4 and btrfs, offline installation, update failures, rollback and rescue boot.
Verify security-update candidate selection and service state after installation.
Exercise suspend/resume, networking, audio, GPU drivers, Windows/Android layers,
and disk-space pressure on representative hardware. Run sustained workload tests
and independently restore off-device backups. Publish a DevOS maintenance policy
covering custom applications and third-party repositories as well as the base OS.

These steps remain outstanding. Booting to a desktop alone does not validate the
complete installer or every OS feature.
