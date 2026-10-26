from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components/ai-core"))
import server


class ResponsivenessTests(unittest.TestCase):
    def test_snapshot_guard_checks_the_actual_filesystem_not_a_shipped_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            config=base/'root-config';config.write_text('FSTYPE="btrfs"')
            stat_bin=base/'stat';stat_bin.write_text('#!/bin/sh\nprintf "%s\\n" "$DEVOS_TEST_FS"\n');stat_bin.chmod(0o755)
            script=(ROOT/'build/includes.chroot/usr/local/sbin/devos-snapshots-ready').read_text().replace('/etc/snapper/configs/root',str(config))
            for filesystem,expected in (('btrfs',0),('ext2/ext3',1),('overlayfs',1)):
                env=dict(os.environ,PATH=str(base)+':/usr/bin:/bin',DEVOS_TEST_FS=filesystem)
                self.assertEqual(subprocess.run(['sh'],input=script,text=True,env=env).returncode,expected)
            config.unlink()
            self.assertEqual(subprocess.run(['sh'],input=script,text=True,env=env).returncode,1)

    def test_ext4_finalize_removes_only_the_inapplicable_root_snapshot_template(self):
        source=(ROOT/'build/includes.chroot/usr/local/sbin/devos-install-finalize').read_text()
        script=source.split('# The image carries a Btrfs Snapper template.')[1].split('echo "==> Applying')[0]
        script='# The image carries a Btrfs Snapper template.'+script
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);config=base/'etc/snapper/configs/root'
            config.parent.mkdir(parents=True);config.write_text('root template')
            data=config.with_name('data');data.write_text('user data config')
            defaults=base/'etc/default/snapper';defaults.parent.mkdir();defaults.write_text('SNAPPER_CONFIGS="root"\n')
            binary=base/'stat';binary.write_text('#!/bin/sh\necho ext2/ext3\n');binary.chmod(0o755)
            script=script.replace('/etc/',str(base/'etc')+'/')
            env=dict(os.environ,PATH=str(base)+':/usr/bin:/bin')
            subprocess.run(['bash'],input=script,text=True,env=env,check=True)
            self.assertFalse(config.exists())
            self.assertEqual(data.read_text(),'user data config')
            self.assertIn('SNAPPER_CONFIGS=""',defaults.read_text())

    def test_parallel_models_share_default_cpu_budget(self):
        with patch.dict(os.environ, {}, clear=True):
            for logical in (1, 2, 4, 8, 20, 64):
                for slots in (1, 2, 4):
                    gen, batch = server.thread_plan(logical, max(1, logical // 2), slots)
                    self.assertGreaterEqual(gen, 1)
                    self.assertGreaterEqual(batch, gen)
                    if logical > slots:
                        self.assertLessEqual(batch * slots, logical - (1 if logical > 2 else 0))

    def test_model_memory_remains_reclaimable_on_big_and_small_pcs(self):
        for ram in (4, 8, 16, 32, 128):
            kwargs = server.llama_speed_kwargs("chat", ram, 2, 0, logical=8, physical=4)
            self.assertFalse(kwargs["use_mlock"])

    def test_ai_does_not_change_users_power_profile_by_default(self):
        boost = server._CpuBoost()
        with patch.dict(os.environ, {}, clear=True), patch.object(boost, "_paths") as paths:
            boost.enter()
            boost.leave()
            paths.assert_not_called()

    def test_hardware_policy_selects_supported_schedulers_and_distinguishes_hdd(self):
        with tempfile.TemporaryDirectory() as tmp:
            sysroot = Path(tmp)
            def write(relative, content):
                p = sysroot / relative
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
                return p
            governor = write("devices/system/cpu/cpu0/cpufreq/scaling_governor", "powersave")
            write("devices/system/cpu/cpu0/cpufreq/scaling_available_governors", "powersave schedutil")
            for name, rotating, available in (("nvme0n1", "0", "[mq-deadline] none"),
                    ("sda", "0", "[none] mq-deadline"), ("sdb", "1", "[mq-deadline] bfq"),
                    ("sdc", "0", "[none]")):
                write(f"block/{name}/queue/rotational", rotating)
                write(f"block/{name}/queue/scheduler", available)
                write(f"block/{name}/queue/read_ahead_kb", "0")
            script = (ROOT / "build/includes.chroot/usr/local/sbin/devos-tune-hardware").read_text()
            # Only an isolated fixture is written, never the host's sysfs.
            script = script.replace("/sys/", str(sysroot) + "/")
            subprocess.run(["bash"], input=script, text=True, check=True)
            self.assertEqual(governor.read_text().strip(), "schedutil")
            for name, scheduler, ahead in (("nvme0n1", "none", "128"),
                    ("sda", "mq-deadline", "128"), ("sdb", "bfq", "1024"), ("sdc", "[none]", "128")):
                self.assertEqual((sysroot / f"block/{name}/queue/scheduler").read_text().strip(), scheduler)
                self.assertEqual((sysroot / f"block/{name}/queue/read_ahead_kb").read_text().strip(), ahead)


if __name__ == "__main__":
    unittest.main(verbosity=2)
