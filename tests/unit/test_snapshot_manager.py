#!/usr/bin/env python3
"""Snapper (btrfs) and Timeshift (ext4) restore-point backends."""

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "settings"))

from snapshot_manager import SnapshotManager, parse_timeshift_list  # noqa: E402


def test_parse_timeshift_list():
    text = """
Num     Name                 Tags  Description
------------------------------------------------------------------------------
0    >  2026-11-07_12-00-00  O  Before package changes
1       2026-11-06_09-30-00  O  Manual
"""
    points = parse_timeshift_list(text)
    assert len(points) == 2
    assert points[0]["id"] == "2026-11-07_12-00-00"
    assert points[0]["backend"] == "timeshift"
    assert "Before package" in points[0]["description"]


def test_ext4_does_not_copy_the_system_onto_a_data_disk():
    calls = []

    def runner(argv):
        calls.append(argv)
        return 0, "ok", ""

    mgr = SnapshotManager(runner=runner, euid=0, fstype="ext4", tools={"timeshift": True})
    res = mgr.create_restore_point("Before package changes")
    assert res["status"] == "UNAVAILABLE"
    assert calls == []
    assert "another disk" in res["message"]


def test_package_hook_does_not_start_timeshift_on_ext4():
    hook = (ROOT / "build/includes.chroot/usr/local/sbin/devos-snapshot-pre-upgrade").read_text(encoding="utf-8")
    assert "timeshift" not in hook
    assert "exit 0" in hook


def test_btrfs_snapper_unchanged():
    def runner(argv):
        if argv[:3] == ["snapper", "-c", "root"] and "create" in argv:
            return 0, "", ""
        if argv[:3] == ["snapper", "-c", "root"] and "list" in argv:
            return 0, (
                " # | Type   | Pre # | Date | User | Cleanup | Description | Userdata\n"
                "---+--------+-------+------+------+---------+-------------+---------\n"
                "0  | single |       |  …   | root |         |             |\n"
                "1  | single |       | now  | root | number  | test        |\n"
            ), ""
        return 1, "", "no"

    mgr = SnapshotManager(
        runner=runner, euid=0, fstype="btrfs",
        tools={"snapper": True, "btrfs": True, "timeshift": False},
    )
    res = mgr.create_restore_point("test")
    assert res["status"] == "CREATED"
    assert res["backend"] == "snapper"


def _reclaim():
    path = ROOT / "build/includes.chroot/usr/local/sbin/devos-reclaim-timeshift"
    loader = importlib.machinery.SourceFileLoader("devos_reclaim_timeshift", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_reclaim_removes_only_the_timeshift_snapshot_store(tmp_path):
    disk = tmp_path / "drive-a"
    (disk / "project" / "site").mkdir(parents=True)
    (disk / "websites").mkdir()
    (disk / "lost+found").mkdir()
    (disk / "timeshift" / "snapshots" / "2026-11-15_01-00-00").mkdir(parents=True)
    (disk / "timeshift" / "snapshots" / "2026-11-15_01-00-00" / "backup").write_text("copy")
    (disk / "project" / "timeshift" / "snapshots").mkdir(parents=True)
    root = tmp_path / "root"
    root.mkdir()

    reclaim = _reclaim()
    stores = reclaim.find_snapshot_stores([str(disk), str(root), "/"])
    assert stores == [str(disk / "timeshift")]

    removed = reclaim.remove_stores(stores)
    assert removed == [str(disk / "timeshift")]
    assert not (disk / "timeshift").exists()
    assert (disk / "project" / "site").is_dir()
    assert (disk / "websites").is_dir()
    assert (disk / "lost+found").is_dir()
    assert (disk / "project" / "timeshift" / "snapshots").is_dir()


def test_reclaim_counts_one_folder_when_timeshift_mounted_it_many_times():
    reclaim = _reclaim()
    stores = [
        "/run/timeshift/40988/backup/timeshift",
        "/run/media/dev/A/timeshift",
        "/run/timeshift/68667/backup/timeshift",
    ]
    assert reclaim.unique_stores(stores, lambda _path: ("disk-a", 1)) == [
        "/run/media/dev/A/timeshift"
    ]


def test_reclaim_ignores_a_timeshift_symlink(tmp_path):
    disk = tmp_path / "drive-a"
    real = tmp_path / "real-snapshots"
    (real / "snapshots").mkdir(parents=True)
    disk.mkdir()
    os.symlink(real, disk / "timeshift")
    reclaim = _reclaim()
    assert reclaim.find_snapshot_stores([str(disk)]) == []
