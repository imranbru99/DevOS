"""
Unit tests for the DevOS Optimizer core logic (no display required).
Covers size scanning, symlink path safety, idle-detection decisions,
protected processes, the never-ask allowlist and the suggestion rate limit.
"""

import sys
import os
import time
import shutil
import tempfile
import unittest

SYS_PATH_OPTIMIZER = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/optimizer"))
sys.path.insert(0, SYS_PATH_OPTIMIZER)

import optimizer  # noqa: E402
from optimizer import (  # noqa: E402
    Target, Category, IdleTracker, SuggestionLimiter, build_categories,
    scan_category, clean_entries, is_safe_entry, tree_rss, app_root,
    parse_wmctrl, low_disk, load_config, save_config, MB, GB, DAY,
)


def write(path, size=0, age_s=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    if age_s:
        old = time.time() - age_s
        os.utime(path, (old, old))
    return path


def app(comm, pid, rss_mb, cpu=0.0, protected=False, uid=None):
    return {"key": "%s:%d" % (comm, pid), "name": optimizer.pretty_name(comm), "comm": comm,
            "pid": pid, "uid": os.getuid() if uid is None else uid, "rss": rss_mb * MB,
            "cpu": cpu, "windows": [], "protected": protected}


class TestOptimizerScan(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="devos-opt-")
        self.home = os.path.join(self.base, "home")
        self.outside = os.path.join(self.base, "outside")
        os.makedirs(self.home)
        os.makedirs(self.outside)
        self.uid = os.getuid()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_01_size_scan_of_fake_tree(self):
        root = os.path.join(self.home, ".local", "share", "Trash")
        write(os.path.join(root, "files", "a.bin"), 1000)
        write(os.path.join(root, "files", "sub", "b.bin"), 2500)
        write(os.path.join(root, "info", "a.bin.trashinfo"), 100)
        res = scan_category(Category("trash", "Recycle Bin", "", [Target(root, uid=self.uid)]))
        self.assertEqual(res["size"], 3600)
        self.assertEqual(res["count"], 3)

    def test_02_min_age_filters_recent_files(self):
        root = os.path.join(self.base, "tmp")
        write(os.path.join(root, "old.log"), 500, age_s=2 * DAY)
        write(os.path.join(root, "new.log"), 700)
        res = scan_category(Category("temp", "Temp", "", [Target(root, min_age_s=DAY, uid=self.uid)]))
        self.assertEqual(res["size"], 500)
        self.assertEqual(res["count"], 1)

    def test_03_symlink_escaping_root_is_refused(self):
        root = os.path.join(self.home, ".cache")
        secret = write(os.path.join(self.outside, "important.doc"), 4096)
        os.makedirs(os.path.join(self.outside, "dir"))
        write(os.path.join(self.outside, "dir", "keep.txt"), 10)
        write(os.path.join(root, "app", "cache.bin"), 50, age_s=2 * 3600)
        os.symlink(secret, os.path.join(root, "app", "evil-link"))
        os.symlink(os.path.join(self.outside, "dir"), os.path.join(root, "app", "evil-dir"))

        self.assertFalse(is_safe_entry(os.path.join(root, "app", "evil-link"), root, self.uid))
        res = scan_category(Category("cache", "Cache", "", [Target(root, uid=self.uid)]))
        paths = [e[0] for e in res["_entries"]]
        self.assertEqual(paths, [os.path.join(root, "app", "cache.bin")])

        # Even if an escaping entry is injected, cleaning must refuse it.
        freed, errors = clean_entries(res["_entries"] + [
            (os.path.join(root, "app", "evil-link"), root, self.uid),
            (secret, root, self.uid),
        ])
        self.assertEqual(freed, 50)
        self.assertEqual(errors, 2)
        self.assertTrue(os.path.exists(secret))
        self.assertTrue(os.path.exists(os.path.join(self.outside, "dir", "keep.txt")))
        self.assertFalse(os.path.exists(os.path.join(root, "app", "cache.bin")))
        self.assertTrue(os.path.isdir(root))  # the root itself is never removed

    def test_04_symlinked_root_is_ignored(self):
        link_root = os.path.join(self.home, "Downloads")
        write(os.path.join(self.outside, "x.iso"), 1000, age_s=40 * DAY)
        os.symlink(self.outside, link_root)
        res = scan_category(Category("dl", "Downloads", "", [Target(link_root, uid=self.uid)]))
        self.assertEqual(res["count"], 0)

    def test_05_build_categories_respects_home_and_exclusions(self):
        cache = os.path.join(self.home, ".cache")
        write(os.path.join(cache, "devos", "state.db"), 999, age_s=2 * DAY)
        write(os.path.join(cache, "thumbnails", "large", "t.png"), 300, age_s=2 * DAY)
        write(os.path.join(cache, "someapp", "tmp", "scratch"), 40, age_s=2 * DAY)
        write(os.path.join(self.home, "Downloads", "old.zip"), 2000, age_s=60 * DAY)
        write(os.path.join(self.home, "Downloads", "new.zip"), 3000)
        prefix_tmp = os.path.join(self.home, ".local", "share", "winlayer", "prefixes", "game",
                                  "drive_c", "users", "devos", "AppData", "Local", "Temp")
        write(os.path.join(prefix_tmp, "setup.tmp"), 77)
        write(os.path.join(self.home, ".xsession-errors.old"), 11)
        tmp_root = os.path.join(self.base, "systmp")
        write(os.path.join(tmp_root, "mine.old"), 5, age_s=2 * DAY)

        cats = build_categories(home=self.home, uid=self.uid, tmp_roots=(tmp_root,))
        res = {c.id: scan_category(c) for c in cats}
        self.assertEqual(res["cache"]["size"], 300)          # devos + tmp dir excluded
        self.assertEqual(res["temp"]["size"], 45)            # cache tmp dir + /tmp file
        self.assertEqual(res["downloads"]["size"], 2000)     # only > 30 days
        self.assertFalse(res["downloads"]["default_checked"])
        self.assertEqual(res["wintemp"]["size"], 77)
        self.assertEqual(res["logs"]["size"], 11)
        freed, errors = clean_entries(res["logs"]["_entries"])
        self.assertEqual((freed, errors), (11, 0))

    def test_06_low_disk_rule(self):
        self.assertTrue(low_disk([{"path": "/", "total": 500 * GB, "free": 4 * GB}]))
        self.assertTrue(low_disk([{"path": "/", "total": 30 * GB, "free": 2.9 * GB}]))
        self.assertFalse(low_disk([{"path": "/", "total": 100 * GB, "free": 40 * GB}]))

    def test_07_config_roundtrip_and_clamp(self):
        path = os.path.join(self.home, ".config", "devos", "optimizer.json")
        save_config({"idle_minutes": 3, "never_ask": ["Chrome"], "paused_until": 0}, path)
        cfg = load_config(path)
        self.assertEqual(cfg["idle_minutes"], 10)
        self.assertEqual(cfg["never_ask"], ["chrome"])


class TestOptimizerProcesses(unittest.TestCase):

    def test_08_process_tree_rss_and_app_root(self):
        uid = os.getuid()
        table = {
            100: {"comm": "chrome", "ppid": 1, "uid": uid, "rss": 300 * MB, "cpu": 1.0},
            101: {"comm": "chrome", "ppid": 100, "uid": uid, "rss": 200 * MB, "cpu": 1.0},
            102: {"comm": "chrome", "ppid": 101, "uid": uid, "rss": 100 * MB, "cpu": 1.0},
            103: {"comm": "cat", "ppid": 100, "uid": uid, "rss": 1 * MB, "cpu": 0.0},
            200: {"comm": "kate", "ppid": 1, "uid": uid, "rss": 50 * MB, "cpu": 0.0},
        }
        self.assertEqual(tree_rss(100, table), 601 * MB)
        self.assertEqual(app_root(102, table), 100)
        self.assertEqual(app_root(200, table), 200)
        apps = optimizer.collect_apps(table=table, windows={102: ["0x1"], 200: ["0x2"]},
                                      my_uid=uid, my_pid=99999)
        self.assertIn("chrome:100", apps)
        self.assertEqual(apps["chrome:100"]["rss"], 601 * MB)
        self.assertEqual(apps["chrome:100"]["name"], "Chrome")

    def test_09_parse_wmctrl(self):
        text = ("0x01e00003 -1 1234 host plasmashell\n"
                "0x03400003  0 2222 host Some page - Google Chrome\n"
                "0x03400010  0 2222 host Other window\n"
                "0x05000001  1 0    host no pid\n")
        self.assertEqual(parse_wmctrl(text), {2222: ["0x03400003", "0x03400010"]})


class TestIdleDecisions(unittest.TestCase):

    def test_10_idle_threshold_15_minutes(self):
        t = IdleTracker(idle_minutes=15)
        chrome = app("chrome", 100, 1200, cpu=10.0)
        t.update(0, {chrome["key"]: chrome})
        t.update(14 * 60, {chrome["key"]: chrome})
        self.assertEqual(t.candidates(14 * 60), [])
        t.update(15 * 60, {chrome["key"]: chrome})
        self.assertEqual([a["key"] for a in t.candidates(15 * 60)], ["chrome:100"])
        self.assertIn("Chrome hasn't been used for 15 min and is using 1.2 GB",
                      optimizer.suggestion_text(chrome, t.idle_minutes_of("chrome:100", 15 * 60)))

    def test_11_cpu_activity_resets_idle(self):
        t = IdleTracker(idle_minutes=15)
        vlc = app("vlc", 300, 400, cpu=0.0)
        t.update(0, {vlc["key"]: vlc})
        busy = dict(vlc, cpu=30.0)  # 30 CPU-seconds over 600 s = 5% -> active
        t.update(10 * 60, {busy["key"]: busy})
        t.update(20 * 60, {busy["key"]: busy})  # now idle (0% since last sample)
        self.assertEqual(t.candidates(20 * 60), [])
        self.assertAlmostEqual(t.idle_minutes_of("vlc:300", 20 * 60), 10.0)
        t.update(25 * 60, {busy["key"]: busy})
        self.assertEqual(len(t.candidates(25 * 60)), 1)

    def test_12_focus_resets_idle(self):
        t = IdleTracker(idle_minutes=15)
        code = app("codium", 400, 800)
        t.update(0, {code["key"]: code})
        t.update(20 * 60, {code["key"]: code}, focused_key=code["key"])
        self.assertEqual(t.candidates(20 * 60), [])

    def test_13_protected_small_and_foreign_never_suggested(self):
        t = IdleTracker(idle_minutes=15)
        apps = {}
        for a in (app("plasmashell", 10, 900), app("kwin_x11", 11, 500),
                  app("xorg", 12, 600), app("kate", 13, 60),
                  app("firefox", 14, 900, protected=True)):
            apps[a["key"]] = a
        t.update(0, apps)
        t.update(60 * 60, apps)
        self.assertEqual(t.candidates(60 * 60), [])
        self.assertTrue(optimizer.is_protected("Xorg"))
        self.assertTrue(optimizer.is_protected("chrome", pid=500, uid=0, my_uid=1000))
        self.assertTrue(optimizer.is_protected("chrome", pid=777, uid=1000, my_uid=1000, my_pid=777))
        self.assertFalse(optimizer.is_protected("chrome", pid=500, uid=1000, my_uid=1000, my_pid=1))

    def test_14_allowlist_respected(self):
        t = IdleTracker(idle_minutes=15, never_ask=["Chrome"])
        chrome, gimp = app("chrome", 100, 1500), app("gimp", 200, 700)
        apps = {chrome["key"]: chrome, gimp["key"]: gimp}
        t.update(0, apps)
        t.update(30 * 60, apps)
        self.assertEqual([a["comm"] for a in t.candidates(30 * 60)], ["gimp"])

    def test_15_idle_minutes_minimum_is_10(self):
        self.assertEqual(IdleTracker(idle_minutes=5).idle_minutes, 10)
        self.assertEqual(IdleTracker(idle_minutes=20).idle_minutes, 20)

    def test_16_suggestion_rate_limit(self):
        lim = SuggestionLimiter(interval_s=600)
        self.assertTrue(lim.can_suggest(1000))
        lim.record(1000)
        self.assertFalse(lim.can_suggest(1000 + 599))
        self.assertTrue(lim.can_suggest(1000 + 600))
        lim.pause(2000, 3600)
        self.assertFalse(lim.can_suggest(2000 + 3599))
        self.assertTrue(lim.can_suggest(2000 + 3600))

    def test_17_ai_summary_has_no_file_names(self):
        apps = {"chrome:1": app("chrome", 1, 1200), "kate:2": app("kate", 2, 80)}
        scan = [{"label": "Old downloads", "size": 5 * GB, "_files": [("/home/u/secret.pdf", 1)]}]
        summary = optimizer.build_ai_summary(apps, [{"path": "/", "total": 100 * GB, "free": 20 * GB}],
                                             optimizer.public_scan(scan))
        self.assertIn("Chrome 1200 MB", summary)
        self.assertNotIn("secret", summary)

    def test_18_ai_unreachable_message(self):
        msg = optimizer.ask_ai("hi", url="http://127.0.0.1:9/v1/chat/completions", timeout=2)
        self.assertEqual(msg, optimizer.AI_UNAVAILABLE_MSG)

    def test_19_live_session_detection(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash\n")
        try:
            self.assertTrue(optimizer.is_live_session(fh.name))
        finally:
            os.remove(fh.name)
        self.assertFalse(optimizer.is_live_session("/nonexistent/cmdline"))


    def test_20_devos_ai_identity_and_protection(self):
        # DevOS AI Core names in PROTECTED_NAMES
        self.assertTrue(optimizer.is_protected("devos-ai"))
        self.assertTrue(optimizer.is_protected("devos-ai-core"))
        self.assertTrue(optimizer.is_protected("devos-ai-code-agent"))
        self.assertTrue(optimizer.is_protected("devos-chat"))
        
        # Test simulated /proc cmdline resolution
        fake_proc = tempfile.mkdtemp(prefix="fake-proc-")
        try:
            pid_dir = os.path.join(fake_proc, "9999")
            os.makedirs(pid_dir)
            with open(os.path.join(pid_dir, "cmdline"), "wb") as f:
                f.write(b"python3\x00/usr/local/share/devos/components/code-agent/agent_gui.py\x00")
            name, prot = optimizer.resolve_app_identity("python3", pid=9999, proc_root=fake_proc)
            self.assertEqual(name, "DevOS AI Code Agent")
            self.assertTrue(prot)
            self.assertTrue(optimizer.is_protected("python3", pid=9999, proc_root=fake_proc))
            
            # Simulated DevOS AI Core server.py
            with open(os.path.join(pid_dir, "cmdline"), "wb") as f:
                f.write(b"python3\x00/usr/local/share/devos/components/ai-core/server.py\x00")
            name, prot = optimizer.resolve_app_identity("python3", pid=9999, proc_root=fake_proc)
            self.assertEqual(name, "DevOS AI Core (Local Neural Engine & API)")
            self.assertTrue(prot)

            # Simulated DevOS AI Chat assistant.py
            with open(os.path.join(pid_dir, "cmdline"), "wb") as f:
                f.write(b"python3\x00/usr/local/share/devos/components/assistant/assistant.py\x00")
            name, prot = optimizer.resolve_app_identity("python3", pid=9999, proc_root=fake_proc)
            self.assertEqual(name, "DevOS AI Chat")
            self.assertTrue(prot)
        finally:
            shutil.rmtree(fake_proc, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

