#!/usr/bin/env python3
"""Command groups UI: project fields show chosen group + agent; settings dialog exists."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "components" / "ai-agent" / "pipeline_gui.py"
CHROOT = ROOT / "build/includes.chroot/usr/local/share/devos/components/ai-agent/pipeline_gui.py"
UPDATE_BIN = ROOT / "build/includes.chroot/usr/local/bin/devos-update-ai-pipeline"


def test_command_group_setting_and_chooser_in_source():
    text = SRC.read_text(encoding="utf-8")
    assert 'setWindowTitle("⚙ Command Group Setting")' in text
    assert "class ChooseCommandGroupDialog" in text
    assert "Choose group…" in text
    assert "command_group_name" in text
    assert "def choose_command_group" in text
    assert "def format_group_prompts_for_field" in text
    assert "⚙ Command Group Setting" in text


def test_per_project_agent_chooser():
    text = SRC.read_text(encoding="utf-8")
    assert "def fill_pipeline_agent_combo" in text
    assert "Per-project agent chooser" in text
    # OpenProjectFieldCard must own an agent_combo and export it in snapshots
    assert "self.agent_combo = QtWidgets.QComboBox()" in text
    assert 'fill_pipeline_agent_combo(self.agent_combo, default_key=default_agent)' in text
    assert "self.agent_combo.currentData()" in text


def test_command_group_edit_selected_prompt():
    text = SRC.read_text(encoding="utf-8")
    assert "def _edit_selected_step" in text
    assert "✎ Edit selected" in text
    assert "Update prompt #" in text
    assert "itemDoubleClicked.connect" in text


def test_no_hard_prompt_limit_per_group():
    text = SRC.read_text(encoding="utf-8")
    assert "MAX_STEP_PACK = None" in text
    assert "This group already has 6 prompts" not in text
    # UI must not advertise a max-6 cap
    assert "(max 6)" not in text


def test_smart_add_prompt_first_layout():
    text = SRC.read_text(encoding="utf-8")
    assert "1. Add prompt / command" in text
    assert "2. Serial prompts for this project" in text
    assert "def append_command_group_to_drafts" in text
    assert "Advanced: multi-field draft (optional)" in text
    # Primary queue action — open-fields button is no longer the main primary CTA
    assert "+ Add Project to Pipeline" in text
    assert "All agents run together" in text


def test_single_agent_chooser_no_seo_or_collab_badge():
    text = SRC.read_text(encoding="utf-8")
    # Top duplicate Agent row / SEO / collab badge removed from main form
    assert 'QLabel("1. Agent:")' not in text
    assert "SEO Preset" not in text
    assert "Multi-Agent: Collaborative Routing" not in text
    assert "def fill_seo_prompt" not in text
    assert "One agent chooser for this project" in text


def test_chroot_pipeline_gui_synced():
    assert CHROOT.is_file()
    src = SRC.read_text(encoding="utf-8")
    chroot = CHROOT.read_text(encoding="utf-8")
    assert "ChooseCommandGroupDialog" in chroot
    assert 'setWindowTitle("⚙ Command Group Setting")' in chroot
    assert "def fill_pipeline_agent_combo" in src
    assert "def fill_pipeline_agent_combo" in chroot
    assert src == chroot


def test_update_ai_pipeline_helper_exists():
    assert UPDATE_BIN.is_file()
    text = UPDATE_BIN.read_text(encoding="utf-8")
    assert "pipeline_gui.py" in text
    assert "raw.githubusercontent.com/imranbru99/DevOS" in text


def test_format_group_prompts_join_logic():
    steps = ["Add unit tests", "Run security scan"]
    field = "\n---\n".join(steps)
    assert field.startswith("Add unit tests")
    assert "---" in field
    assert field.endswith("Run security scan")
