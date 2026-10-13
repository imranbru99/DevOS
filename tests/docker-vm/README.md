# Run the DevOS ISO in Docker Desktop

Boots `out/devos-24.04-amd64.iso` in a QEMU virtual machine inside a container
and shows its screen in the browser. The installer only sees the container's
40 GB virtual disk (`tests/docker-vm/storage/data.img`), never your real drives.

```powershell
.\tests\docker-vm\run-devos-vm.ps1            # UEFI boot (default)
.\tests\docker-vm\run-devos-vm.ps1 -Legacy    # legacy BIOS boot
.\tests\docker-vm\run-devos-vm.ps1 -Reset     # wipe the virtual disk, start over
.\tests\docker-vm\run-devos-vm.ps1 -Stop
```

Screen: http://localhost:8006, or Docker Desktop > Containers > `devos-vm` >
the `8006:8006` port link.

After the install finishes the VM restarts into the installed system on the
virtual disk. To try the live USB again, run with `-Reset`.

Notes
- The script loads the KVM module into Docker Desktop's VM first. Without it
  QEMU falls back to slow software emulation.
- Ctrl+Alt+F-keys are taken by the browser. Use the noVNC side panel
  (keyboard icon) to send them.
