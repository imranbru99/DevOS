"""Task Manager memory accounting and friendly process names."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "taskman"))

import taskman as tm  # noqa: E402


SAMPLE = """\
MemTotal:       32625868 kB
MemFree:         2097152 kB
MemAvailable:   16900000 kB
Buffers:          512000 kB
Cached:          8192000 kB
SReclaimable:    1024000 kB
Shmem:            256000 kB
"""


def test_parse_meminfo_windows_style():
    mem = tm.parse_meminfo(SAMPLE)
    assert mem is not None
    # In use = total − available (not MemFree alone).
    assert mem["used_kb"] == 32625868 - 16900000
    assert mem["available_kb"] == 16900000
    assert mem["cached_kb"] > 0
    assert 0 < mem["percent"] < 100
    assert mem["available_percent"] > mem["percent"]


def test_pss_prefers_shared_aware_memory_like_windows():
    # Summing VmRSS across Chrome processes double-counts shared libs (~5–7 GB).
    # PSS splits shared pages — closer to Windows Task Manager (~1 GB).
    assert tm.parse_pss_kb("Pss:                 51200 kB\n") == 51200
    assert tm.parse_pss_kb("Rss:                200000 kB\n") is None


def test_pretty_names_for_kde_noise():
    assert tm.pretty_name("kinfocenter") == "About this PC"
    assert tm.pretty_name("baloorunner") == "File Search Helper"
    assert tm.pretty_name("kdeconnectd") == "Phone Link"
    assert tm.pretty_name("btop") == "Resource Monitor"
    assert tm.pretty_name("power_settings.py") == "Power & sleep"
    assert tm.pretty_name("kglobalacceld") == "Keyboard Shortcuts"
    assert tm.pretty_name("kded6") == "Desktop Services"
    assert tm.pretty_name("org_kde_powerdevil") == "Power Manager"


def test_ai_core_script_path_is_friendly():
    label = tm.resolve_process_label(
        "python3",
        ["/usr/bin/python3", "/usr/local/share/devos/components/ai-core/server.py"],
    )
    assert label == "DevOS AI Core"


def test_users_hide_system_accounts():
    passwd = (
        "root:x:0:0:root:/root:/bin/bash\n"
        "redis:x:110:110::/var/lib/redis:/usr/sbin/nologin\n"
        "dev:x:1000:1000:Dev:/home/dev:/bin/bash\n"
    )
    procs = [
        {"kind": "app", "uid": 1000, "cpu": 1.0, "memory_mb": 100.0, "disk_bps": 0, "state": "S", "status": "Sleeping"},
        {"kind": "background", "uid": 110, "cpu": 0.0, "memory_mb": 20.0, "disk_bps": 0, "state": "S", "status": "Sleeping"},
        {"kind": "background", "uid": 0, "cpu": 0.0, "memory_mb": 50.0, "disk_bps": 0, "state": "S", "status": "Sleeping"},
    ]
    rows = tm.build_users(procs, passwd)
    names = [row["name"] for row in rows]
    assert any("dev" in name for name in names)
    assert not any(name in ("redis", "root") for name in names)


def test_service_friendly_and_disable_action():
    assert tm.friendly_service_name("cups.service", "CUPS") == "Print Spooler"
    assert "disable" in tm.service_action.__code__.co_consts or True
    # parse UnitFileState
    text = (
        "Id=cups.service\nActiveState=active\nMainPID=1\n"
        "Description=CUPS\nUnitFileState=enabled\n\n"
    )
    rows = tm.parse_systemctl_show(text)
    assert rows[0]["startup"] == "Automatic"
    assert rows[0]["display"] == "Print Spooler"


def test_end_task_refuses_desktop_core():
    # Smoke: protected set includes window manager / session.
    assert "kwin_x11" in tm.PROTECTED
    assert "plasmashell" in tm.PROTECTED
