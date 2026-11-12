"""Saved agent permissions are enforced independently of model output."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components" / "assistant"))

import agents
import engine
import tools


class Model:
    def __init__(self, *steps):
        self.steps = iter(steps)
        self.prompts = []

    def chat(self, messages, **kwargs):
        self.prompts.append(json.loads(messages[-1]["content"]))
        name, value = next(self.steps)
        return json.dumps({"tool": name, "value": value})


class TestAgents(unittest.TestCase):
    def test_saved_profile_and_multi_step_read(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "notes.md").write_text("The exam is on Tuesday.", encoding="utf-8")
            store = agents.ProfileStore(root / "profiles" / "agents.json")
            profile = agents.Profile("Study", "Summarize my notes", str(root))
            store.save({profile.name: profile})
            self.assertEqual(store.load(), {profile.name: profile})

            model = Model(("list_files", "."), ("read_file", "notes.md"), ("answer", "Exam Tuesday."))
            result = agents.run(profile, "When is the exam?", model, tools.ToolContext(), engine.StreamHandle())
            self.assertEqual(result.answer, "Exam Tuesday.")
            self.assertEqual(len(result.actions), 2)
            self.assertIn("The exam is on Tuesday.", model.prompts[-1]["tool_results"][-1]["result"])

    def test_traversal_and_symlink_are_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            scoped = root / "approved"
            scoped.mkdir()
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            with self.assertRaises(ValueError):
                agents.read_file(scoped, "../outside.txt", tools.ToolContext())
            try:
                (scoped / "link.txt").symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks are unavailable on this host.")
            with self.assertRaises((ValueError, OSError)):
                agents.read_file(scoped, "link.txt", tools.ToolContext())
            self.assertNotIn("link.txt", agents.list_files(scoped, "."))

    def test_model_cannot_launch_unapproved_apps_or_execute_commands(self):
        launched = []
        ctx = tools.ToolContext(launcher=lambda argv: launched.append(argv) or True)
        app = SimpleNamespace(name="Notes", path="/apps/notes.desktop", exec="notes")
        profile = agents.Profile("Desk", "Open approved apps", apps=("notes",))
        model = Model(("open_app", "terminal"), ("shell", "something"),
                      ("open_app", "notes"), ("answer", "Notes is ready for approval."))
        with patch.object(agents, "app_choices", return_value={"notes": app}):
            result = agents.run(profile, "Open Notes", model, ctx, engine.StreamHandle())
            self.assertEqual(result.launches, ("notes",))
            self.assertEqual(launched, [])
            self.assertEqual(sum(line.startswith("Failed") for line in result.actions), 2)
            with self.assertRaises(ValueError):
                agents.launch_app(profile, "notes", ctx, (app.path, "changed"))
            with patch.object(tools, "launch_command", return_value=["notes"]):
                agents.launch_app(profile, "notes", ctx, (app.path, app.exec))
        self.assertEqual(launched, [["notes"]])

    def test_cancel_discards_proposed_actions(self):
        handle = engine.StreamHandle()
        handle.stop()
        result = agents.run(agents.Profile("Desk", "Test"), "Request", Model(),
                            tools.ToolContext(), handle)
        self.assertEqual(result.answer, "Stopped.")
        self.assertEqual(result.launches, ())

    def test_invalid_followup_can_still_answer_from_tool_results(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "notes.txt").write_text("The appointment is on Tuesday.", encoding="utf-8")
            profile = agents.Profile("Study", "Read the notes", str(root))
            model = SimpleNamespace(chat=unittest.mock.Mock(side_effect=[
                '{"tool":"read_file","value":"notes.txt"}',
                '{"tool":"read_file","value":"notes.txt","result":"The appointment is on Tuesday."}',
                "The appointment is on Tuesday.",
            ]))
            result = agents.run(profile, "When is the appointment?", model, tools.ToolContext(),
                                engine.StreamHandle())
            self.assertEqual(result.answer, "The appointment is on Tuesday.")
            self.assertIn("The appointment is on Tuesday.", model.chat.call_args.args[0][-1]["content"])
