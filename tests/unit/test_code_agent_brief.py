#!/usr/bin/env python3
"""A long brief must be understood from its own structure (sections, packages, phases), the user's
'go' must continue the saved build, and package names the brief never mentions must never be written."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/code-agent")))

import brief  # noqa: E402
import code_agent as core  # noqa: E402

FILLER = "Detail line that keeps the brief long enough to be treated as a big task.\n" * 40

BRIEF = f"""# MASTER BUILD PROMPT: SHOPLY — Small Shop Platform
**Laravel 12 + Filament v3 + the `acme/*` package suite**

> Build phase by phase. After each phase: run tests and wait for my "go". Never invent features outside this spec.

## 0. ROLE AND WORKING RULES
Rules for yourself:
1. Money is stored as integers. Never float.
2. Write tests with the code.

## 2. FIXED TECH STACK (do not substitute)
| Layer | Choice |
|---|---|
| Framework | PHP 8.3, **Laravel 12** |
| Excel | `maatwebsite/excel` |
| Search | Meilisearch or MySQL fulltext behind a swappable driver |

## 3. THE `acme` PACKAGE SUITE
Use them, do not replace them.

### 3.1 `acme/laravel-profiler` — speed
- Install: `composer require acme/laravel-profiler`. Namespace `Acme\\Profiler\\Facades\\Profiler`.

### 3.2 `acme/laravel-slugger` — slugs in any language
- Install: `composer require acme/laravel-slugger`. Never write slugs by hand (use slugger).

## 4. MODULES
### 4.1 Sales and invoicing
{FILLER}
## 5. MULTI-TENANCY
Single database with business_id on every table.

## 7. PRICING
First 12 months free. After that a monthly fee based on volume.

## 11. ANDROID / PWA
Installable PWA with offline shell and a Capacitor wrapper. Create the `mobile/` folder and `docs/NOTES.md`.

## 12. DELIVERY PHASES
**Phase 1 — Foundation:** Laravel 12, Docker, tenancy, roles. Install **profiler**.
**Phase 2 — Core money:** invoices, payments, expenses. Install **slugger**.
**Phase 3 — Mobile:** PWA offline sync, Capacitor build.

## 14. HOW YOU MUST RESPOND
1. **First reply only:** confirm your understanding; list assumptions and up to 10 questions (include: the exact definition of "volume", which SMS gateway to start with); propose the folder structure. Then **wait for my "go"**.
2. Never call AI providers directly.

