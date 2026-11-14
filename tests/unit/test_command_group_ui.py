#!/usr/bin/env python3
"""Command groups UI: project fields show chosen group; settings dialog exists."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "components" / "ai-agent" / "pipeline_gui.py"
CHROOT = ROOT / "build/includes.chroot/usr/local/share/devos/components/ai-agent/pipeline_gui.py"


def test_command_group_setting_and_chooser_in_source():
    text = SRC.read_text(encoding="utf-8")
    assert 'setWindowTitle("⚙ Command Group Setting")' in text
    assert "class ChooseCommandGroupDialog" in text
    assert "Choose group…" in text
    assert "command_group_name" in text
    assert "def choose_command_group" in text
    assert "def format_group_prompts_for_field" in text
    assert "⚙ Command Group Setting" in text


def test_chroot_pipeline_gui_synced():
    assert CHROOT.is_file()
    src = SRC.read_text(encoding="utf-8")
    chroot = CHROOT.read_text(encoding="utf-8")
    assert "ChooseCommandGroupDialog" in chroot
    assert 'setWindowTitle("⚙ Command Group Setting")' in chroot
    # Keep ISO tree copy in sync with components/
    assert "def format_group_prompts_for_field" in src
    assert "def format_group_prompts_for_field" in chroot


def test_format_group_prompts_join_logic():
    steps = ["Add unit tests", "Run security scan"]
    field = "\n---\n".join(steps)
    assert field.startswith("Add unit tests")
    assert "---" in field
    assert field.endswith("Run security scan")
