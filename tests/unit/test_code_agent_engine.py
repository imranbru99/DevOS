#!/usr/bin/env python3
"""Tests for the Code Agent engine: multi-call parsing, loose file recovery, syntax self-check,
truncated-reply continuation, phased big briefs, and never ending a run with nothing."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import io
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/code-agent")))

import code_agent as core  # noqa: E402


class ScriptedLLM:
    """Plays back replies; records the messages it was asked with."""

    def __init__(self, replies, finishes=None):
        self.replies = list(replies)
        self.finishes = list(finishes or [])
        self.max_tokens = 4096
        self.last_finish = "stop"
        self.asked = []

    def chat(self, messages, on_token=None, should_stop=None, options=None):
        self.asked.append(messages)
        reply = self.replies.pop(0) if self.replies else ""
        self.last_finish = self.finishes.pop(0) if self.finishes else "stop"
        if on_token and reply:
            on_token(reply)
        return reply


def write_block(path, content):
    return f"```tool write_file\npath: {path}\n---\n{content}\n```"


def make_agent(root, llm, **kwargs):
    events = []
    agent = core.CodeAgent(core.Workspace(root), llm, approve=lambda a: True,
                           policy=core.ApprovalPolicy(auto_reads=True, auto_edits=True, auto_commands=True),
                           on_event=lambda k, p=None: events.append((k, p)), keep_notes=False,
                           bootstrap=kwargs.pop('bootstrap', False), **kwargs)
    return agent, events


class ParserTests(unittest.TestCase):
    def test_several_blocks_in_one_reply_stop_after_a_command(self):
        text = ("```tool write_file\npath: a.php\n---\n<?php echo 1;\n```\n"
                "```tool read_file\npath: b.php\n```\n"
                "```tool run_command\ncommand: ls\n```\n"
                "```tool read_file\npath: never.php\n```")
        calls = core.parse_tool_calls(text)
        self.assertEqual([c.name for c in calls], ["write_file", "read_file", "run_command"])
        self.assertEqual(calls[0].args["content"], "<?php echo 1;")

    def test_first_call_helper_still_works(self):
        self.assertEqual(core.parse_tool_call("```tool read_file\npath: x\n```").args["path"], "x")
        self.assertIsNone(core.parse_tool_call("All done."))

    def test_path_then_code_block_becomes_write_file(self):
        text = ("**routes/web.php**\n```php\n<?php\nRoute::get('/', fn () => view('welcome'));\n```\n"
                "`resources/views/welcome.blade.php`:\n```html\n<h1>Hello from the landing page</h1>\n```")
        calls = core.parse_loose_files(text)
        self.assertEqual([c.args["path"] for c in calls], ["routes/web.php", "resources/views/welcome.blade.php"])
        self.assertTrue(all(c.name == "write_file" for c in calls))

    def test_plain_example_block_is_not_a_file(self):
        self.assertEqual(core.parse_loose_files("Run it like this:\n```bash\nphp artisan serve\n```"), [])

    def test_unclosed_fence(self):
        self.assertTrue(core.has_unclosed_fence("```tool write_file\npath: x\n---\nabc"))
        self.assertFalse(core.has_unclosed_fence("```tool read_file\npath: x\n```"))

    def test_read_sse_reports_finish_reason(self):
        lines = [b'data: {"choices":[{"delta":{"content":"hi"}}]}\n',
                 b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n', b"data: [DONE]\n"]
        meta = {}
        self.assertEqual(core.read_sse(lines, meta=meta), "hi")
        self.assertEqual(meta["finish_reason"], "length")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.ws = core.Workspace(self.dir)

    def test_syntax_check_python_and_json(self):
        self.ws.write_text("ok.py", "x = 1\n")
        self.ws.write_text("bad.py", "def f(:\n")
        self.ws.write_text("bad.json", "{oops")
        self.assertEqual(self.ws.check_syntax("ok.py"), "")
        self.assertIn("line 1", self.ws.check_syntax("bad.py"))
        self.assertTrue(self.ws.check_syntax("bad.json"))

    def test_project_brief_reads_manifests(self):
        self.ws.write_text("composer.json", '{"require": {"php": "^8.2", "laravel/framework": "^11.0"}}')
        self.ws.write_text("package.json", '{"scripts": {"dev": "vite"}, "dependencies": {"vue": "^3"}}')
        brief = self.ws.project_brief()
        self.assertIn("laravel/framework", brief)
        self.assertIn("vue", brief)


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_http_error_does_not_restart_a_responding_server(self):
        llm = core.LocalLLM(endpoint="http://127.0.0.1:11434/v1", model="missing", api_key="")
        error = urllib.error.HTTPError(llm.endpoint, 404, "Not Found", {}, io.BytesIO(b'model not found'))
        with mock.patch.object(core.urllib.request, "urlopen", side_effect=error), \
                mock.patch.object(core, "ensure_ai_service") as start:
            with self.assertRaisesRegex(core.AgentError, "HTTP 404: model not found"):
                llm.chat([{"role": "user", "content": "build"}])
            start.assert_not_called()

    def test_cli_passes_unattended_options_to_the_agent(self):
        with mock.patch.object(core, "run_cli", return_value=0) as run:
            self.assertEqual(core.main(["--cli", "create app.py", "--dir", self.dir,
                                        "--auto-edits", "--auto-commands"]), 0)
        run.assert_called_once_with("create app.py", self.dir, True, True,
                                    auto_commands=True, max_steps=15)

    def test_missing_batch_file_is_explicitly_queued_for_repair(self):
        llm = ScriptedLLM([])
        llm.supports_batch = lambda: True
        llm.chat_batch = lambda *a, **kw: {"branches": {
            "a.py": {"text": write_block("a.py", "A = 1"), "reason": "stop"},
            "b.py": {"text": write_block("b.py", "B = 2"), "reason": "stop"},
        }}
        agent, _ = make_agent(self.dir, llm)
        agent._plan_files = lambda *a: [("a.py", "first"), ("b.py", "second"), ("c.py", "third")]
        self.assertTrue(agent._parallel_files("create three modules", "build"))
        self.assertIn("[write_file c.py]", agent.messages[-1]["content"])
        self.assertIn("no result came back", agent.messages[-1]["content"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "c.py")))

    def test_syntax_error_is_reported_back_and_fixed(self):
        llm = ScriptedLLM([
            "```tool write_file\npath: app.py\n---\ndef broken(:\n```",
            "```tool write_file\npath: app.py\n---\nprint('ok')\n```",
            "Fixed app.py; run it with python3 app.py.",
        ])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create app.py that prints ok")
        feedback = llm.asked[1][-1]["content"]
        self.assertIn("SYNTAX ERROR in app.py", feedback)
        with open(os.path.join(self.dir, "app.py")) as handle:
            self.assertEqual(handle.read(), "print('ok')\n")

    def test_reply_cut_off_inside_a_file_is_continued(self):
        llm = ScriptedLLM(
            ["```tool write_file\npath: big.py\n---\nA = 1\n", "B = 2\n```", "Done."],
            finishes=["length", "stop", "stop"])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create big.py with two constants")
        with open(os.path.join(self.dir, "big.py")) as handle:
            self.assertEqual(handle.read(), "A = 1\nB = 2\n")

    def test_a_fast_engine_may_write_two_files_in_one_reply(self):
        llm = ScriptedLLM([
            "```tool write_file\npath: one.py\n---\nONE = 1\n```\n```tool write_file\npath: two.py\n---\nTWO = 2\n```",
            "Created both files.",
        ])
        llm.is_local = False
        agent, _ = make_agent(self.dir, llm)
        agent.run("create one.py and two.py")
        self.assertEqual(len(llm.asked), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "one.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "two.py")))

    def test_the_local_model_writes_each_file_as_soon_as_it_is_complete(self):
        """A file takes minutes on this PC: the first complete block is run at once, the rest of the reply is not waited for."""
        class Streaming(ScriptedLLM):
            def chat(inner, messages, on_token=None, should_stop=None, options=None):
                inner.asked.append(messages)
                reply = inner.replies.pop(0)
                got = []
                for i in range(0, len(reply), 9):
                    if should_stop and should_stop():
                        break
                    got.append(reply[i:i + 9])
                    on_token(reply[i:i + 9])
                inner.streamed = "".join(got)
                return "".join(got)

        two = ("```tool write_file\npath: one.py\n---\nONE = 1\n```\n" + "```tool write_file\npath: two.py\n---\n"
               + "TWO = 2\n" * 300 + "```")
        llm = Streaming([two, "```tool write_file\npath: two.py\n---\nTWO = 2\n```", "Both written."])
        agent, events = make_agent(self.dir, llm)
        agent.run("create one.py and two.py")
        self.assertLess(len(llm.streamed or ""), 120 if len(llm.asked) == 1 else 10 ** 6)
        self.assertEqual(len(llm.asked), 3)
        order = [p.title for k, p in events if k == "change"]
        self.assertEqual(len(order), 2)

    def test_a_runaway_file_is_cut_not_written_and_retried_shorter(self):
        loop = "    \"imrandevbd/ledger\": \"^1.0\",\n" * 400
        llm = ScriptedLLM(["```tool write_file\npath: composer.json\n---\n{\n" + loop + "}\n```",
                           "```tool write_file\npath: composer.json\n---\n{\"require\": {}}\n```", "Short version written."])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create composer.json")
        self.assertIn("cut off and NOT written", llm.asked[1][-1]["content"])
        with open(os.path.join(self.dir, "composer.json")) as handle:
            self.assertEqual(handle.read().strip(), '{"require": {}}')

    def test_nested_code_fences_inside_a_markdown_file_do_not_end_the_block_early(self):
        md = "# Notes\n```php\necho 1;\n```\nMore text\n"
        llm = ScriptedLLM(["```tool write_file\npath: NOTES.md\n---\n" + md + "```", "Done."])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create NOTES.md")
        with open(os.path.join(self.dir, "NOTES.md")) as handle:
            self.assertIn("More text", handle.read())

    def test_empty_replies_are_retried_not_ended(self):
        llm = ScriptedLLM(["", "```tool write_file\npath: z.py\n---\nZ = 1\n```", "Created z.py."])
        agent, _ = make_agent(self.dir, llm)
        final = agent.run("create z.py")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "z.py")))
        self.assertTrue(final.strip())

    def test_code_in_plain_blocks_is_still_written(self):
        llm = ScriptedLLM(["**hello.py**\n```python\nprint('hello world, from the agent')\n```", "Done."])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create hello.py")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "hello.py")))

    def test_history_keeps_file_bodies_out_of_the_prompt(self):
        body = "\n".join(f"V{i} = {i}" for i in range(400))
        llm = ScriptedLLM([f"```tool write_file\npath: big.py\n---\n{body}\n```", "Done."])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create big.py")
        second_prompt = "\n".join(m["content"] for m in llm.asked[1])
        self.assertNotIn("V399", second_prompt)
        self.assertIn("lines written", second_prompt)

    def test_several_files_in_one_block_are_split(self):
        text = "```tool write_file\npath: a.py\n---\nA = 1\n\nb.py\n---\nB = 2\n\nsub/c.py\n---\nC = 3\n```"
        calls = core.parse_tool_calls(text)
        self.assertEqual([c.args["path"] for c in calls], ["a.py", "b.py", "sub/c.py"])
        self.assertEqual(calls[0].args["content"].strip(), "A = 1")
        self.assertEqual(calls[2].args["content"].strip(), "C = 3")

    def test_stream_stops_when_a_second_file_starts_inside_one_block(self):
        class Streaming(ScriptedLLM):
            def chat(inner, messages, on_token=None, should_stop=None, options=None):
                inner.asked.append(messages)
                reply = inner.replies.pop(0)
                got = []
                for i in range(0, len(reply), 7):
                    if should_stop and should_stop():
                        break
                    got.append(reply[i:i + 7])
                    if on_token:
                        on_token(reply[i:i + 7])
                inner.streamed = "".join(got)
                return "".join(got)

        runaway = "```tool write_file\npath: a.py\n---\nA = 1\n\nb.py\n---\nB = 2\n" + "X = 0\n" * 2000
        llm = Streaming([runaway, write_block("b.py", "B = 2"), "Both files are written."])
        agent, _ = make_agent(self.dir, llm)
        agent.run("create a.py and b.py")
        self.assertLess(len(llm.streamed or ""), 400)                      # the second file was cut off at once
        self.assertIn("Only the FIRST file", llm.asked[1][-1]["content"])
        with open(os.path.join(self.dir, "a.py")) as handle:
            self.assertEqual(handle.read().strip(), "A = 1")
        with open(os.path.join(self.dir, "b.py")) as handle:
            self.assertEqual(handle.read().strip(), "B = 2")

    def test_big_structured_spec_without_phases_is_built_in_proposed_phases(self):
        spec = "# Billing platform\n" + "".join(f"## {i}. Part {i}\nRequirement detail line.\n" * 1 + "More detail for part.\n" * 40
                                               for i in range(1, 7))
        llm = ScriptedLLM([
            "1. Create skeleton file a.py\n2. Create module file b.py",
            "```tool write_file\npath: a.py\n---\nA = 1\n```", "Phase one done.",
            "```tool write_file\npath: b.py\n---\nB = 2\n```", "Phase two done.",
        ])
        agent, events = make_agent(self.dir, llm)
        final = agent.run(spec)
        phases = [p for k, p in events if k == "phase"]
        self.assertEqual([p["index"] for p in phases], [1, 2])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "a.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "b.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, ".devos", "spec.md")))
        self.assertIn("2 file(s)", final)

    def test_long_unstructured_message_is_an_ordinary_request(self):
        log = "Traceback (most recent call last):\n" + "  File x.py, line 1\n    boom()\n" * 120
        llm = ScriptedLLM(["The error is in boom()."])
        agent, events = make_agent(self.dir, llm)
        final = agent.run("why does this fail?\n" + log)
        self.assertEqual(len(llm.asked), 1)
        self.assertFalse([p for k, p in events if k == "phase"])
        self.assertIn("boom", final)

    def test_ordinary_task_is_left_as_written_and_never_auto_runs_the_server(self):
        self.assertEqual(core.CodeAgent._sanitize_task("fix the login page"), "fix the login page")
        cleaned = core.CodeAgent._sanitize_task('Build the page.\n1. **First reply only:** confirm. Then **wait for my "go"**.\nBegin with step 1 now.')
        self.assertNotIn("go", cleaned.lower().replace("do not wait", "").replace("begin with a tool call", "") .split("build the page.")[1][:5])
        self.assertIn("Build the page.", cleaned)
        # the model keeps talking; the old heuristics saw 'start' in a boilerplate note and launched the dev server
        open(os.path.join(self.dir, "artisan"), "w").close()
        llm = ScriptedLLM(["I think the cause is the view.", "I think the cause is the view, yes."])
        agent, events = make_agent(self.dir, llm)
        agent.run("add a pricing page")
        self.assertFalse([p for k, p in events if k == "command"])

    def test_loose_code_block_never_overwrites_an_existing_file(self):
        path = os.path.join(self.dir, "hello.py")
        with open(path, "w") as handle:
            handle.write("KEEP = True\n")
        llm = ScriptedLLM(["**hello.py**\n```python\nprint('replacement that is long enough to count')\n```", "Done."])
        agent, _ = make_agent(self.dir, llm)
        agent.run("explain how hello.py could print a greeting and add one")
        with open(path) as handle:
            self.assertEqual(handle.read(), "KEEP = True\n")

    def test_task_message_survives_earlier_conversation(self):
        history = [{"role": "user", "content": "earlier " * 400}, {"role": "assistant", "content": "answer " * 400}]
        llm = ScriptedLLM(["Done."])
        agent, _ = make_agent(self.dir, llm, history=history)
        agent.run("create z.py with the number 42 in it, exactly this text: MARKER_TASK_TEXT " + "pad " * 300)
        sent = llm.asked[0]
        self.assertTrue(any("MARKER_TASK_TEXT" in m["content"] and "(shortened)" not in m["content"] for m in sent))
        self.assertLess(len(sent[1]["content"]), 1300)               # the old turns are the ones that are shortened

    def test_non_consecutive_empty_replies_do_not_abort(self):
        llm = ScriptedLLM(["", write_block("a.py", "A = 1"), "", write_block("b.py", "B = 2"), "", "All done."])
        agent, _ = make_agent(self.dir, llm)
        final = agent.run("create a.py and b.py")
        self.assertNotIn("three times", final)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "b.py")))

    def test_context_tokens_survives_odd_servers(self):
        import http.server, threading
        bodies = ['[]', '{"speed": []}', '{"speed": {"code_context": "x"}}', '{"speed": {"code_context": 16384}}']
        served = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(inner):
                body = bodies[len(served)].encode()
                served.append(1)
                inner.send_response(200)
                inner.send_header("Content-Length", str(len(body)))
                inner.end_headers()
                inner.wfile.write(body)

            def log_message(inner, *a):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        llm = core.LocalLLM(endpoint=f"http://127.0.0.1:{server.server_port}/v1", model="m", api_key="")
        self.assertEqual([llm.context_tokens() for _ in range(4)], [8192, 8192, 8192, 16384])   # failures are retried, success cached
        self.assertEqual(llm.context_tokens(), 16384)

    def test_question_with_build_words_inside_big_brief_is_not_diagnostic(self):
        self.assertFalse(core.CodeAgent._is_diagnostic("Build the app. " + "why how what " * 80))
        self.assertTrue(core.CodeAgent._is_diagnostic("why is the landing page blank?"))
        self.assertFalse(core.CodeAgent._is_diagnostic("why is it blank, fix it"))


if __name__ == "__main__":
    unittest.main()
