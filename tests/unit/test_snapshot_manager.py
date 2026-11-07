#!/usr/bin/env python3
"""Snapper (btrfs) and Timeshift (ext4) restore-point backends."""

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


def test_ext4_without_timeshift_unavailable():
    mgr = SnapshotManager(
        runner=lambda argv: (1, "", "no"),
        euid=0,
        fstype="ext4",
        tools={"timeshift": False, "snapper": False, "btrfs": False},
    )
    res = mgr.create_restore_point("test")
    assert res["status"] == "UNAVAILABLE"
    assert "Timeshift" in res["message"]


def test_ext4_with_timeshift_creates():
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["timeshift", "--create"]:
            return 0, "ok", ""
        if argv[:2] == ["timeshift", "--list"]:
            return 0, "0    >  2026-11-07_12-00-00  O  test\n", ""
        return 1, "", "unexpected"

    mgr = SnapshotManager(runner=runner, euid=0, fstype="ext4", tools={"timeshift": True})
    res = mgr.create_restore_point("test")
    assert res["status"] == "CREATED"
    assert res["backend"] == "timeshift"
    assert res["id"] == "2026-11-07_12-00-00"
    assert any(c[:2] == ["timeshift", "--create"] for c in calls)


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
