"""
The installed system must boot from disk as DevOS.

These checks lock the Calamares sequence and the identity files that the
Ubuntu base would otherwise leave named Ubuntu.
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as handle:
        return handle.read()


class TestInstalledSystemBoot(unittest.TestCase):
    def load_bootloader(self):
        source = Path(ROOT) / (
            "build/includes.chroot/usr/lib/x86_64-linux-gnu/"
            "calamares/modules/devosbootloader/main.py"
        )
        spec = importlib.util.spec_from_file_location("devosbootloader_test", source)
        job = importlib.util.module_from_spec(spec)
        calamares = types.SimpleNamespace(
            globalstorage=types.SimpleNamespace(value=lambda key: "/target"),
            utils=types.SimpleNamespace(warning=lambda message: None),
        )
        with patch.dict(sys.modules, {"libcalamares": calamares}):
            spec.loader.exec_module(job)
        return job

    def test_failed_grub_install_returns_error_in_both_firmware_modes(self):
        job = self.load_bootloader()
        for uefi in (False, True):
            with (
                self.subTest(uefi=uefi),
                patch.object(job.os.path, "ismount", return_value=True),
                patch.object(job.os.path, "isdir", return_value=uefi),
                patch.object(job, "_install_disk", return_value="/dev/vda"),
                patch.object(job, "_host_run", return_value=(0, "")),
                patch.object(job, "_warn"),
                patch.object(job, "_target_run", side_effect=[(0, "root-uuid"), (1, "install failed")]) as run,
            ):
                self.assertEqual(job.run()[0], "Bootloader failed")
                self.assertEqual(run.call_args.args[1][0], "grub-install")

    def test_grub_config_requires_target_root_and_matching_initramfs(self):
        job = self.load_bootloader()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            config = root / "boot/grub/grub.cfg"
            config.parent.mkdir(parents=True)
            config.write_text("# linux root=UUID=target\n", encoding="utf-8")
            self.assertFalse(job._grub_cfg_ok(root, {"root=UUID=target"}))
            config.write_text(
                "menuentry DevOS {\n"
                " linux /@/boot/vmlinuz-7.0 root=UUID=target ro\n"
                " initrd /@/boot/initrd.img-7.0\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "boot/vmlinuz-7.0").write_bytes(b"kernel")
            self.assertFalse(job._grub_cfg_ok(root, {"root=UUID=target"}))
            (root / "boot/initrd.img-7.0").write_bytes(b"initrd")
            self.assertFalse(job._grub_cfg_ok(root, {"root=UUID=wrong-root"}))
            self.assertTrue(job._grub_cfg_ok(root, {"root=UUID=target"}))

    def test_calamares_creates_a_bootable_installation(self):
        settings = read("build/includes.chroot/etc/calamares/settings.conf")
        exec_block = settings.split("- exec:")[1].split("- show:")[0]
        steps = [line.strip().lstrip("- ") for line in exec_block.splitlines() if line.strip().startswith("- ")]

        self.assertIn("unpackfs", steps)
        # The QML account page (usersq) owns the account-creation job.
        self.assertIn("usersq", steps)
        self.assertIn("shellprocess@finalize", steps)
        self.assertIn("shellprocess@initramfs", steps)
        self.assertNotIn("initramfs", steps)  # custom job verifies the target initramfs
        self.assertIn("devosbootloader", steps)
        self.assertNotIn("bootloader", steps)  # DevOS validates the full target chain
        self.assertIn("grubcfg", steps)
        self.assertIn("devosprepare", steps)
        self.assertIn("devospreserve", steps)
        self.assertLess(steps.index("devosprepare"), steps.index("partition"))
        self.assertLess(steps.index("usersq"), steps.index("shellprocess@finalize"))
        self.assertLess(steps.index("shellprocess@finalize"), steps.index("shellprocess@initramfs"))
        self.assertLess(steps.index("shellprocess@initramfs"), steps.index("devosbootloader"))
        self.assertLess(steps.index("grubcfg"), steps.index("devosbootloader"))
        self.assertLess(steps.index("devosbootloader"), steps.index("devosumount"))
        # Optional data/AI/apps steps must run only after GRUB is installed.
        self.assertLess(steps.index("devosbootloader"), steps.index("devosstorage"))
        self.assertLess(steps.index("devosbootloader"), steps.index("contextualprocess@aimodel-apply"))
        self.assertLess(steps.index("devosbootloader"), steps.index("shellprocess@features-shell"))
        self.assertNotIn("packages", steps)
        # Final unmount must not use stock umount (busy root → false "Installation Failed").
        self.assertIn("devosumount", steps)
        self.assertNotIn("umount", steps)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosumount/main.py")))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosbootloader/main.py")))
        self.assertIn("rootMountPoint", read(
            "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosbootloader/main.py"))
        self.assertIn('["chroot", str(root)', read(
            "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosbootloader/main.py"))
        self.assertIn("Continuing install after prepare warnings", read(
            "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosprepare/main.py"))
        self.assertIn("auto Safe Graphics retry", read(
            "build/includes.chroot/usr/local/bin/devos-install-gui"))
        umount_job = read(
            "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosumount/main.py")
        self.assertIn('["umount", "-l"', umount_job)
        self.assertIn("RELEASE_BUDGET_S", umount_job)
        self.assertIn('["sync", "-f"', umount_job)
        self.assertIn("- finished", settings)
        prepare = read("build/includes.chroot/usr/local/sbin/devos-prepare-install-disk")
        self.assertIn("sgdisk --zap-all", prepare)
        self.assertIn("wipefs -af", prepare)
        self.assertIn("ntfsfix", prepare)
        finished = read("build/includes.chroot/etc/calamares/modules/finished.conf")
        self.assertIn("devos-live-reboot", finished)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/local/sbin/devos-live-reboot")))
        live_reboot = read("build/includes.chroot/usr/local/sbin/devos-live-reboot")
        # Must hard-reboot without detaching live squashfs (avoids SQUASHFS I/O spam).
        self.assertIn("reboot --force --force", live_reboot)
        self.assertIn("wait_for_usb_removal", live_reboot)
        self.assertNotIn("grub-install", live_reboot)
        self.assertNotRegex(live_reboot, r"(?m)^[ \t]*losetup[ \t]+-d")
        self.assertNotRegex(live_reboot, r"(?m)^[ \t]*fuser[ \t]+-k")
        self.assertNotIn("devos-set-boot-order", live_reboot)

    def test_live_installer_has_only_an_x11_session(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/share/xsessions/devos-install.desktop")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "build/includes.chroot/usr/share/wayland-sessions/devos-install.desktop")))
        session = read("build/includes.chroot/usr/local/sbin/devos-force-installer-session")
        self.assertIn("rm -f /usr/share/wayland-sessions/devos-install.desktop", session)

    def test_unpack_and_bootloader_targets_are_explicit(self):
        unpackfs = read("build/includes.chroot/etc/calamares/modules/unpackfs.conf")
        bootloader = read(
            "build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosbootloader/main.py"
        )
        finalize = read("build/includes.chroot/usr/local/sbin/devos-install-finalize")

        self.assertIn("/cdrom/casper/filesystem.squashfs", unpackfs)
        self.assertIn("--bootloader-id=DevOS", bootloader)
        self.assertIn("i386-pc", bootloader)
        self.assertIn("devos-install-efi-fallback", bootloader)
        # Boot review: GRUB must run in the installed target, not the live USB.
        self.assertIn("rootMountPoint", bootloader)
        self.assertIn("chroot", bootloader)
        self.assertIn("Bootloader failed", bootloader)
        self.assertIn("_grub_cfg_ok", bootloader)
        self.assertIn("dpkg --purge", finalize)
        self.assertIn("casper", finalize)
        self.assertIn("/etc/sddm.conf.d/autologin.conf", finalize)
        self.assertIn("calamares-welcome.desktop", finalize)
        # ~64% must stay fast: defer branding/swap; do not allow a 30-minute shell hang.
        shell_finalize = read("build/includes.chroot/etc/calamares/modules/shellprocess.conf")
        self.assertIn("timeout: 120", shell_finalize)
        self.assertIn("exit 0", shell_finalize)
        self.assertIn("stdbuf -oL -eL", finalize)
        self.assertIn("need-postinstall-deferred", finalize)
        self.assertIn("devos-postinstall.service", finalize)
        self.assertNotIn("timeout -k 10 240", finalize)
        self.assertNotIn("ensure_swapfile", finalize)
        # Soft warnings only — never abort before bootloader for home/account checks.
        self.assertIn("install-warnings", finalize)
        self.assertNotIn("Installation has not been marked complete", finalize)
        self.assertNotRegex(finalize, r"(?m)^[ \t]*exit 1[ \t]*$")
        initramfs = read("build/includes.chroot/etc/calamares/modules/shellprocess_initramfs.conf")
        self.assertIn("devos-install-initramfs", initramfs)
        self.assertNotIn("$UPD", initramfs)
        self.assertIn("timeout: 420", initramfs)
        self.assertNotIn("exit 0", initramfs)
        initramfs_bin = read("build/includes.chroot/usr/local/sbin/devos-install-initramfs")
        self.assertIn("update-initramfs", initramfs_bin)
        self.assertIn("need-initramfs-rebuild", initramfs_bin)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/local/sbin/devos-install-initramfs")))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/local/sbin/devos-postinstall-deferred")))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/etc/systemd/system/devos-postinstall.service")))
        english = read("build/includes.chroot/etc/calamares/modules/shellprocess_english_ui.conf")
        self.assertIn("|| true", english)
        aimodel = read("build/includes.chroot/etc/calamares/modules/contextualprocess_aimodel.conf")
        self.assertIn("|| true", aimodel)

    def test_identity_files_use_devos_name(self):
        os_release = read("build/includes.chroot/etc/os-release")
        lib_release = read("build/includes.chroot/usr/lib/os-release")
        lsb = read("build/includes.chroot/etc/lsb-release")
        casper = read("build/includes.chroot/etc/casper.conf")
        grub = read("build/includes.chroot/etc/default/grub.d/devos.cfg")
        plymouth = read("build/includes.chroot/usr/share/plymouth/themes/devos/devos.plymouth")
        branding = read("build/includes.chroot/etc/calamares/branding/devos/branding.desc")
        script = read("build/includes.chroot/usr/local/sbin/devos-apply-branding")

        self.assertIn('PRETTY_NAME="DevOS 26.04 LTS"', os_release)
        self.assertNotIn("Ubuntu", os_release)
        self.assertEqual(os_release, lib_release)
        self.assertIn('HOME_URL="https://imrandev.bd/"', os_release)
        self.assertIn('SUPPORT_URL="https://imrandev.bd/contact"', os_release)
        self.assertIn("DISTRIB_ID=DevOS", lsb)
        self.assertNotIn("Ubuntu", lsb)
        self.assertIn('export BUILD_SYSTEM="DevOS"', casper)
        self.assertNotIn("Ubuntu", casper)
        live_hook = read("build/hooks/04-branding.hook.chroot")
        self.assertIn('MP_QUIET="-q"', live_hook)
        self.assertIn('modprobe ${MP_QUIET}', live_hook)
        self.assertIn('GRUB_DISTRIBUTOR="DevOS"', grub)
        self.assertIn("Name=DevOS", plymouth)
        self.assertIn("ModuleName=two-step", plymouth)
        self.assertIn("bootloaderEntryName: DevOS", branding)
        self.assertIn('slideshow: "show.qml"', branding)
        self.assertIn("images:", branding)
        self.assertIn("windowExpanding: noexpand", branding)
        self.assertIn("windowSize: 800px,520px", branding)
        self.assertNotIn("windowExpanding: fullscreen", branding)
        self.assertNotIn("windowExpanding: normal", branding)
        self.assertIn('productIcon: "logo.png"', branding)
        self.assertIn("sidebar: qml", branding)
        # Bottom Next/Back must be height-pinned so Summary cannot clip it on laptops.
        navigation = read("build/includes.chroot/etc/calamares/branding/devos/calamares-navigation.qml")
        self.assertIn("Layout.minimumHeight: barHeight", navigation)
        self.assertIn("readonly property bool compact:", navigation)
        self.assertIn("ViewManager.nextLabel", navigation)
        self.assertIn("Shut down", navigation)
        self.assertIn("Restart", navigation)
        self.assertIn("127.0.0.1:41777", navigation)
        # Confirm must be a top-level Window (Item-in-navbar clipped under the progress bar).
        self.assertIn("function openFor(nextOp)", navigation)
        self.assertIn("id: powerWin", navigation)
        self.assertIn("id: installWin", navigation)
        self.assertIn('label: "Install Now"', navigation)
        self.assertIn("WindowStaysOnTopHint", navigation)
        self.assertIn("ApplicationModal", navigation)
        settings = read("build/includes.chroot/etc/calamares/settings.conf")
        self.assertIn("prompt-install: false", settings)
        stylesheet = read("build/includes.chroot/etc/calamares/branding/devos/stylesheet.qss")
        self.assertIn("font-size: 22px;", stylesheet)
        self.assertIn("QMessageBox", stylesheet)
        self.assertIn("Install Now", stylesheet)
        # Scenic photo is main-window only — QMessageBox must not inherit it.
        main_bg = stylesheet.split("QMainWindow", 1)[1].split("QDialog", 1)[0]
        self.assertIn("border-image: url(bg/04.jpg)", main_bg)
        msg = stylesheet.split("QMessageBox {", 1)[1].split("QMessageBox QLabel", 1)[0]
        self.assertIn("border-image: none", msg)
        self.assertIn("background-color: #0f172a", msg)
        summary = read("build/includes.chroot/etc/calamares/branding/devos/summaryq.qml")
        self.assertIn("InstallerBackground", summary)
        self.assertIn("INSTALL PREVIEW", summary)
        self.assertIn("packagechooserq@summaryreview", read("build/includes.chroot/etc/calamares/settings.conf"))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/local/bin/devos-installer-powerd")))
        self.assertIn("start_powerd", read("build/includes.chroot/usr/local/bin/devos-install-gui"))
        self.assertIn("themes/devos/theme.txt", read("build/lib-boot-iso.sh"))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/branding/grub/background.png")))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/share/grub/themes/devos/theme.txt")))
        self.assertNotIn("welcome.png", branding)
        self.assertIn("Name=DevOS", script)
        self.assertIn('GRUB_DISTRIBUTOR="DevOS"', script)
        self.assertIn("DevOS branding applied", script)

    def test_storage_step_and_complete_desktop(self):
        partition = read("build/includes.chroot/etc/calamares/modules/partition.conf")
        slideshow = read("build/includes.chroot/etc/calamares/branding/devos/show.qml")
        everyday = read("build/package-lists/16-everyday.list.chroot")
        installer = read("build/package-lists/20-installer.list.chroot")
        mime = read("build/includes.chroot/etc/xdg/mimeapps.list")
        code = read("build/includes.chroot/usr/local/bin/devos-code")
        win = read("build/includes.chroot/usr/share/applications/devos-winlayer.desktop")
        self.assertIn("Name=Windows apps", win)
        apk = read("build/includes.chroot/usr/share/applications/devos-apphub.desktop")

        self.assertIn("initialPartitioningChoice: erase", partition)
        self.assertIn("allowManualPartitioning: true", partition)
        self.assertIn("alwaysShowPartitionLabels: true", partition)
        show = read("build/includes.chroot/etc/calamares/settings.conf").split("- exec:")[0]
        # Calamares 3.3.5 keeps Next disabled on the disk page when it comes
        # before the welcome page (its requirements gate the whole sequence).
        self.assertLess(show.index("- welcome"), show.index("- partition"))
        self.assertLess(show.index("- partition"), show.index("- users"))
        # Without a layout, Erase disk made only the EFI partition.
        self.assertIn("partitionLayout:", partition)
        self.assertIn('mountPoint: "/"', partition)
        mount = read("build/includes.chroot/etc/calamares/modules/mount.conf")
        self.assertIn("extraMounts:", mount)
        self.assertIn("btrfsSubvolumes:", mount)
        self.assertIn("grub2-common", installer)
        boot_order = read("build/includes.chroot/usr/local/sbin/devos-set-boot-order")
        self.assertIn("PARTUUID", boot_order)
        self.assertIn("matching_entry", boot_order)
        self.assertIn("BootNext:", boot_order)
        self.assertNotIn("efibootmgr -B", boot_order)
        self.assertNotIn("Windows Boot Manager", boot_order)
        live_reboot = read("build/includes.chroot/usr/local/sbin/devos-live-reboot")
        self.assertIn("wait_for_usb_removal", live_reboot)
        self.assertIn("live_usb_still_present", live_reboot)
        self.assertIn("UNPLUG THE USB", live_reboot)
        self.assertNotIn("efibootmgr", live_reboot)
        homepage = read("build/includes.chroot/usr/local/bin/devos-open-homepage")
        self.assertIn("DEVOS_HOMEPAGE_READY_FILE", homepage)
        webapp = read("components/appwindow/devos_webapp.py")
        self.assertIn("if ok and not self.offline", webapp)
        self.assertIn("DEVOS_HOMEPAGE_READY_FILE", webapp)
        finalize = read("build/includes.chroot/usr/local/sbin/devos-install-finalize")
        self.assertIn("multi-user.target.wants/devos-force-installer.service", finalize)
        self.assertIn("install-finalize.ok", finalize)
        self.assertIn("boot_ui.py", finalize)
        boot_ui = read("build/includes.chroot/usr/local/share/devos/boot_ui.py")
        self.assertIn("detect_installed_devos", boot_ui)
        self.assertIn("probe_installed_devos", boot_ui)
        self.assertIn("FRESH_INSTALL_SEC", boot_ui)
        self.assertIn("continue_live_anyway", boot_ui)
        self.assertIn("show_installed", boot_ui)
        self.assertIn("Use live USB / Reinstall", boot_ui)
        install_done = read("build/includes.chroot/etc/calamares/modules/shellprocess_install_done.conf")
        self.assertIn("dontChroot: true", install_done)
        self.assertIn("/run/devos-install-completed", install_done)
        self.assertNotIn("chroot: false", install_done)
        features_shell = read("build/includes.chroot/etc/calamares/modules/shellprocess_features.conf")
        self.assertIn("installer-plan", features_shell)
        self.assertNotIn("apt-get purge", features_shell)
        self.assertNotIn("apt purge", features_shell)
        self.assertIn("never apt-purge", read(
            "build/includes.chroot/usr/local/share/devos/components/features/features_cli.py"))
        self.assertIn("SequentialAnimation", slideshow)
        # The slideshow cannot see install progress, so it must not draw a
        # step list or bar of its own (it used to cycle out of sync).
        self.assertNotIn("Copying DevOS onto the disk", slideshow)
        self.assertIn("Windows apps".upper(), slideshow)
        self.assertIn("falkon", everyday)
        self.assertIn("okular", everyday)
        self.assertIn("kate", everyday)
        self.assertIn("kwrite", everyday)
        self.assertIn("kinfocenter", everyday)
        self.assertIn("open_pc_properties", read("build/includes.chroot/usr/local/bin/devos-files"))
        self.assertIn("Name=About this PC", read("build/includes.chroot/usr/share/applications/devos-about.desktop"))
        help_desktop = read("build/includes.chroot/usr/share/applications/devos-help.desktop")
        self.assertIn("Name=Help Center", help_desktop)
        self.assertIn("Exec=/usr/local/bin/devos-about --help-center", help_desktop)
        editor = read("build/includes.chroot/usr/share/applications/devos-editor.desktop")
        self.assertIn("Name=Text Editor", editor)
        self.assertNotRegex(editor, r"(?i)^Name=Kate\b")
        studio = read("build/includes.chroot/usr/share/applications/devos-antigravity-studio.desktop")
        self.assertIn("Name=Antigravity IDE", studio)
        self.assertIn("NoDisplay=true", studio)
        self.assertIn("TryExec=/opt/antigravity/antigravity", studio)
        ag = read("build/includes.chroot/usr/share/applications/antigravity.desktop")
        self.assertIn("NoDisplay=true", ag)
        self.assertIn("TryExec=/opt/antigravity/antigravity", ag)
        ide = read("build/includes.chroot/usr/share/applications/antigravity-ide.desktop")
        self.assertIn("Hidden=true", ide)
        self.assertIn("NoDisplay=true", ide)
        kinfo_shim = read("build/includes.chroot/usr/local/bin/kinfocenter")
        self.assertIn("devos-about", kinfo_shim)
        self.assertIn("DEVOS_CLASSIC_INFO", kinfo_shim)
        hardware = read("build/package-lists/10-hardware.list.chroot")
        self.assertIn("fwupd", hardware)
        self.assertIn("pciutils", hardware)
        self.assertIn("usbutils", hardware)
        self.assertIn("lm-sensors", hardware)
        about_src = read("components/about/about.py")
        self.assertIn("def _page_energy", about_src)
        self.assertIn("def _page_audio", about_src)
        self.assertIn("def _page_pci", about_src)
        self.assertIn("def _page_sensors", about_src)
        self.assertIn("def _page_interrupts", about_src)
        self.assertIn("def _page_samba", about_src)
        self.assertIn("kcalc", everyday)
        self.assertIn("kde-spectacle", everyday)
        desktop = read("build/package-lists/15-desktop.list.chroot")
        session = read("build/includes.chroot/etc/sddm.conf.d/devos-theme.conf")
        install_gui = read("build/includes.chroot/usr/local/bin/devos-install-gui")
        chat = read("build/includes.chroot/usr/share/applications/devos-chat.desktop")
        panel = read("build/includes.chroot/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc")
        self.assertIn("kwin-x11", desktop)
        self.assertIn("xserver-xorg", desktop)
        self.assertIn("x11-xserver-utils", desktop)
        self.assertIn("sddm-theme-breeze", desktop)
        self.assertIn("GRUB_DISABLE_OS_PROBER: false", read("build/includes.chroot/etc/calamares/modules/grubcfg.conf"))
        self.assertIn("udisks2", desktop)
        self.assertIn("DisplayServer=x11", session)
        self.assertIn("Current=devos", session)
        self.assertIn("NOPASSWD:SETENV:", read("build/hooks/02-disable-services.hook.chroot"))
        self.assertIn("sudo -E -n", install_gui)
        self.assertNotIn("DevOS is not installed yet", install_gui)
        self.assertIn("QT_QPA_PLATFORM=", install_gui)
        self.assertIn("chmod 440 /etc/sudoers.d/devos", read("build/hooks/02-disable-services.hook.chroot"))
        self.assertIn("Name=DevOS AI", chat)
        self.assertIn("DevOS-Default.png", read("build/includes.chroot/usr/share/plasma/look-and-feel/org.devos.desktop/contents/layouts/org.kde.plasma.desktop-layout.js"))
        self.assertIn("org.devos.desktop", read("build/includes.chroot/usr/local/bin/devos-apply-desktop"))
        self.assertIn("Session=devos-install", read("build/includes.chroot/etc/sddm.conf.d/autologin.conf"))
        self.assertIn("zz-devos-install.conf", read("build/includes.chroot/usr/local/sbin/devos-force-installer-session"))
        self.assertIn("devos-install.desktop", read("build/includes.chroot/usr/local/sbin/devos-force-installer-session"))
        self.assertNotIn("TryExec=", read("build/includes.chroot/usr/share/xsessions/devos-install.desktop"))
        self.assertIn("ConditionKernelCommandLine=!boot=casper", read("build/includes.chroot/etc/systemd/system/devos-dashboard.service"))
        live = read("build/includes.chroot/usr/local/bin/devos-live-session")
        self.assertIn("calamares", live)
        self.assertNotIn("startplasma-x11", live)
        iso = read("build/lib-boot-iso.sh")
        self.assertIn("set timeout=", iso)
        self.assertIn("splash plymouth.theme=devos", iso)
        # Safe-graphics menu entries intentionally disable plymouth; the default entry must not.
        self.assertNotIn("plymouth.enable=0", iso.split("menuentry", 2)[1])
        safe_block = iso.split('menuentry "DevOS · Safe Graphics"', 1)[1].split("menuentry", 1)[0]
        self.assertIn("plymouth.enable=0", safe_block)
        self.assertIn("xdotool", read("build/package-lists/20-installer.list.chroot"))
        plymouth_theme = read("build/includes.chroot/usr/share/plymouth/themes/devos/devos.plymouth")
        # two-step plugin (Ubuntu spinner) — script DRM path stayed blank on Intel TVs.
        self.assertIn("ModuleName=two-step", plymouth_theme)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/share/plymouth/themes/devos/animation-0001.png")))
        boot_ui_src = read("build/includes.chroot/usr/local/share/devos/boot_ui.py")
        self.assertIn("INTRO_SEC", boot_ui_src)
        self.assertIn("_paint_motion_intro", boot_ui_src)
        self.assertIn("DevOS Motion", boot_ui_src)
        self.assertIn('mode = "intro"', boot_ui_src)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/share/plymouth/themes/devos/track.png")))
        self.assertGreater(os.path.getsize(os.path.join(
            ROOT, "build/includes.chroot/usr/share/plymouth/themes/devos/track.png")), 100)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/share/plymouth/themes/devos/thumb.png")))
        self.assertGreater(os.path.getsize(os.path.join(
            ROOT, "build/includes.chroot/usr/share/plymouth/themes/devos/thumb.png")), 200)

        self.assertNotIn("ModuleName=text", read("build/includes.chroot/usr/local/sbin/devos-apply-branding"))
        self.assertIn("boot_ui.py", live)
        boot_ui = read("build/includes.chroot/usr/local/share/devos/boot_ui.py")
        self.assertIn("Try DevOS", boot_ui)
        self.assertIn("Safe Graphics", boot_ui)
        self.assertIn("Premium Setup", boot_ui)
        self.assertIn("devos-preferred-usertype", boot_ui)
        # First screen must share Calamares welcome look (photo plates + WELCOME intro).
        self.assertIn("InstallerBackground", boot_ui)  # docstring / comment intent
        self.assertIn("/etc/calamares/branding/devos", boot_ui)
        self.assertIn("WELCOME", boot_ui)
        self.assertIn("load_backgrounds", boot_ui)
        # Overlay must get out of the way once Calamares is running.
        self.assertIn("calamares_running", boot_ui)
        self.assertIn("release_overlay", boot_ui)
        self.assertIn("force_power", boot_ui)
        self.assertIn("confirm_power", boot_ui)
        self.assertIn("powerConfirmScrim", boot_ui)
        self.assertIn("confirmLogout=true", read("build/includes.chroot/etc/xdg/ksmserverrc"))
        self.assertIn("header_wrap", boot_ui)
        self.assertIn("root.addStretch(1)", boot_ui)
        self.assertIn("QScrollArea", boot_ui)
        # Real motion is the X11 intro; Plymouth uses two-step (not blank script).
        boot_ui_src = read("build/includes.chroot/usr/local/share/devos/boot_ui.py")
        self.assertIn("_paint_motion_intro", boot_ui_src)
        self.assertIn("INTRO_SEC", boot_ui_src)
        self.assertIn("ModuleName=two-step", read(
            "build/includes.chroot/usr/share/plymouth/themes/devos/devos.plymouth"))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/local/sbin/devos-refresh-plymouth")))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/share/plymouth/themes/devos/animation-0001.png")))
        self.assertIn("plymouth.use-simpledrm", read(
            "build/includes.chroot/etc/calamares/modules/grubcfg.conf"))
        gui = read("build/includes.chroot/usr/local/bin/devos-install-gui")
        self.assertIn("flock -w 45", gui)
        usertype_qml = read("build/includes.chroot/etc/calamares/branding/devos/usertypeq.qml")
        self.assertIn("preferred-usertype.js", usertype_qml)
        self.assertIn("loadSavedKind", usertype_qml)
        features_qml = read("build/includes.chroot/etc/calamares/branding/devos/featuresq.qml")
        self.assertIn("loadSavedPicks", features_qml)
        self.assertIn("rememberedFeaturesKind", features_qml)
        # Custom ticks must survive Back/Next; do not re-preset when kind is unchanged.
        self.assertIn("if (kind === appliedKind)", features_qml)
        storage_qml = read("build/includes.chroot/etc/calamares/branding/devos/storageq.qml")
        self.assertIn("loadSavedPlan", storage_qml)
        self.assertIn("devos_storage_selected_json", storage_qml)
        self.assertIn("apply_preferred_usertype", read(
            "build/includes.chroot/usr/local/bin/devos-install-gui"))
        self.assertIn("Try DevOS / Install", iso)
        self.assertIn("DevOS · Safe Graphics", iso)
        self.assertIn("libxcb-cursor0", desktop)
        self.assertIn("x11-utils", desktop)
        branding_hook = read("build/hooks/04-branding.hook.chroot")
        self.assertIn("Wait until the screen is black, then remove the USB.", branding_hook)
        self.assertIn("update-alternatives --install", branding_hook)
        self.assertIn("/usr/share/plymouth/themes/devos/devos.plymouth", branding_hook)
        self.assertIn(r"s/\r$//", branding_hook)
        self.assertIn("two-step.so", branding_hook)
        self.assertIn("branding: devos", read("build/includes.chroot/usr/local/bin/devos-install-gui"))
        self.assertIn("ubuntu-desktop-bootstrap", read("build/hooks/02-disable-services.hook.chroot"))
        # Icons-only taskbar: group by app so multi-window IDEs stay one icon.
        self.assertIn("org.kde.plasma.icontasks", panel)
        self.assertIn("groupingStrategy=1", panel)
        self.assertIn("sortingStrategy=1", panel)
        self.assertIn("onlyGroupWhenFull=false", panel)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/local/bin/devos-tray-overflow")))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/etc/xdg/autostart/devos-tray-overflow.desktop")))
        self.assertIn("devos-tray-overflow", read("build/includes.chroot/usr/local/bin/devos-apply-desktop"))
        self.assertIn("hiddenItems=", panel)
        self.assertIn("shownItems=", panel)
        self.assertIn("showAllItems=false", panel)
        overflow = read("build/includes.chroot/usr/local/bin/devos-tray-overflow")
        self.assertIn("showAllItems", overflow)
        self.assertIn("registered_tray_ids", overflow)
        # Volume + brightness must sit under ^, not as forever-visible panel icons.
        self.assertIn("org.kde.plasma.volume", overflow)
        self.assertIn("org.kde.plasma.brightness", overflow)
        self.assertIn("org.kde.plasma.volume", panel)
        self.assertIn("org.kde.plasma.brightness", panel)
        self.assertIn("devos-windows.desktop", panel)
        self.assertIn("devos-thispc.desktop", panel)
        self.assertIn("Devices and drives", read("build/includes.chroot/usr/local/bin/devos-files"))
        self.assertIn("python3-pyqt5", desktop)
        self.assertIn("groupPopups=true", panel)
        self.assertIn("invokeShortcut string:Overview", read("build/includes.chroot/usr/local/bin/devos-show-windows"))
        self.assertIn("icon=devos-logo", panel)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/share/icons/hicolor/48x48/apps/devos-logo.png")))
        look = read("build/includes.chroot/etc/skel/.config/kdeglobals")
        self.assertIn("ColorScheme=DevOS-Light", look)
        self.assertIn("Enabled=false", read("build/includes.chroot/etc/xdg/kwalletrc"))
        self.assertIn("SavePasswordsOn=false", read("build/includes.chroot/etc/skel/.config/falkon/profiles/default/settings.ini"))
        self.assertIn("Theme=Papirus", look)
        self.assertNotIn("Papirus-Dark", look)
        self.assertIn("widgetStyle=Breeze", look)
        self.assertIn("breeze-light", read("build/includes.chroot/etc/skel/.config/plasmarc"))
        self.assertIn("ColorScheme=DevOS-Light", read("build/includes.chroot/usr/share/plasma/look-and-feel/org.devos.desktop/contents/defaults"))
        self.assertIn("widgetStyle=Breeze", read("build/includes.chroot/usr/share/plasma/look-and-feel/org.devos.desktop/contents/defaults"))
        style = read("build/includes.chroot/etc/xdg/plasma-workspace/env/devos-style.sh")
        self.assertNotIn("QT_STYLE_OVERRIDE=kvantum", style)
        apply = read("build/includes.chroot/usr/local/bin/devos-apply-desktop")
        self.assertIn("DevOS-Light", apply)
        self.assertIn("widgetStyle Breeze", apply)
        self.assertIn("devos-heal-theme", apply)
        heal = read("build/includes.chroot/usr/local/bin/devos-heal-theme")
        self.assertIn("widgetStyle Breeze", heal)
        self.assertIn("Colors:Complementary", heal)
        self.assertIn("whitesurdark", heal)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/local/bin/devos-heal-theme-watch")))
        self.assertIn("devos-heal-theme-watch", read("build/includes.chroot/etc/xdg/autostart/devos-heal-theme.desktop"))
        switcher = read("components/settings/theme_switcher.py")
        self.assertIn('style = "kvantum" if mode == "mac" else "Breeze"', switcher)
        self.assertIn("write_complementary_overlay", switcher)
        self.assertIn("devos-heal-theme", switcher)
        apply = read("build/includes.chroot/usr/local/bin/devos-apply-desktop")
        self.assertIn("Colors:Complementary", apply)
        self.assertIn("want_mode=dark", apply)
        self.assertIn("want_mode=light", apply)
        self.assertIn("plasma-apply-colorscheme DevOS", apply)
        skel = read("build/includes.chroot/etc/skel/.config/kdeglobals")
        self.assertIn("Colors:Complementary", skel)
        self.assertIn('"theme": "light"', read("build/includes.chroot/etc/skel/.config/devos/settings.json"))
        dash = read("components/dashboard/static/style.css")
        self.assertIn('html[data-theme="light"]', dash)
        self.assertIn('html[data-theme="dark"]', dash)
        self.assertIn("data-theme", read("components/dashboard/static/app.js"))
        self.assertIn("appearance_theme", read("components/dashboard/dashboard_server.py"))
        self.assertIn("papirus-icon-theme", desktop)
        self.assertIn("qt5-style-kvantum", desktop)
        hook = read("build/hooks/02-disable-services.hook.chroot")
        self.assertIn("bluetooth.service", hook)
        self.assertIn("podman-restart.service", hook)
        self.assertIn("podman-auto-update.service", hook)
        wifi = read("build/includes.chroot/etc/NetworkManager/conf.d/98-devos-wifi.conf")
        self.assertIn("Hidden=true", read("build/includes.chroot/etc/xdg/autostart/devos-dashboard.desktop"))
        self.assertIn("--no-browser", read("build/includes.chroot/etc/xdg/autostart/devos-dashboard.desktop"))
        self.assertIn("wifi.powersave=2", wifi)
        tune = read("build/includes.chroot/usr/local/sbin/devos-tune-hardware")
        self.assertIn("performance", tune)
        self.assertIn("schedutil", tune)
        self.assertIn("mq-deadline", tune)
        self.assertIn("bfq", tune)
        self.assertIn("PERCENT=50", read("build/includes.chroot/etc/default/zramswap"))
        self.assertIn("AnimationDurationFactor=0.35",
                      read("build/includes.chroot/etc/xdg/kdeglobals"))
        self.assertIn("LimitNOFILE=524288",
                      read("build/includes.chroot/etc/systemd/system/user@.service.d/devos-agents.conf"))
        self.assertIn("commit=60", read("build/includes.chroot/etc/calamares/modules/mount.conf"))
        self.assertIn("default.clock.quantum",
                      read("build/includes.chroot/etc/pipewire/pipewire.conf.d/50-devos-desktop.conf"))
        self.assertIn("size=35%",
                      read("build/includes.chroot/etc/systemd/system/tmp.mount.d/devos-size.conf"))
        self.assertIn("ManagedOOMMemoryPressure=auto",
                      read("build/includes.chroot/etc/systemd/user/app.slice.d/20-devos-responsiveness.conf"))
        ai_core = read("build/includes.chroot/etc/systemd/system/devos-ai-core.service")
        self.assertIn("MemoryHigh=40%", ai_core)
        self.assertIn("devos-agents.slice", ai_core)
        self.assertIn("DEVOS_AI_IDLE_TIMEOUT=1800", ai_core)
        self.assertIn("HandleLidSwitchExternalPower=ignore",
                      read("build/includes.chroot/etc/systemd/logind.conf.d/devos-no-auto-power.conf"))
        self.assertIn("devos-agent-endurance",
                      read("build/includes.chroot/etc/systemd/user/devos-agent-endurance.service"))
        self.assertIn('Automatic-Reboot "false"',
                      read("build/includes.chroot/etc/apt/apt.conf.d/99devos-no-auto-reboot"))
        self.assertIn("tcp_congestion_control = bbr",
                      read("build/includes.chroot/etc/sysctl.d/99-devos-heavy-load.conf"))
        self.assertIn("fs.inotify.max_user_watches = 1048576",
                      read("build/includes.chroot/etc/sysctl.d/99-devos-heavy-load.conf"))
        self.assertIn("MaxFPS=60", read("build/includes.chroot/etc/xdg/kwinrc"))
        perf = read("build/hooks/03-tune-performance.hook.chroot")
        self.assertIn("devos-hardware.service", perf)
        self.assertIn("thermald.service", perf)
        self.assertIn("want tmp.mount", perf)
        self.assertIn("redis-server", read("build/hooks/02-disable-services.hook.chroot"))
        self.assertIn("cups-browsed.service", read("build/hooks/02-disable-services.hook.chroot"))
        self.assertNotIn("\nearlyoom\n", "\n" + read("build/package-lists/00-base.list.chroot") + "\n")
        self.assertNotIn("libreoffice-gnome",
                         read("build/package-lists/18-offline-essentials.list.chroot"))
        ethernet = read("build/includes.chroot/etc/NetworkManager/conf.d/99-devos-ethernet.conf")
        self.assertIn("unmanaged-devices=", ethernet)
        ethernet_link = read("build/includes.chroot/etc/NetworkManager/system-connections/devos-ethernet.nmconnection")
        self.assertIn("method=auto", ethernet_link)
        self.assertIn("autoconnect=true", ethernet_link)
        self.assertIn("dns=1.1.1.1;8.8.8.8;", ethernet_link)
        self.assertIn('for unit in systemd-resolved.service NetworkManager.service', hook)
        self.assertIn("multi-user.target.wants/${unit}", hook)
        self.assertIn("chmod 755", hook)
        self.assertIn("/usr/local/bin/devos-live-session", hook)
        self.assertIn("renderer: NetworkManager", read("build/includes.chroot/etc/netplan/01-network-manager-all.yaml"))
        bring_up = read("build/includes.chroot/usr/local/sbin/devos-bring-up-network")
        self.assertIn("nmcli connection up", bring_up)
        self.assertNotIn("nmcli device connect", bring_up)
        self.assertIn("stub-resolv.conf", bring_up)
        self.assertIn("1.1.1.1", bring_up)
        self.assertIn("devos-network.service", hook)
        self.assertIn("systemd-resolved.service", hook)
        self.assertIn("stub-resolv.conf", hook)
        self.assertIn("DNS=1.1.1.1 8.8.8.8", read("build/includes.chroot/etc/systemd/resolved.conf.d/devos.conf"))
        self.assertIn("systemd-resolved", read("build/package-lists/10-hardware.list.chroot"))
        iso_script = read("build/build-iso.sh")
        self.assertIn('rm -rf "${CHROOT_DIR}/home/devos"', iso_script)
        self.assertNotIn("${CHROOT_DIR}/home/devos/Desktop", iso_script)
        self.assertIn("dnsmasq.service", hook)
        self.assertIn("stub-resolv.conf", iso_script)
        self.assertIn("devos-install-llm", read("build/build-iso.sh"))
        llm = read("build/includes.chroot/usr/local/sbin/devos-install-llm")
        self.assertIn("qwen2.5-1.5b-instruct-q4_k_m.gguf", llm)
        self.assertIn("qwen2.5-1.5b-instruct-q4_k_m.gguf", read("components/ai-core/model_catalog.py"))
        self.assertNotIn("local assistant running completely offline", read("components/ai-core/server.py"))
        self.assertIn("ntfs-3g", installer)
        self.assertIn("os-prober", installer)
        self.assertIn("application/pdf=org.kde.okular.desktop", mime)
        self.assertIn("x-scheme-handler/https=devos-browser.desktop", mime)
        chrome = read("build/includes.chroot/usr/local/sbin/devos-install-chrome")
        self.assertIn("google-chrome-stable_current_amd64.deb", chrome)
        self.assertIn("offline-apt/chrome.deb", chrome)
        self.assertIn("wait_for_network", chrome)
        self.assertIn("cache-optional-apps.py\" --vendor-only", read("build/build-iso.sh"))
        self.assertIn("network-online.target", read(
            "build/includes.chroot/etc/systemd/system/devos-features.service"))
        browser = read("build/includes.chroot/usr/local/bin/devos-browser")
        self.assertIn("--accept-lang", browser)
        self.assertIn("cdn-cgi/trace", browser)
        self.assertIn("en-US,en,bn-BD,bn", browser)
        self.assertIn("--guest", browser)
        self.assertIn("new-guest-window", read("build/includes.chroot/usr/local/share/applications/google-chrome.desktop"))
        chrome_privacy = read("build/includes.chroot/etc/opt/chrome/policies/managed/devos-privacy.json")
        self.assertIn('"BrowserGuestModeEnabled": true', chrome_privacy)
        chrome_perf = read("build/includes.chroot/etc/opt/chrome/policies/managed/devos-performance.json")
        self.assertIn('"HighEfficiencyModeEnabled": true', chrome_perf)
        self.assertIn('"MemorySaverModeSavings": 2', chrome_perf)
        self.assertIn('"TotalMemoryLimitMb"', chrome_perf)
        self.assertNotIn("--process-per-site", browser)
        self.assertNotIn("--renderer-process-limit=", browser)
        self.assertIn("--disk-cache-size=", browser)
        self.assertNotIn("MemorySaverModeAvailability", browser)
        self.assertNotIn("IntensiveWakeUpThrottling", browser)
        self.assertNotIn("--disable-background-networking", browser)
        self.assertIn('"BackgroundModeEnabled": false', chrome_perf)
        self.assertIn('"BackgroundAppUpdateEnabled": false', chrome_perf)
        bg = read("build/includes.chroot/etc/systemd/user/background.slice.d/20-devos-responsiveness.conf")
        self.assertIn("CPUWeight=10", bg)
        self.assertIn("MemoryHigh=18%", bg)
        # Chrome tune runs on first boot (deferred) so install 64% stays fast.
        self.assertIn("devos-chrome-tune", read("build/includes.chroot/usr/local/sbin/devos-postinstall-deferred"))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/local/sbin/devos-chrome-tune")))
        self.assertIn("parse_pss_kb", read("components/taskman/taskman.py"))
        self.assertIn("fonts-noto-core", desktop)
        self.assertIn(".config/google-chrome", chrome)
        self.assertIn("code", code)
        self.assertNotIn("exec kate", code.lower())
        self.assertIn("code_setup.py", code)
        self.assertIn("Default Light Modern", read("build/includes.chroot/etc/skel/.config/Code/User/settings.json"))
        self.assertIn("Icon=devos-code", read("build/includes.chroot/usr/share/applications/devos-code.desktop"))
        self.assertIn("StartupWMClass=code", read("build/includes.chroot/usr/share/applications/devos-code.desktop"))
        self.assertIn("nameShort", read("build/includes.chroot/usr/local/sbin/devos-install-code"))
        self.assertIn("DevOS Code", read("build/includes.chroot/usr/local/sbin/devos-install-code"))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/local/share/devos/components/code/code_setup.py")))
        self.assertIn("devos-settings.desktop", read("build/includes.chroot/usr/local/share/devos/apply-ui.js"))
        term = read("build/includes.chroot/usr/share/applications/devos-terminal.desktop")
        self.assertIn("Name=Terminal", term)
        self.assertIn("Exec=konsole", term)
        debrand = read("build/includes.chroot/usr/local/sbin/devos-debrand-desktop")
        self.assertIn('"code"', debrand)
        self.assertIn('"org.kde.spectacle"', debrand)
        self.assertIn('"org.kde.klipper"', debrand)
        self.assertIn("fonts-jetbrains-mono", read("build/package-lists/30-developer.list.chroot"))
        self.assertIn("11434", code)
        # .exe opens directly. App Hub sends a chosen .apk to the same opener.
        self.assertIn("/usr/local/bin/devos-open-app", win)
        self.assertIn("wine32:i386", read("build/package-lists/50-wine.list.chroot"))
        self.assertIn("Exec=/usr/local/bin/devos-apphub %f", apk)
        hub = read("build/includes.chroot/usr/local/bin/devos-apphub")
        self.assertIn('OPEN="/usr/local/bin/devos-open-app"', hub)
        self.assertIn('exec "$OPEN" "$@"', hub)
        self.assertNotIn("/usr/lib/devos", win)
        self.assertNotIn("/usr/lib/devos", apk)

        # Boot & installation resilience tests
        root_grub = read("build/grub.cfg")
        self.assertIn("username=devos hostname=devos", root_grub)
        self.assertIn("devos_root", root_grub)

        efi_fallback = read("build/includes.chroot/usr/local/sbin/devos-install-efi-fallback")
        self.assertIn("grub-mkrelpath /boot/grub", efi_fallback)
        self.assertIn("grub-script-check", efi_fallback)
        self.assertIn("/EFI/ubuntu", efi_fallback)
        self.assertIn("/EFI/DevOS", efi_fallback)
        self.assertIn("BOOTX64.EFI", efi_fallback)

        finalize_script = read("build/includes.chroot/usr/local/sbin/devos-install-finalize")
        self.assertIn("/vmlinuz", finalize_script)
        self.assertIn("/initrd.img", finalize_script)
        self.assertIn("echo \"btrfs\" >> /etc/initramfs-tools/modules", finalize_script)


class TestDevOSIdentity(unittest.TestCase):
    """Users see DevOS, not the parts it is built from."""

    def test_desktop_names_are_devos(self):
        debrand = read("build/includes.chroot/usr/local/sbin/devos-debrand-desktop")
        self.assertIn('rename_session /usr/share/xsessions/plasma.desktop "DevOS"', debrand)
        self.assertIn('"org.kde.dolphin": (', debrand)
        self.assertIn("File Explorer", debrand)
        self.assertIn('"org.kde.konsole": (', debrand)
        self.assertIn('"org.kde.kcalc": (', debrand)
        self.assertIn("Calculator", debrand)
        self.assertIn("devos-calculator.desktop", debrand)
        self.assertIn("Snipping Tool", debrand)
        self.assertIn("PDF Viewer", debrand)
        self.assertIn("Zip Folders", debrand)
        # Hide-only pass must not wipe friendly Name= (old bug restored KCalc).
        self.assertIn("hide=app_id in HIDE", debrand)
        self.assertIn(r'\bKCalc\b', debrand)
        self.assertIn(r'\bDolphin\b', debrand)
        self.assertIn(r'\bKate\b', debrand)
        self.assertIn("Engine=none", debrand)
        self.assertIn("devos-debrand-desktop", read("build/includes.chroot/usr/local/sbin/devos-apply-branding"))
        for desk in (
            "devos-calculator.desktop",
            "devos-pdf.desktop",
            "devos-photos.desktop",
            "devos-zip.desktop",
            "devos-snip.desktop",
            "devos-paint.desktop",
            "devos-scanner.desktop",
            "devos-charmap.desktop",
            "devos-magnifier.desktop",
            "devos-passwords.desktop",
        ):
            text = read(f"build/includes.chroot/usr/share/applications/{desk}")
            self.assertIn("Name=", text)
            self.assertNotRegex(
                text,
                r"(?i)Name=(KCalc|Dolphin|Kate|Konsole|Spectacle|Okular|Gwenview|Ark|"
                r"KolourPaint|Skanlite|KCharSelect|KMag|KeePassXC|btop\+\+|Filelight|FileZilla)\b",
            )
        self.assertIn("Paint", debrand)
        self.assertIn("Scanner", debrand)
        self.assertIn("Character Map", debrand)
        self.assertIn("kvantummanager", debrand)
        # Settings → General Behavior must not say "Plasma" to normal people.
        self.assertIn("brand_settings_qml", debrand)
        self.assertIn("Allow the desktop to show:", debrand)
        self.assertIn('i18nc("@title:group", "Desktop")', debrand)
        self.assertIn(r'(?<![\w.])Plasma\b", "Desktop"', debrand)

    def test_english_ui_forced_systemwide(self):
        force = read("build/includes.chroot/usr/local/sbin/devos-force-english-ui")
        self.assertIn("EN_LOCALE='en_US.UTF-8'", force)
        self.assertIn("LC_TIME=${EN_LOCALE}", force)
        self.assertIn("LANGUAGE=en_US", force)
        self.assertIn("LC_NUMERIC=${EN_LOCALE}", force)
        self.assertIn("/etc/xdg/kdeglobals", force)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "build/includes.chroot/usr/local/sbin/devos-force-english-ui")))
        locale = read("build/includes.chroot/etc/default/locale")
        self.assertIn("LANG=en_US.UTF-8", locale)
        self.assertIn("LC_TIME=en_US.UTF-8", locale)
        plasma = read("build/includes.chroot/etc/xdg/plasma-localerc")
        self.assertIn("LC_TIME=en_US.UTF-8", plasma)
        self.assertIn("[Translations]", plasma)
        kde = read("build/includes.chroot/etc/xdg/kdeglobals")
        self.assertIn("[Locale]", kde)
        self.assertIn("Country=us", kde)
        english_job = read("build/includes.chroot/etc/calamares/modules/shellprocess_english_ui.conf")
        self.assertIn("devos-force-english-ui", english_job)
        apply = read("build/includes.chroot/usr/local/bin/devos-apply-desktop")
        self.assertIn("devos-force-english-ui", apply)
        env = read("build/includes.chroot/etc/xdg/plasma-workspace/env/devos-style.sh")
        self.assertIn("LC_TIME=en_US.UTF-8", env)
        self.assertIn("LC_NUMERIC=en_US.UTF-8", env)
        envd = read("build/includes.chroot/etc/environment.d/90devos-english-ui.conf")
        self.assertIn("LC_TIME=en_US.UTF-8", envd)
        self.assertIn("LC_NUMERIC=en_US.UTF-8", envd)
        settings = read("build/includes.chroot/etc/calamares/settings.conf")
        self.assertIn("shellprocess@english-ui", settings)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/etc/calamares/modules/shellprocess_english_ui.conf")))
        dash = read("components/dashboard/static/index.html")
        self.assertNotIn('value="bn_BD.UTF-8"', dash)
        browser = read("build/includes.chroot/usr/local/bin/devos-browser")
        self.assertIn('lang="en-US,en,bn-BD,bn"', browser)

    def test_grub_boots_without_waiting(self):
        grub = read("build/includes.chroot/etc/calamares/modules/grubcfg.conf")
        self.assertIn("GRUB_TIMEOUT: 0", grub)
        self.assertIn("GRUB_RECORDFAIL_TIMEOUT: 0", grub)
        self.assertIn('OS="${GRUB_DISTRIBUTOR}"', read("build/hooks/04-branding.hook.chroot"))

    def test_assistant_is_devos_ai(self):
        server = read("components/ai-core/server.py")
        self.assertIn("You are DevOS AI", server)
        self.assertIn("You are not Claude", server)
        code = read("build/includes.chroot/etc/skel/.config/Code/User/settings.json")
        self.assertIn('"chat.disableAIFeatures": true', code)

    def test_password_is_optional(self):
        users = read("build/includes.chroot/etc/calamares/modules/usersq.conf")
        self.assertIn("presets:", users)
        self.assertIn("doAutologin: true", users)
        finalize = read("build/includes.chroot/usr/local/sbin/devos-install-finalize")
        self.assertIn("zz-devos-autologin.conf", finalize)
        self.assertIn("Windows-style automatic sign-in", finalize)
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/usr/local/bin/devos-open-homepage")))
        self.assertTrue(os.path.isfile(os.path.join(
            ROOT, "build/includes.chroot/etc/xdg/autostart/devos-homepage.desktop")))


    def test_slideshow_ai_era_collection_has_over_100_images(self):
        slideshow_dir = os.path.join(ROOT, "build/includes.chroot/usr/share/wallpapers/DevOS-Slideshow")
        self.assertTrue(os.path.isdir(slideshow_dir))
        files = os.listdir(slideshow_dir)
        ai_images = [f for f in files if f.startswith("AI_") and f.endswith(".jpg")]
        self.assertGreaterEqual(len(ai_images), 100)
        total_images = [f for f in files if f.endswith(".jpg") or f.endswith(".png")]
        self.assertGreaterEqual(len(total_images), 130)


if __name__ == "__main__":
    unittest.main()
