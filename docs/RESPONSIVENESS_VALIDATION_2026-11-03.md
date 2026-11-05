# Responsiveness validation — November 3, 2026

On the current KDE Wayland session:

- Physical RAM: approximately 31.1 GiB; available approximately 25.2 GiB.
- Compressed swap: approximately 15.6 GiB; unused during inspection.
- Root filesystem: NVMe, approximately 12% used.
- Memory PSI averages were zero during inspection; no current memory stall was observed.
- Before activation, session/app CPU weights were both 100; background was 30.
- Priority-only activation succeeded. Kernel `cpu.weight` now reports session 400,
  apps 100 and background 20. These are contention shares, not CPU reservations.
- I/O weights were configured but `io.weight` is unavailable in the user cgroups.
  No effective I/O prioritization or throughput improvement is claimed.
- systemd-oomd is active. The new per-app memory threshold and monitoring policy
  have **not** been activated on this session; explicit approval is pending.
- A real `systemd-run` scope launched `/usr/bin/true` through the bounded launcher
  and returned success. This verifies supported properties and basic launch, not
  sustained-load performance or memory-exhaustion recovery.
- The existing six responsiveness tests and ten new launcher/policy tests pass.
  Theme-switcher tests also passed independently.

No stress workload was run against the user's active desktop. There is no measured
before/after frame-latency claim and no guarantee that every application or driver
will remain responsive. Application deadlocks, GPU faults and thermal throttling
require diagnosis separately.

The 20 premium wallpapers were installed in the user's wallpaper directory and
Pearl Fold was applied successfully. All 20 originals decoded, had unique SHA-256
hashes, and measured 1672 × 941 pixels. No ISO rebuild was performed.