**Begin with step 1 now.**
"""

NO_PROTOCOL = (BRIEF.replace('and wait for my "go"', "").replace('Then **wait for my "go"**.', "")
               .replace("**First reply only:**", "First:"))


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.max_tokens = 4096
        self.last_finish = "stop"
        self.asked = []

    def chat(self, messages, on_token=None, should_stop=None, options=None):
        self.asked.append(messages)
        reply = self.replies.pop(0) if self.replies else "Done."
        if on_token:
            for i in range(0, len(reply), 5):
                on_token(reply[i:i + 5])
        return reply


def make_agent(root, llm):
    events = []
    agent = core.CodeAgent(core.Workspace(root), llm, approve=lambda a: True,
                           policy=core.ApprovalPolicy(auto_reads=True, auto_edits=True, auto_commands=True),
                           on_event=lambda k, p=None: events.append((k, p)), keep_notes=False, bootstrap=False)
    return agent, events


def write(path, content):
    return f"```tool write_file\npath: {path}\n---\n{content}\n```"


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.b = brief.Brief(BRIEF)

    def test_sections_are_numbered_and_fenced_headings_ignored(self):
        text = "# T\n## 1. One\nbody\n```\n## not a heading\n```\n### 1.1 Sub\nmore"
        secs = brief.split_sections(text)
        self.assertEqual([s.number for s in secs], ["", "1", "1.1"])
        self.assertIn("## not a heading", secs[1].body)

    def test_other_heading_styles(self):
        setext = brief.split_sections("Title\n=====\nintro\n\nOverview\n--------\nbody\n\nStack\n-----\nx")
        self.assertEqual([s.title for s in setext if s.heading], ["Title", "Overview", "Stack"])
        bold = brief.split_sections("**1. SCOPE**\ntext\n**2. RULES**\nmore\n**3. DELIVERY**\nlast")
        self.assertEqual([s.title for s in bold if s.heading], ["SCOPE", "RULES", "DELIVERY"])
        crlf = brief.split_sections("# T\r\n## 1. One\r\nbody\r\n## 2. Two\r\nx")
        self.assertEqual([s.number for s in crlf if s.heading], ["", "1", "2"])

    def test_packages_are_only_real_package_names(self):
        self.assertEqual(self.b.owned, {"acme"})
        self.assertIn("acme/laravel-profiler", self.b.packages)
        self.assertIn("maatwebsite/excel", self.b.packages)
        prose = brief.find_packages("Use hit/miss and stock/payments, but install `foo/bar-baz` and docs/NOTES.md")
        self.assertEqual(prose, ["foo/bar-baz"])

    def test_ecosystem_vendors_and_folders_are_never_the_users_vendor(self):
        text = "Install `laravel/sanctum`, `laravel/horizon` and `spatie/laravel-permission`, `spatie/laravel-backup`, `app/Models`, `docs/readme`."
        self.assertEqual(brief.owned_vendors(text, brief.find_packages(text)), set())
        self.assertEqual(brief.owned_vendors("the `acme/*` suite", []), {"acme"})
        self.assertEqual(brief.owned_vendors("`Acme/One`, `ACME/Two`", brief.find_packages("`Acme/One`, `ACME/Two`")), {"acme"})

    def test_packages_in_tables_and_bullets_count(self):
        text = "| Layer | Pkg |\n|---|---|\n| a | acme/one |\n- acme/two — second\n"
        self.assertEqual(sorted(brief.find_packages(text)), ["acme/one", "acme/two"])

    def test_phases_come_from_the_brief_itself(self):
        self.assertEqual([(p["n"], p["title"]) for p in self.b.phases],
                         [(1, "Foundation"), (2, "Core money"), (3, "Mobile")])
        self.assertIn("tenancy", self.b.phases[0]["text"])
        self.assertEqual(brief.extract_phases("We build phase by phase, always."), [])

    def test_phase_notations(self):
        cases = {
            "**Phase 1** — Foundation: a, b\n**Phase 2** — Core: c, d\n": [(1, "Foundation"), (2, "Core")],
            "**Phase 1:** Foundation — a, b\n**Phase 2:** Core — c\n": [(1, "Foundation"), (2, "Core")],
            "Phase A: Foundation\nPhase B: Core\n": [(1, "Foundation"), (2, "Core")],
            "Phase I: Foundation\nPhase II: Core\nPhase III: Last\n": [(1, "Foundation"), (2, "Core"), (3, "Last")],
            "Phase one: A thing\nPhase two: B thing\n": [(1, "A thing"), (2, "B thing")],
            "| Phase | Scope |\n|---|---|\n| 1 | Foundation |\n| 2 | Core |\n": [(1, "Foundation"), (2, "Core")],
            "## Phase 1\nFoundation stuff\n- a\n- b\n## Phase 2\nCore\n- c\n- d\n": [(1, "Foundation stuff"), (2, "Core")],
            "Milestone 1: A\nMilestone 2: B\n": [(1, "A"), (2, "B")],
            "Phase 1 of 3: Foundation\nPhase 2 of 3: Core\nPhase 3 of 3: End\n": [(1, "Foundation"), (2, "Core"), (3, "End")],
            "Phase 0: Setup\nPhase 1: Core\nPhase 2: End\n": [(0, "Setup"), (1, "Core"), (2, "End")],
        }
        for text, expected in cases.items():
            self.assertEqual([(p["n"], p["title"]) for p in brief.extract_phases(text)], expected, text)

    def test_phase_tasks_from_bullets_and_prose_after_the_list(self):
        phases = brief.extract_phases("## Phase 1\nFoundation\n- set up docker\n- add roles\n## Phase 2\nCore\n- invoices\n- payments\n")
        self.assertEqual(phases[0]["tasks"], ["set up docker", "add roles"])
        cut = brief.extract_phases("Phase 1: A\nPhase 2: B\nPhase 4: C\n")
        self.assertEqual([p["n"] for p in cut], [1, 2])
        self.assertEqual(brief.phase_gaps("Phase 1: A\nPhase 2: B\nPhase 4: C\n"), [4])
        glued = brief.extract_phases("**Phase 1 — A:** x, y\n**Phase 2 — B:** z\nAfter each phase deliver tests.\n")
        self.assertEqual(glued[1]["text"], "z")

    def test_protocol_detection(self):
        self.assertTrue(self.b.protocol)
        self.assertFalse(brief.Brief(NO_PROTOCOL).protocol)
        for yes in ("Then wait until I say go.", "Stop after each phase and wait for my review.",
                    "Do not start the next phase until I confirm.", "Ask me before starting the next phase.",
                    "Pause after each phase.", 'wait for my "go".'):
            self.assertTrue(brief.detect_protocol(yes), yes)
        for no in ("so main can wait for the go routines to finish.", "The checkout must wait for confirmation from the payment gateway.",
                   "```\nwait for my go\n```"):
            self.assertFalse(brief.detect_protocol(no), no)

    def test_questions(self):
        qs = self.b.required_questions()
        self.assertTrue(any("volume" in q for q in qs))
        self.assertTrue(any("SMS gateway" in q for q in qs))
        other = brief.Brief("# x\nQuestions about: the currency, the SMS provider. Then wait for my go.")
        self.assertEqual(other.required_questions(), ["The currency", "The SMS provider"])

    def test_each_phase_gets_the_sections_it_names(self):
        p1 = brief.select_sections(self.b, "Foundation: Laravel 12, Docker. Install **profiler**.")
        self.assertIn("acme/laravel-profiler", p1)
        self.assertNotIn("acme/laravel-slugger", p1)
        self.assertIn("FIXED TECH STACK", p1)             # standing rules and stack always come along
        p3 = brief.select_sections(self.b, "Mobile: PWA offline sync, Capacitor build")
        self.assertIn("ANDROID / PWA", p3)
        self.assertNotIn("DELIVERY PHASES", p3)           # the phase list itself is not repeated

    def test_unstructured_brief_still_yields_something(self):
        flat = brief.Brief("We are building a shop app.\n\nThe pricing is a monthly fee.\n\nUsers log in with a phone number.")
        self.assertIn("phone number", brief.select_sections(flat, "login with phone"))

    def test_split_tasks_ignores_commas_in_brackets(self):
        self.assertEqual(brief.split_tasks("Laravel 12, CI (a, b), i18n (bn/en). Install X and Y."),
                         ["Laravel 12", "CI (a, b)", "i18n (bn/en)", "Install X and Y"])

    def test_card_names_the_allowed_packages(self):
        card = self.b.card()
        self.assertIn("acme/laravel-slugger", card)
        self.assertIn("Never invent features", card)

    def test_extractive_understanding_assumptions_and_tree(self):
        lines = self.b.understanding()
        self.assertGreaterEqual(len(lines), 4)
        self.assertTrue(any(line.startswith("**Multi-tenancy") for line in lines))
        self.assertTrue(any("12 months free" in line for line in lines))
        assumptions = self.b.assumptions()
        self.assertTrue(any("`go`" in a for a in assumptions))
        self.assertTrue(any("Meilisearch or MySQL fulltext" in a for a in assumptions))
        tree = "\n".join(self.b.folder_tree("shoply"))
        self.assertIn("mobile/", tree)
        self.assertIn("NOTES.md", tree)

    def test_hostile_inputs_are_fast_and_safe(self):
        import time
        started = time.time()
        for text in ("", "\n\n", "#" * 50000, ("Phase 1: " + "x" * 5000 + "\n") * 3, "`" * 20000, "a/b " * 20000,
                     "\x00\udc80 odd \r\n" * 10, ("## 1. A\n" + "line\n" * 50) * 500):
            b = brief.Brief(text)
            b.card(), b.understanding(), b.assumptions(), b.folder_tree(), b.required_questions()
            brief.select_sections(b, "anything about phase one")
        self.assertLess(time.time() - started, 6.0)


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.g = brief.Grounding(brief.Brief(BRIEF))

    def test_invented_packages_of_the_users_vendor(self):
        self.assertTrue(self.g.is_invented("acme/ledger"))
        self.assertTrue(self.g.is_invented("ACME/Ledger"))
        self.assertFalse(self.g.is_invented("acme/laravel-slugger"))
        self.assertEqual(self.g.suggest("acme/slugger"), "acme/laravel-slugger")
        self.assertIsNone(self.g.suggest("acme/payroll"))

    def test_third_party_packages_warn_but_are_not_blocked(self):
        self.assertFalse(self.g.third_party_unmentioned("maatwebsite/excel"))
        self.assertTrue(self.g.third_party_unmentioned("acmecorp/mystery-bundle"))
        self.assertEqual(self.g.composer_problems(["predis/predis"]), [])
        self.assertEqual(self.g.composer_warnings(["predis/predis"]), ["predis/predis is not mentioned in the brief"])

    def test_text_guard_sees_urls_paths_case_and_namespaces(self):
        found = self.g.invented_in_text("see https://github.com/acme/ledger, vendor/ACME/Payroll/src and use Acme\\Ledger\\Foo; "
                                        "but vendor/acme/laravel-slugger/README.md and Acme\\Profiler\\Facades are fine")
        self.assertEqual(found, ["Acme\\Ledger", "acme/ledger", "acme/payroll"])
        self.assertEqual(self.g.invented_in_text("acme/shoply", ignore=("shoply",)), [])        # the project's own name

    def test_ground_text_fixes_or_drops(self):
        text, changed = self.g.ground_text("Use acme/slugger and `acme/ledger` for books.")
        self.assertIn("acme/laravel-slugger", text)
        self.assertNotIn("acme/ledger", text)
        self.assertEqual(sorted(changed), ["acme/ledger", "acme/slugger"])

    def test_composer_commands_and_files(self):
        parse = brief.composer_command_packages
        self.assertEqual(parse("cd app && composer require --dev acme/ledger:^1.0 maatwebsite/excel -W && npm i"),
                         ["acme/ledger", "maatwebsite/excel"])
        self.assertEqual(parse("composer create-project laravel/laravel shop 11.*"), ["laravel/laravel"])
        self.assertEqual(parse("composer create-project laravel/laravel ./my-app"), ["laravel/laravel"])
        self.assertEqual(parse("composer require -d ../x acme/pos"), ["acme/pos"])
        self.assertEqual(parse('bash -c "composer require acme/pos"'), ["acme/pos"])
        self.assertEqual(parse("php composer.phar require acme/pos"), ["acme/pos"])
        self.assertEqual(parse("COMPOSER_MEMORY_LIMIT=-1 composer req acme/pos"), ["acme/pos"])
        self.assertEqual(brief.composer_json_packages('{"name": "acme/shoply", "require": {"php": "^8.3", "acme/pos": "*"}}'), ["acme/pos"])
        self.assertEqual(self.g.composer_problems(["acme/pos", "acme/laravel-profiler"]), ["acme/pos is not in the brief"])

    def test_stream_grounder_cleans_names_split_across_tokens(self):
        shown = []
        sg = brief.StreamGrounder(self.g, shown.append)
        for tok in ["We use acme/", "ledger and acme/lara", "vel-slugger.\nNext line"]:
            sg.feed(tok)
        sg.finish()
        self.assertEqual("".join(shown), "We use " + brief.UNLISTED + " and acme/laravel-slugger.\nNext line")
        self.assertEqual(sg.changed, ["acme/ledger"])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.state = brief.BriefState("/tmp", {"title": "T", "protocol": True, "asked": True,
                                               "phases": [{"n": 1, "title": "A", "text": ""}, {"n": 2, "title": "B", "text": ""}]})

    def test_go_variants(self):
        p = lambda t: brief.parse_command(t, self.state)  # noqa: E731
        self.assertEqual(p("go"), ("go", 1))
        self.assertEqual(p("  Go ahead!  "), ("go", 1))
        self.assertEqual(p("go all"), ("go_all", None))
        self.assertEqual(p("go phase 2"), ("go", 2))
        self.assertEqual(p("go 2"), ("go", 2))
        self.assertEqual(p("redo 1"), ("go", 1))
        self.assertEqual(p("build phase 2"), ("go", 2))
        self.assertEqual(p("status"), ("status", None))
        self.assertEqual(p("reset the brief"), ("reset", None))

    def test_ordinary_requests_are_not_commands(self):
        self.state.done = {"1": {}}
        p = lambda t: brief.parse_command(t, self.state)  # noqa: E731
        for text in ("go to the settings page and rename Save", "run 3 tests on the login form", "build 2 pages",
                     "status of the login bug?", "progress bar is broken, fix it", "reset my password flow",
                     "clear the cache button does nothing", "continue the story in the readme"):
            self.assertIsNone(p(text), text)

    def test_finished_build_does_not_swallow_ok_and_yes(self):
        self.state.done = {"1": {}, "2": {}}
        self.assertIsNone(brief.parse_command("ok", self.state))
        self.assertEqual(brief.parse_command("go", self.state), ("go", None))

    def test_answers_versus_new_requests(self):
        p = lambda t: brief.parse_command(t, self.state)  # noqa: E731
        self.assertEqual(p("1. monthly volume = sales + purchases\n2. BulkSMSBD first"), ("answers", None))
        self.assertEqual(p("Monthly volume is sales plus purchases; start with BulkSMSBD."), ("answers", None))
        self.assertIsNone(p("fix the login page"))
        self.state.done = {"1": {}}
        self.assertIsNone(p("Monthly volume is sales plus purchases."))       # after the build started: ordinary request

    def test_state_is_derived_from_done(self):
        st = brief.BriefState("/tmp", {"phases": [{"n": 0, "title": "Z", "text": ""}, {"n": 1, "title": "A", "text": ""},
                                                  {"n": 2, "title": "B", "text": ""}]})
        self.assertEqual(st.next, 0)
        st.mark_done(2, [], "")
        self.assertEqual((st.next, st.remaining(), st.finished), (0, [0, 1], False))
        st.mark_done(0, [], "")
        st.mark_done(1, [], "")
        self.assertTrue(st.finished)

    def test_bad_state_files_are_ignored(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, ".devos"))
        for bad in ("", "[]", '{"phases": "x"}', '{"phases": [{"n": "1"}]}', '{"phases": [{"n": 1, "title": "A"}], "done": []}'):
            with open(os.path.join(d, ".devos", "brief.json"), "w") as handle:
                handle.write(bad)
            st = brief.BriefState.load(d)
            self.assertTrue(st is None or st.phases == [] or st.done == {})

    def test_two_runs_do_not_lose_each_others_phases(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        b = brief.Brief(BRIEF)
        one, two = brief.BriefState.create(d, b), brief.BriefState.create(d, b)
        one.mark_done(1, ["a"], "x")
        one.save()
        two.mark_done(2, ["b"], "y")
        two.save()
        self.assertEqual(sorted(brief.BriefState.load(d).done), ["1", "2"])


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def state(self):
        return brief.BriefState.load(self.dir)

    def start(self, text=BRIEF, llm=None):
        agent, events = make_agent(self.dir, llm or ScriptedLLM([]))
        return agent.run(text), events

    def test_first_reply_understands_then_waits_for_go(self):
        llm = ScriptedLLM([])
        final, events = self.start(llm=llm)
        self.assertEqual(len(llm.asked), 0)                        # taken from the brief itself: no model, no invention
        self.assertIn("2 of your own packages", final)
        self.assertIn("1. Foundation → 2. Core money → 3. Mobile", final)
        self.assertIn("What I understood", final)
        self.assertIn("Assumptions", final)
        self.assertIn("12 months free", final)
        self.assertIn("Phase 1 — Foundation: task list", final)
        self.assertIn('The exact definition of "volume"', final)
        self.assertIn("Meilisearch or MySQL fulltext", final)
        self.assertIn("reply `go`", final)
        self.assertEqual(self.state().next, 1)
        self.assertTrue(self.state().asked)
        self.assertFalse([p for k, p in events if k == "change"])  # nothing was written yet
        self.assertTrue(os.path.isfile(os.path.join(self.dir, ".devos", "spec.md")))

    def test_unstructured_protocol_brief_uses_the_model_but_never_shows_invented_packages(self):
        text = ("Build **Shoply** with `acme/profiler` and `acme/slugger`; the suite is `acme/*`. Wait for my go after each phase.\n"
                "Phase 1: A, b\nPhase 2: C\n" + FILLER)
        llm = ScriptedLLM(["## What I understood\n- Uses acme/ledger and acme/slugger and acme/payroll."])
        final, _ = self.start(text, llm)
        self.assertEqual(len(llm.asked), 1)
        self.assertNotIn("acme/ledger", final)
        self.assertNotIn("acme/payroll", final)
        self.assertIn("acme/slugger", final)

    def test_protocol_brief_without_phases_proposes_phases_and_still_waits(self):
        text = "# Shoply\n" + "".join(f"## {i}. Section {i}\nBody of section {i}.\n" for i in range(1, 8)) + \
               "Wait for my go after each part.\n" + FILLER
        llm = ScriptedLLM(["1. Setup: config and folders\n2. Data: models\n3. Screens: pages"])
        final, events = self.start(text, llm)
        self.assertEqual(len(llm.asked), 1)                        # only the phase proposal
        self.assertTrue(self.state().protocol)
        self.assertEqual(self.state().total, 3)
        self.assertFalse([p for k, p in events if k == "phase"])   # nothing was built
        self.assertIn("reply `go`", final)

    def test_go_builds_one_phase_with_its_sections_and_stops(self):
        self.start()
        llm = ScriptedLLM([write("composer.json", '{"require": {"acme/laravel-profiler": "dev-main", "laravel/framework": "^12.0"}}'),
                           "Phase 1 written; tests not available yet."])
        agent2, _ = make_agent(self.dir, llm)
        final = agent2.run("go")
        first_prompt = llm.asked[0][1]["content"]
        self.assertIn("CURRENT PHASE 1 of 3 — Foundation", first_prompt)
        self.assertIn("acme/laravel-profiler", first_prompt)       # the section the phase names is included
        self.assertNotIn("Installable PWA", first_prompt)           # phase 3's section is not sent for phase 1
        self.assertIn("Phase 1 of 3 — Foundation", final)
        self.assertIn("composer.json", final)
        self.assertIn("`go` to build Phase 2 — Core money", final)
        self.assertEqual(self.state().next, 2)
        self.assertEqual(self.state().done["1"]["files"], ["composer.json"])

    def test_a_phase_that_did_nothing_or_was_stopped_is_not_marked_built(self):
        self.start()
        agent, events = make_agent(self.dir, ScriptedLLM(["Nothing to do here.", "Still nothing.", "Really nothing."]))
        final = agent.run("go")
        self.assertIn("Not marked as built", final)
        self.assertEqual(self.state().next, 1)
        self.assertEqual(self.state().done, {})
        # Stop pressed during the phase: nothing recorded either
        a2, _ = make_agent(self.dir, ScriptedLLM([]))

        class Stopper(ScriptedLLM):
            def chat(inner, messages, on_token=None, should_stop=None, options=None):
                a2.cancel()
                return "```tool write_file\npath: a.py\n---\nA = 1\n```"

        a2.llm = Stopper([])
        final2 = a2.run("go")
        self.assertIn("stopped", final2)
        self.assertEqual(self.state().done, {})

    def test_go_out_of_order_keeps_the_earlier_phases_pending(self):
        self.start()
        agent, _ = make_agent(self.dir, ScriptedLLM([write("c.py", "C = 3"), "Phase 3 done."]))
        agent.run("go 3")
        self.assertEqual(sorted(self.state().done), ["3"])
        self.assertEqual(self.state().next, 1)
        a2, ev2 = make_agent(self.dir, ScriptedLLM([write("a.py", "A = 1"), "ok", write("b.py", "B = 2"), "ok"]))
        final = a2.run("go all")
        self.assertEqual([p["index"] for k, p in ev2 if k == "phase"], [1, 2])
        self.assertIn("All 3 phases are built", final)

    def test_unknown_phase_and_finished_messages(self):
        self.start()
        a, _ = make_agent(self.dir, ScriptedLLM([]))
        self.assertIn("numbered 1 to 3", a.run("go 9"))
        self.assertIn("no saved brief", make_agent(tempfile.mkdtemp(), ScriptedLLM([]))[0].run("go"))

    def test_invented_packages_are_refused_in_files_commands_and_heredocs(self):
        self.start()
        bad = '{"require": {"acme/ledger": "*", "acme/pos": "*", "acme/laravel-slugger": "dev-main"}}'
        llm = ScriptedLLM([
            write("composer.json", bad),
            "```tool run_command\ncommand: composer require acme/ledger acme/slugger\n```",
            "```tool run_command\ncommand: echo '{\"require\": {\"acme/pos\": \"*\"}}' > composer.json\n```",
            write("docs/PACKAGE_NOTES.md", "We use acme/payroll."),
            "Stopped trying to add packages.",
        ])
        agent2, _ = make_agent(self.dir, llm)
        agent2.run("go")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "composer.json")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "docs", "PACKAGE_NOTES.md")))
        feedback = "\n".join(m["content"] for ask in llm.asked[1:] for m in ask[-1:])
        self.assertIn("acme/ledger is not in the brief", feedback)
        self.assertIn("did you mean acme/laravel-slugger", feedback)
        self.assertIn("acme/pos is not in the brief", feedback)

    def test_the_projects_own_name_and_unlisted_third_party_packages_are_allowed(self):
        self.start()
        name = os.path.basename(self.dir)
        ok = '{"name": "acme/%s", "require": {"acme/laravel-profiler": "dev-main", "predis/predis": "^2.0"}}' % name
        llm = ScriptedLLM([write("composer.json", ok), "done"])
        agent2, _ = make_agent(self.dir, llm)
        agent2.run("go")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "composer.json")))
        self.assertIn("predis/predis is not mentioned in the brief", llm.asked[1][-1]["content"])

    def test_go_all_runs_every_remaining_phase(self):
        self.start()
        llm = ScriptedLLM([write("a.py", "A = 1"), "Phase 1 done.", write("b.py", "B = 2"), "Phase 2 done.",
                           write("c.py", "C = 3"), "Phase 3 done."])
        agent2, events = make_agent(self.dir, llm)
        final = agent2.run("go all")
        self.assertEqual([p["index"] for k, p in events if k == "phase"], [1, 2, 3])
        self.assertIn("All 3 phases are built", final)
        self.assertTrue(self.state().finished)
        reports = [p for k, p in events if k == "report"]
        self.assertEqual(len(reports), 1)
        self.assertNotIn("Phase 1 done.", reports[0])             # the model's own summary was already streamed

    def test_status_answers_reset_and_repaste(self):
        self.start()
        a2, _ = make_agent(self.dir, ScriptedLLM([]))
        self.assertIn("0 of 3 phases built", a2.run("status"))
        self.assertIn("Noted", a2.run("1. volume = sales + purchases"))
        self.assertEqual(self.state().answers, ["1. volume = sales + purchases"])
        a3, _ = make_agent(self.dir, ScriptedLLM([write("a.py", "A = 1"), "ok"]))
        a3.run("go")
        a4, _ = make_agent(self.dir, ScriptedLLM([]))
        self.assertIn("already loaded", a4.run(BRIEF))              # 'Rerun' on the brief does not restart the build
        self.assertEqual(sorted(self.state().done), ["1"])
        os.remove(os.path.join(self.dir, ".devos", "spec.md"))      # a lost spec is restored by pasting the brief again
        a5, _ = make_agent(self.dir, ScriptedLLM([]))
        self.assertIn("missing", a5.run("go"))
        a5.run(BRIEF)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, ".devos", "spec.md")))
        self.assertIn("Brief cleared", a5.run("reset the brief"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".devos", "brief.json")))

    def test_brief_without_a_wait_for_go_rule_is_built_straight_through(self):
        llm = ScriptedLLM([write("a.py", "A = 1"), "Phase 1 done.", write("b.py", "B = 2"), "Phase 2 done.",
                           write("c.py", "C = 3"), "Phase 3 done."])
        final, events = self.start(NO_PROTOCOL, llm)
        self.assertEqual([p["index"] for k, p in events if k == "phase"], [1, 2, 3])
        self.assertIn("All 3 phases are built", final)

    def test_followup_after_the_brief_keeps_its_context_and_guard(self):
        self.start()
        llm = ScriptedLLM([write("composer.json", '{"require": {"acme/ledger": "*"}}'), "no"])
        agent2, _ = make_agent(self.dir, llm)
        agent2.run("fix the slug of the product page")
        self.assertIn("saved brief", llm.asked[0][1]["content"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "composer.json")))

    def test_a_long_message_that_is_not_a_brief_does_not_replace_the_saved_one(self):
        self.start()
        spec_path = os.path.join(self.dir, ".devos", "spec.md")
        with open(spec_path) as handle:
            spec_before = handle.read()
        paste = "Traceback (most recent call last):\n" + "  File x.py, line 1, in <module>\n    boom()\n" * 80
        llm = ScriptedLLM(["The error comes from boom()."])
        agent2, _ = make_agent(self.dir, llm)
        agent2.run("why does this fail?\n" + paste)
        with open(spec_path) as handle:
            self.assertEqual(handle.read(), spec_before)
        self.assertEqual(len(llm.asked), 1)                        # an ordinary answer, not a phase plan
        self.assertTrue(self.state().asked)

    def test_lone_surrogates_in_a_long_task_do_not_crash(self):
        llm = ScriptedLLM(["ok"])
        agent, _ = make_agent(self.dir, llm)
        agent.run("fix this " + "\udc80 " * 900)


class BatchLLM(ScriptedLLM):
    """A model that can write several files at once: `chat` answers the planner and the step loop, `chat_batch` the files."""

    def __init__(self, replies, files=None, reasons=None, fail=False):
        super().__init__(replies)
        self.files = files or {}
        self.reasons = reasons or {}
        self.fail = fail
        self.batches = []

    def supports_batch(self):
        return True

    def chat_batch(self, messages, branches, on_event=None, should_stop=None, max_tokens=1800, temperature=None):
        self.batches.append((messages, branches))
        if self.fail:
            raise core.AgentError("no parallel writing here")
        out = {"branches": {}, "tokens_per_sec": 41.5}
        for b in branches:
            body = self.files.get(b["id"], "<?php // %s" % b["id"])
            text = "```tool write_file\npath: %s\n---\n%s\n```" % (b["id"], body)
            reason = self.reasons.get(b["id"], "fence")
            if on_event:
                on_event({"type": "delta", "id": b["id"], "text": text})
                on_event({"type": "end", "id": b["id"], "reason": reason, "tokens": 12})
            out["branches"][b["id"]] = {"text": text, "reason": reason, "tokens": 12}
        return out


PLAN = ("1. app/Models/Business.php :: tenancy model that every business-owned table belongs to\n"
        "2. docker-compose.yml :: Docker services for the app\n"
        "3. app/Models/Role.php :: roles of a business user\n"
        "4. composer.json :: dependencies\n"
        "5. ../outside.php :: must be ignored\n")


class ParallelFilesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        agent, _ = make_agent(self.dir, ScriptedLLM([]))
        agent.run(BRIEF)

    def go(self, llm, **kw):
        agent, events = make_agent(self.dir, llm)
        return agent.run("go"), events, agent

    def test_the_phases_new_files_are_planned_then_written_together(self):
        llm = BatchLLM([PLAN, "All three files exist; nothing more to do."],
                       files={"app/Models/Business.php": "<?php class Customer {}"})
        final, events, _ = self.go(llm)
        self.assertEqual(len(llm.batches), 1)
        _, branches = llm.batches[0]
        self.assertEqual([b["id"] for b in branches],
                         ["app/Models/Business.php", "docker-compose.yml", "app/Models/Role.php"])
        for path in ("app/Models/Business.php", "docker-compose.yml", "app/Models/Role.php"):
            self.assertTrue(os.path.isfile(os.path.join(self.dir, path)), path)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "composer.json")))     # generators make that
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.dir), "outside.php")))
        self.assertEqual(len(llm.asked), 2)                                          # the plan, then one verifying step
        self.assertIn("written in parallel", llm.asked[1][-1]["content"])
        self.assertIn("[write_file app/Models/Role.php]", llm.asked[1][-1]["content"])
        self.assertTrue([p for k, p in events if k == "speed" and p.get("tokens_per_sec") == 41.5])
        self.assertEqual(brief.BriefState.load(self.dir).done["1"]["files"].count("app/Models/Role.php"), 1)

    def test_planned_files_unrelated_to_the_phase_scope_or_looping_are_dropped(self):
        """The 3B planner once answered Phase 1 (foundation) with 20 'Create a custom Livewire page for X' controllers."""
        plan = ("docker-compose.yml :: Docker services for the app\n"
                "app/Models/Business.php :: tenancy model for every business\n"
                "app/Http/Controllers/PosController.php :: Create a custom Livewire page for POS\n"
                "app/Http/Controllers/ScanController.php :: Create a custom Livewire page for Scan\n"
                "app/Http/Controllers/DeviceController.php :: Create a custom Livewire page for Device\n"
                "app/Models/Role.php :: roles of a business user\n"
                "lang/bn.json :: Bangla i18n strings\n")
        llm = BatchLLM([plan, "ok"])
        self.go(llm)
        ids = [b["id"] for b in llm.batches[0][1]]
        self.assertEqual(ids, ["docker-compose.yml", "app/Models/Business.php", "app/Models/Role.php"])

    def test_the_planner_is_asked_with_the_scope_last_and_a_repeat_penalty(self):
        seen = {}

        class Spy(BatchLLM):
            def chat(inner, messages, on_token=None, should_stop=None, options=None):
                seen.setdefault("options", options)
                seen.setdefault("user", messages[-1]["content"])
                return super().chat(messages, on_token, should_stop, options)

        self.go(Spy([PLAN, "ok"]))
        self.assertEqual(seen["options"], {"repeat_penalty": 1.15})
        self.assertIn("THIS PHASE'S SCOPE", seen["user"])
        self.assertTrue(seen["user"].rstrip().endswith("List the new files now."))

    def test_every_branch_sees_the_whole_plan(self):
        llm = BatchLLM([PLAN, "ok"])
        self.go(llm)
        shared, branches = llm.batches[0]
        text = shared[-1]["content"]
        self.assertIn("app/Models/Business.php :: tenancy model that every", text)
        self.assertIn("app/Models/Role.php :: roles of a business user", text)
        self.assertIn("COMPLETE file `app/Models/Role.php`", branches[2]["prompt"])

    def test_existing_files_are_not_replanned_and_a_single_file_is_not_fanned_out(self):
        os.makedirs(os.path.join(self.dir, "app/Models"))
        with open(os.path.join(self.dir, "app/Models/Business.php"), "w") as handle:
            handle.write("<?php // mine")
        only_one = "1. app/Models/Business.php :: exists already\n2. app/Models/Role.php :: routes\n"
        llm = BatchLLM([only_one, write("app/Models/Role.php", "<?php // sequential"), "done"])
        self.go(llm)
        self.assertEqual(llm.batches, [])                                            # 1 new file: the step loop does it
        with open(os.path.join(self.dir, "app/Models/Business.php")) as handle:
            self.assertEqual(handle.read(), "<?php // mine")
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "app/Models/Role.php")))

    def test_a_branch_that_looped_is_reported_not_written(self):
        llm = BatchLLM([PLAN, "I will redo it."], reasons={"app/Models/Role.php": "repeat"})
        self.go(llm)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "app/Models/Role.php")))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "app/Models/Business.php")))
        self.assertIn("it started repeating itself", llm.asked[1][-1]["content"])

    def test_a_server_without_parallel_writing_falls_back_to_one_file_at_a_time(self):
        llm = BatchLLM([PLAN, write("a.py", "A = 1"), "Done sequentially."], fail=True)
        final, _, _ = self.go(llm)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "a.py")))
        self.assertIn("Phase 1 of 3", final)

    def test_syntax_errors_in_a_parallel_file_are_fed_back(self):
        llm = BatchLLM([PLAN, "fixing"], files={"app/Models/Business.php": "<?php class {"})
        os.environ.get("PATH")
        self.go(llm)
        feedback = llm.asked[1][-1]["content"]
        if shutil.which("php"):
            self.assertIn("SYNTAX ERROR in app/Models/Business.php", feedback)



class BootstrapTests(unittest.TestCase):
    """When the brief names Laravel and the folder is empty, the agent runs Composer itself (no model tokens)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.bin + os.pathsep + self.old_path
        self.addCleanup(os.environ.__setitem__, "PATH", self.old_path)

    def fake(self, composer_exit=0):
        for name, body in (("php", "exit 0"),
                           ("composer", 'echo "$@" >> "%s/composer.log"\n'
                                        'if [ "$1" = create-project ]; then\n'
                                        '  if [ "%d" != 0 ]; then echo "network down"; exit %d; fi\n'
                                        '  mkdir -p .devos-skeleton && touch .devos-skeleton/artisan .devos-skeleton/.env\n'
                                        '  echo \'{"require": {"php": "^8.3"}}\' > .devos-skeleton/composer.json\nfi\nexit 0'
                            % (self.bin, composer_exit, composer_exit))):
            path = os.path.join(self.bin, name)
            with open(path, "w") as handle:
                handle.write("#!/bin/sh\n" + body + "\n")
            os.chmod(path, 0o755)

    def start(self, llm):
        agent = core.CodeAgent(core.Workspace(self.dir), llm, approve=lambda a: True,
                               policy=core.ApprovalPolicy(auto_reads=True, auto_edits=True, auto_commands=True),
                               keep_notes=False, bootstrap=True)
        agent.run(BRIEF)
        agent2 = core.CodeAgent(core.Workspace(self.dir), llm, approve=lambda a: True,
                                policy=core.ApprovalPolicy(auto_reads=True, auto_edits=True, auto_commands=True),
                                keep_notes=False, bootstrap=True)
        return agent2.run("go")

    def test_the_skeleton_is_made_by_composer_before_the_model_is_asked(self):
        self.fake()
        llm = ScriptedLLM(["Skeleton is there; nothing more to write."])
        self.start(llm)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "artisan")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".devos-skeleton")))
        self.assertIn("composer.log", os.listdir(self.bin))
        with open(os.path.join(self.bin, "composer.log")) as handle:
            self.assertIn("create-project laravel/laravel:^12.0", handle.read())
        prompt = llm.asked[0][1]["content"]
        self.assertIn("ALREADY DONE by the agent", prompt)
        self.assertIn("composer require vendor/package", prompt)

    def test_a_failed_bootstrap_is_reported_to_the_model_not_hidden(self):
        self.fake(composer_exit=1)
        llm = ScriptedLLM(["I will write files by hand."])
        self.start(llm)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "artisan")))
        self.assertIn("creating the Laravel skeleton with Composer failed", llm.asked[0][1]["content"])

    def test_no_bootstrap_when_the_project_already_exists(self):
        self.fake()
        open(os.path.join(self.dir, "artisan"), "w").close()
        llm = ScriptedLLM(["ok"])
        self.start(llm)
        self.assertFalse(os.path.exists(os.path.join(self.bin, "composer.log")))


    def test_packages_a_phase_names_are_installed_by_the_agent_not_left_to_the_model(self):
        self.fake()
        llm = ScriptedLLM(["Installed everything, all done."])
        self.start(llm)
        with open(os.path.join(self.bin, "composer.log")) as handle:
            log = handle.read()
        self.assertIn("require acme/laravel-profiler", log)               # Phase 1 says "Install profiler"
        self.assertNotIn("acme/laravel-slugger", log)                       # that is Phase 2's package
        self.assertIn("composer require acme/laravel-profiler", llm.asked[0][1]["content"])
        self.assertIn("succeeded", llm.asked[0][1]["content"])

    def test_a_failed_package_install_is_reported_to_the_model(self):
        self.fake()
        with open(os.path.join(self.bin, "composer"), "a") as handle:
            pass
        script = os.path.join(self.bin, "composer")
        with open(script) as handle:
            body = handle.read()
        with open(script, "w") as handle:
            handle.write(body.replace('exit 0"', 'exit 0"').replace('if [ "$1" = create-project ]', 'if [ "$1" = require ]; then echo "Could not find package"; exit 2; fi\nif [ "$1" = create-project ]'))
        llm = ScriptedLLM(["done"])
        self.start(llm)
        self.assertIn("FAILED", llm.asked[0][1]["content"])
        self.assertIn("Do not claim these packages are installed", llm.asked[0][1]["content"])

    def test_the_report_states_what_the_agent_saw_and_flags_unverified_claims(self):
        self.fake()
        llm = ScriptedLLM(["All done: installed acme/laravel-slugger and ran 18 migrations."])
        final = self.start(llm)
        self.assertIn("Commands run:", final)
        self.assertIn("composer create-project", final)
        self.assertIn("not verified by the agent", final)
        self.assertIn("acme/laravel-slugger", final.split("composer.json does not list")[1])


class FactsTests(unittest.TestCase):
    def test_a_phase_without_commands_says_so(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        agent, _ = make_agent(d, ScriptedLLM([]))
        self.assertIn("no migrations, tests or installs were run", agent._verified_facts(0, [], "I ran the migrations."))


class CommandStopTests(unittest.TestCase):
    def test_stop_kills_a_long_command(self):
        import time
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        ws = core.Workspace(d)
        started = time.time()
        flag = {"stop": False}
        import threading
        threading.Timer(1.5, lambda: flag.__setitem__("stop", True)).start()
        result = ws.run_command("sleep 60", 120, should_stop=lambda: flag["stop"])
        self.assertLess(time.time() - started, 10)
        self.assertIn("stopped by the user", result["output"])



if __name__ == "__main__":
    unittest.main()
