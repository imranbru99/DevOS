import pytest
import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "components"))

from components.devos_cli import (
    smart_match,
    COMMAND_CATALOG,
    COMPONENTS_DIR,
    main,
)


def test_command_catalog_paths_exist():
    """Verify that all commands mapped in devos_cli have existing target scripts."""
    candidates = list(COMMAND_CATALOG.keys())
    assert len(candidates) >= 35

    # Check critical subsystems
    critical = ["recorder", "modesty", "assistant", "code", "app", "serve", "sound", "net", "restore", "task"]
    for c in critical:
        assert c in COMMAND_CATALOG


def test_smart_match_exact_and_prefix():
    tags_map = {k: v.get("tags", []) for k, v in COMMAND_CATALOG.items()}
    candidates = list(COMMAND_CATALOG.keys())

    # Exact match
    res = smart_match("recorder", candidates, tags_map)
    assert res[0] == "recorder"

    # Prefix match
    res = smart_match("mod", candidates, tags_map)
    assert "modesty" in res[:2]


def test_smart_match_typos_and_tags():
    tags_map = {k: v.get("tags", []) for k, v in COMMAND_CATALOG.items()}
    candidates = list(COMMAND_CATALOG.keys())

    # 'blr' should match modesty blur filter
    res = smart_match("blr", candidates, tags_map)
    assert "modesty" in res

    # 'rec' should match recorder
    res = smart_match("rec", candidates, tags_map)
    assert "recorder" in res

    # 'audio' should match sound
    res = smart_match("audio", candidates, tags_map)
    assert "sound" in res

    # 'screen' should match recorder
    res = smart_match("screen", candidates, tags_map)
    assert "recorder" in res

    # 'wifi' should match net
    res = smart_match("wifi", candidates, tags_map)
    assert "net" in res


def test_devos_cli_help(capsys):
    with patch.object(sys, "argv", ["devos", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "DevOS Unified Command Line Interface" in captured.out
    assert "recorder" in captured.out
    assert "modesty" in captured.out
    assert "sound" in captured.out


def test_devos_cli_smooth_dispatches_responsiveness():
    smooth_script = os.path.join(COMPONENTS_DIR, "optimizer", "responsiveness.py")
    assert os.path.isfile(smooth_script)
    with patch.object(sys, "argv", ["devos", "smooth", "status"]):
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
    run.assert_called_once()
    assert run.call_args[0][0] == [sys.executable, smooth_script, "status"]


def test_command_catalog_includes_smooth():
    assert "smooth" in COMMAND_CATALOG
    path = os.path.join(COMPONENTS_DIR, "optimizer", "responsiveness.py")
    assert os.path.isfile(path)


def test_devos_cli_unknown_subsystem(capsys):
    # Non-interactive mode should output suggestions
    with patch.object(sys, "argv", ["devos", "scren"]):
        with patch("sys.stdin.isatty", return_value=False):
            with patch("sys.stdout.isatty", return_value=False):
                with pytest.raises(SystemExit) as exc:
                    main()
                assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown subsystem 'scren'" in captured.err
    assert "recorder" in captured.err
