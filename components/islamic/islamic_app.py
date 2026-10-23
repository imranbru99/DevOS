#!/usr/bin/env python3
"""
DevOS Islamic - prayer times, Qibla, Hijri date, Ayah and Hadith of the day.

Opt-in: nothing runs and nothing is downloaded until the user presses
"Turn on" (or runs `devos-islamic enable`).

CLI:
  islamic_app.py [gui]               open the window (default)
  islamic_app.py enable              download the verified texts if missing (system-wide via
                                     pkexec, or into your home folder if that is declined) and
                                     start the reminder service for this account
  islamic_app.py disable             stop the reminder service (texts are kept)
  islamic_app.py times [--date D]    print the day's prayer times (D = YYYY-MM-DD)
  islamic_app.py today               today's times, Hijri date, Qibla, ayah and hadith as JSON
  islamic_app.py fetch-content [--system|--user]
                                     download + verify the Quran and Hadith texts

Settings live in ~/.config/devos/islamic.json (see notifier.DEFAULTS).
Everything above the GUI section is plain stdlib so it can be unit-tested;
PyQt5 is imported only when the window opens.
"""

import argparse
import datetime as _dt
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import content  # noqa: E402
import notifier  # noqa: E402
import prayer_times as pt  # noqa: E402

APP_NAME = "DevOS Islamic"
SERVICE = "devos-islamic.service"
LAUNCHER = "/usr/local/bin/devos-islamic"
TEXT_SIZE_NOTE = "about 55 MB, downloaded once"


# ---------------------------------------------------------------------------
# Plain logic shared by the CLI and the window
# ---------------------------------------------------------------------------

def today_info(settings, now=None):
    """Everything the 'Today' screen shows, as plain data (also the `today` JSON)."""
    loc = pt.resolve_location(settings)
    now = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(loc["tz"])
    times = pt.times_for_settings(now.date(), settings)
    nxt = pt.next_prayer(times, now)
    if nxt is None:  # after Isha: the next one is tomorrow's Fajr
        tomorrow = pt.times_for_settings(now.date() + _dt.timedelta(days=1), settings)
        nxt = ("fajr", tomorrow["fajr"])
    y, m, d = pt.hijri_date(now.date(), settings.get("hijri_adjust", 0))
    return {
        "location": {"name": loc["name"], "lat": loc["lat"], "lon": loc["lon"],
                     "tz": str(getattr(loc["tz"], "key", loc["tz"]))},
        "date": now.date().isoformat(),
        "gregorian": now.strftime("%A, %d %B %Y"),
        "hijri": {"year": y, "month": m, "day": d, "month_name": pt.HIJRI_MONTHS[m - 1],
                  "month_arabic": pt.HIJRI_MONTHS_AR[m - 1],
                  "text": "%d %s %d AH" % (d, pt.HIJRI_MONTHS[m - 1], y)},
        "method": pt.METHODS[settings["method"]]["name"],
        "asr": "Hanafi" if settings["asr"] == "hanafi" else "Shafi'i / Maliki / Hanbali",
        "times": {k: v.strftime("%H:%M") for k, v in times.items()},
        "next": {"prayer": nxt[0], "at": nxt[1].isoformat(timespec="minutes"),
                 "seconds": int((nxt[1] - now).total_seconds())},
        "qibla": round(pt.qibla(loc["lat"], loc["lon"]), 1),
        "qibla_point": pt.compass_point(pt.qibla(loc["lat"], loc["lon"])),
        "_times": times, "_now": now,
    }


def arabic_digits(number):
    return str(number).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def format_countdown(seconds):
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def service_enabled():
    if not shutil.which("systemctl"):
        return False
    out = subprocess.run(["systemctl", "--user", "is-enabled", SERVICE],
                         capture_output=True, text=True)
    return out.stdout.strip() == "enabled"


def _self_command():
    if os.path.exists(LAUNCHER):
        return [LAUNCHER]
    return [sys.executable, os.path.abspath(__file__)]


def ensure_content(log=print):
    """Texts present? If not: system-wide via pkexec, else into the home folder."""
    if content.have_content():
        return content.data_dir()
    if content.is_root():
        return content.fetch_content(content.SYSTEM_DIR, log)
    if shutil.which("pkexec"):
        log("Asking for administrator approval to save the texts for every account on this PC…")
        rc = subprocess.call(["pkexec"] + _self_command() + ["fetch-content", "--system"])
        if rc == 0 and content.have_content():
            return content.data_dir()
        log("Saving the texts in your home folder instead.")
    return content.fetch_content(content.user_dir(), log)


def cmd_enable(_args):
    try:
        ensure_content()
    except content.ContentError as exc:
        # Prayer reminders work without the texts, so still turn them on.
        print("Texts not downloaded yet: %s" % exc)
    if not os.path.exists(notifier.settings_path()):
        notifier.save_settings(notifier.load_settings())
    rc = subprocess.call(["systemctl", "--user", "enable", "--now", SERVICE])
    print("Prayer reminders are on." if rc == 0 else "Could not start the reminder service.")
    return rc


def cmd_disable(_args):
    rc = subprocess.call(["systemctl", "--user", "disable", "--now", SERVICE])
    print("Prayer reminders are off." if rc == 0 else "Could not stop the reminder service.")
    return rc


def cmd_times(args):
    settings = notifier.load_settings()
    loc = pt.resolve_location(settings)
    day = _dt.date.fromisoformat(args.date) if args.date else _dt.datetime.now(loc["tz"]).date()
    times = pt.times_for_settings(day, settings)
    print("%s · %s · %s" % (loc["name"], day.strftime("%a %d %b %Y"),
                            pt.hijri_text(day, settings.get("hijri_adjust", 0))))
    print("%s, Asr %s" % (pt.METHODS[settings["method"]]["name"], settings["asr"].capitalize()))
    for name in pt.PRAYERS:
        print("  %-8s %s" % (pt.PRAYER_LABELS[name], times[name].strftime("%H:%M")))
    return 0


def cmd_today(_args):
    settings = notifier.load_settings()
    info = today_info(settings)
    day = _dt.date.fromisoformat(info["date"])
    out = {k: v for k, v in info.items() if not k.startswith("_")}
    out["ayah"] = content.ayah_of_the_day(day)
    out["hadith"] = content.hadith_of_the_day(day)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_fetch(args):
    if args.system and not content.is_root():
        print("--system needs administrator rights (run through pkexec).")
        return 1
    target = content.SYSTEM_DIR if args.system else (content.user_dir() if args.user else None)
    try:
        # flush=True so the window's progress line updates while it downloads
        content.fetch_content(target, lambda msg: print(msg, flush=True))
    except (content.ContentError, OSError) as exc:
        print("Download failed: %s" % exc)
        return 1
    return 0


# ---------------------------------------------------------------------------
# GUI (PyQt5 imported lazily)
# ---------------------------------------------------------------------------

STYLE = """
QWidget { background: #0b0f1a; color: #e2e8f0; font-family: "Inter", "Noto Sans"; font-size: 14px; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QLabel#title { font-size: 26px; font-weight: 700; color: #f8fafc; }
QLabel#hijri { font-size: 19px; font-weight: 600; color: #f8fafc; }
QLabel#muted { color: #94a3b8; }
QLabel#small { color: #64748b; font-size: 12px; }
QLabel#section { font-size: 16px; font-weight: 600; color: #f8fafc; }
QLabel#countdown { font-size: 40px; font-weight: 700; color: #f8fafc; }
QLabel#nextname { font-size: 15px; font-weight: 600; color: #7dd3fc; }
QLabel#ailabel { color: #fbbf24; font-size: 12px; font-weight: 600; }
QLabel#reference { color: #7dd3fc; font-size: 13px; font-weight: 600; }
QFrame#card { background: #0f172a; border: 1px solid #1e293b; border-radius: 16px; }
QFrame#hero { border: 1px solid #1e3a5f; border-radius: 18px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0c4a6e, stop:0.55 #0f172a, stop:1 #111827); }
QFrame#tile { background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; }
QFrame#tileNext { border: 1px solid #38bdf8; border-radius: 14px;
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0369a1, stop:1 #0c4a6e); }
QFrame#aibox { background: #111827; border: 1px dashed #334155; border-radius: 10px; }
QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 9px; padding: 7px 14px; color: #e2e8f0; }
QPushButton:hover { border-color: #38bdf8; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0ea5e9);
  border-color: #38bdf8; color: white; font-weight: 600; }
QPushButton#nav { background: transparent; border: 1px solid transparent; color: #94a3b8; font-weight: 600; }
QPushButton#nav:checked { background: #0f172a; border-color: #1e293b; color: #f8fafc; }
QPushButton#seg { background: #0b1220; border: 1px solid #1e293b; border-radius: 8px; padding: 4px 10px; color: #94a3b8; }
QPushButton#seg:checked { background: #0c4a6e; border-color: #38bdf8; color: #f8fafc; }
QPushButton:disabled { color: #64748b; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {
  background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 6px; }
QListWidget { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; }
QListWidget::item:selected { background: #0c4a6e; }
QCheckBox::indicator { width: 16px; height: 16px; }
QScrollArea { border: none; background: #0f172a; }
QWidget#cardbody { background: #0f172a; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #334155; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def run_gui(screenshot=None):
    from PyQt5 import QtCore, QtGui, QtWidgets

    def pick_family(candidates, fallback):
        families = set(QtGui.QFontDatabase().families())
        for name in candidates:
            if name in families:
                return name
        return fallback

    class AiWorker(QtCore.QThread):
        done = QtCore.pyqtSignal(str)

        def __init__(self, item, lang, parent=None):
            super().__init__(parent)
            self.item, self.lang = item, lang

        def run(self):
            self.done.emit(content.ai_reflection(self.item, self.lang))

    class QiblaDial(QtWidgets.QWidget):
        """A compass rose with a needle at the Qibla bearing (from true north)."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.bearing = 0.0
            self.setMinimumSize(210, 210)

        def set_bearing(self, bearing):
            self.bearing = bearing
            self.update()

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            side = min(self.width(), self.height()) - 8
            p.translate(self.width() / 2, self.height() / 2)
            r = side / 2
            grad = QtGui.QRadialGradient(0, 0, r)
            grad.setColorAt(0, QtGui.QColor("#13213a"))
            grad.setColorAt(1, QtGui.QColor("#0b1220"))
            p.setBrush(grad)
            p.setPen(QtGui.QPen(QtGui.QColor("#1e3a5f"), 2))
            p.drawEllipse(QtCore.QPointF(0, 0), r, r)
            for deg in range(0, 360, 15):
                p.save()
                p.rotate(deg)
                major = deg % 90 == 0
                p.setPen(QtGui.QPen(QtGui.QColor("#38bdf8" if major else "#334155"), 2 if major else 1))
                p.drawLine(QtCore.QPointF(0, -r + 4), QtCore.QPointF(0, -r + (14 if major else 9)))
                p.restore()
            font = p.font()
            font.setPointSizeF(max(8.0, r / 9))
            font.setBold(True)
            p.setFont(font)
            for label, deg in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
                rad = math.radians(deg)
                x, y = math.sin(rad) * (r - 28), -math.cos(rad) * (r - 28)
                p.setPen(QtGui.QColor("#f8fafc" if label == "N" else "#94a3b8"))
                p.drawText(QtCore.QRectF(x - 12, y - 12, 24, 24), QtCore.Qt.AlignCenter, label)
            # needle
            p.save()
            p.rotate(self.bearing)
            needle = QtGui.QPolygonF([QtCore.QPointF(0, -r + 34), QtCore.QPointF(7, 0),
                                      QtCore.QPointF(0, 10), QtCore.QPointF(-7, 0)])
            ng = QtGui.QLinearGradient(0, -r, 0, 10)
            ng.setColorAt(0, QtGui.QColor("#fbbf24"))
            ng.setColorAt(1, QtGui.QColor("#38bdf8"))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(ng)
            p.drawPolygon(needle)
            # Kaaba marker at the tip
            p.setBrush(QtGui.QColor("#111827"))
            p.setPen(QtGui.QPen(QtGui.QColor("#fbbf24"), 1.5))
            p.drawRect(QtCore.QRectF(-7, -r + 18, 14, 14))
            p.restore()
            p.setBrush(QtGui.QColor("#e2e8f0"))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(QtCore.QPointF(0, 0), 4, 4)
            p.end()

    class TextCard(QtWidgets.QFrame):
        """Ayah / Hadith card: Arabic (RTL) + translation + source + optional AI reflection."""

        def __init__(self, title, fonts, parent=None):
            super().__init__(parent)
            self.setObjectName("card")
            self.fonts = fonts
            self.item = None
            self.lang = "bn"
            self.worker = None
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(18, 16, 18, 16)
            outer.setSpacing(10)
            head = QtWidgets.QHBoxLayout()
            label = QtWidgets.QLabel(title)
            label.setObjectName("section")
            head.addWidget(label)
            head.addStretch(1)
            self.seg = QtWidgets.QButtonGroup(self)
            for code, text in (("bn", "বাংলা"), ("en", "English"), ("both", "Both")):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("seg")
                b.setCheckable(True)
                b.setProperty("lang", code)
                if code == "bn":
                    b.setStyleSheet("font-family: '%s';" % fonts["bn"])
                self.seg.addButton(b)
                head.addWidget(b)
            self.seg.buttonClicked.connect(lambda b: self.set_lang(b.property("lang")))
            outer.addLayout(head)

            self.ref = QtWidgets.QLabel("")
            self.ref.setObjectName("reference")
            self.ref.setWordWrap(True)
            outer.addWidget(self.ref)

            body = QtWidgets.QWidget()
            body.setObjectName("cardbody")
            self.body_layout = QtWidgets.QVBoxLayout(body)
            self.body_layout.setContentsMargins(0, 0, 6, 0)
            self.body_layout.setSpacing(10)
            self.arabic = QtWidgets.QLabel("")
            self.arabic.setWordWrap(True)
            # AlignAbsolute: keep it on the right even though the paragraph is RTL
            # (plain AlignRight is mirrored to the left for right-to-left text).
            self.arabic.setLayoutDirection(QtCore.Qt.RightToLeft)
            self.arabic.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignAbsolute | QtCore.Qt.AlignTop)
            # Fonts go in the label's own style sheet: the window-wide QWidget rule
            # would otherwise override setFont() and shrink the Arabic to 14px.
            self.arabic.setStyleSheet("color: #f8fafc; font-family: '%s'; font-size: 27px;" % fonts["ar"])
            self.arabic.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.bn = QtWidgets.QLabel("")
            self.bn.setWordWrap(True)
            self.bn.setStyleSheet("font-family: '%s'; font-size: 16px; color: #e2e8f0;" % fonts["bn"])
            self.bn.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.en = QtWidgets.QLabel("")
            self.en.setWordWrap(True)
            self.en.setStyleSheet("font-size: 15px; color: #cbd5e1;")
            self.en.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            for w in (self.arabic, self.bn, self.en):
                self.body_layout.addWidget(w)
            self.body_layout.addStretch(1)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(body)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            outer.addWidget(scroll, 1)

            self.translator = QtWidgets.QLabel("")
            self.translator.setObjectName("small")
            self.translator.setWordWrap(True)
            outer.addWidget(self.translator)

            row = QtWidgets.QHBoxLayout()
            self.explain = QtWidgets.QPushButton("✦  Explain with DevOS AI")
            self.explain.clicked.connect(self.ask_ai)
            row.addWidget(self.explain)
            row.addStretch(1)
            outer.addLayout(row)
            self.aibox = QtWidgets.QFrame()
            self.aibox.setObjectName("aibox")
            ai_layout = QtWidgets.QVBoxLayout(self.aibox)
            ai_layout.setContentsMargins(12, 10, 12, 10)
            ai_label = QtWidgets.QLabel(content.AI_LABEL)
            ai_label.setObjectName("ailabel")
            ai_label.setWordWrap(True)
            self.ai_text = QtWidgets.QLabel("")
            self.ai_text.setWordWrap(True)
            self.ai_text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            ai_layout.addWidget(ai_label)
            ai_layout.addWidget(self.ai_text)
            self.aibox.hide()
            outer.addWidget(self.aibox)

        def set_lang(self, lang):
            self.lang = lang
            for b in self.seg.buttons():
                b.setChecked(b.property("lang") == lang)
            self.bn.setVisible(lang in ("bn", "both"))
            self.en.setVisible(lang in ("en", "both"))
            self.show_translators()

        def show_translators(self):
            if not self.item:
                return
            tr = self.item["translators"]
            parts = ["Arabic: %s" % tr.get("ar", "")]
            if self.lang in ("bn", "both"):
                parts.append("Bangla: %s" % tr.get("bn", ""))
            if self.lang in ("en", "both"):
                parts.append("English: %s" % tr.get("en", ""))
            self.translator.setText("  ·  ".join(parts))

        def set_item(self, item, missing_text=""):
            self.item = item
            self.aibox.hide()
            self.explain.setEnabled(bool(item))
            if not item:
                self.ref.setText("")
                self.arabic.hide()
                self.bn.hide()
                self.en.setText(missing_text)
                self.en.show()
                self.translator.setText("")
                return
            self.ref.setText(item["reference"])
            self.arabic.show()
            self.arabic.setText(item["ar"])
            self.bn.setText(item["bn"])
            self.en.setText(item["en"])
            self.set_lang(self.lang)

        def ask_ai(self):
            if not self.item or self.worker:
                return
            self.explain.setEnabled(False)
            self.explain.setText("Thinking…")
            self.aibox.show()
            self.ai_text.setText("DevOS AI is writing a short reflection…")
            lang = "bn" if self.lang == "bn" else "en"
            self.worker = AiWorker(self.item, lang, self)
            self.worker.done.connect(self.ai_done)
            self.worker.start()

        def ai_done(self, text):
            self.ai_text.setText(text)
            self.explain.setEnabled(True)
            self.explain.setText("✦  Explain with DevOS AI")
            self.worker = None

    class IslamicWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(APP_NAME)
            self.resize(1180, 820)
            self.setStyleSheet(STYLE)
            self.settings = notifier.load_settings()
            self.fonts = {
                # Amiri Quran (fonts-hosny-amiri) if the user installed it, else Noto Naskh
                # Arabic from fonts-noto-core, which covers every mark in the Uthmani text.
                "ar": pick_family(["Amiri Quran", "Noto Naskh Arabic", "Amiri", "Noto Sans Arabic"], "Sans"),
                "bn": pick_family(["Noto Sans Bengali", "Noto Serif Bengali", "Lohit Bengali"], "Sans"),
            }
            self.info = None
            self.loaded_day = None
            self.proc = None

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(24, 18, 24, 18)
            root.setSpacing(14)

            # --- header
            header = QtWidgets.QHBoxLayout()
            titles = QtWidgets.QVBoxLayout()
            titles.setSpacing(2)
            title = QtWidgets.QLabel("DevOS Islamic")
            title.setObjectName("title")
            self.subtitle = QtWidgets.QLabel("")
            self.subtitle.setObjectName("muted")
            titles.addWidget(title)
            titles.addWidget(self.subtitle)
            header.addLayout(titles)
            header.addStretch(1)
            self.nav = QtWidgets.QButtonGroup(self)
            for i, text in enumerate(("Today", "Settings")):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("nav")
                b.setCheckable(True)
                b.setChecked(i == 0)
                self.nav.addButton(b, i)
                header.addWidget(b)
            self.nav.buttonClicked[int].connect(lambda i: self.stack.setCurrentIndex(i))
            root.addLayout(header)

            self.stack = QtWidgets.QStackedWidget()
            self.stack.addWidget(self.build_today())
            self.stack.addWidget(self.build_settings())
            root.addWidget(self.stack, 1)

            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(1000)
            self.refresh()

        # ----- Today page
        def build_today(self):
            page = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(page)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(14)

            hero = QtWidgets.QFrame()
            hero.setObjectName("hero")
            h = QtWidgets.QHBoxLayout(hero)
            h.setContentsMargins(22, 16, 22, 16)
            dates = QtWidgets.QVBoxLayout()
            self.hijri_ar = QtWidgets.QLabel("")
            self.hijri_ar.setStyleSheet("color: #fbbf24; font-family: '%s'; font-size: 22px;" % self.fonts["ar"])
            self.hijri = QtWidgets.QLabel("")
            self.hijri.setObjectName("hijri")
            self.greg = QtWidgets.QLabel("")
            self.greg.setObjectName("muted")
            self.place = QtWidgets.QLabel("")
            self.place.setObjectName("small")
            for w in (self.hijri_ar, self.hijri, self.greg, self.place):
                dates.addWidget(w)
            h.addLayout(dates)
            h.addStretch(1)
            nextbox = QtWidgets.QVBoxLayout()
            nextbox.setSpacing(0)
            self.next_name = QtWidgets.QLabel("")
            self.next_name.setObjectName("nextname")
            self.next_name.setAlignment(QtCore.Qt.AlignRight)
            self.countdown = QtWidgets.QLabel("")
            self.countdown.setObjectName("countdown")
            self.countdown.setAlignment(QtCore.Qt.AlignRight)
            self.next_at = QtWidgets.QLabel("")
            self.next_at.setObjectName("muted")
            self.next_at.setAlignment(QtCore.Qt.AlignRight)
            for w in (self.next_name, self.countdown, self.next_at):
                nextbox.addWidget(w)
            h.addLayout(nextbox)
            grid.addWidget(hero, 0, 0, 1, 2)

            tiles = QtWidgets.QHBoxLayout()
            tiles.setSpacing(10)
            self.tiles = {}
            for name in pt.PRAYERS:
                f = QtWidgets.QFrame()
                f.setObjectName("tile")
                v = QtWidgets.QVBoxLayout(f)
                v.setContentsMargins(14, 10, 14, 10)
                n = QtWidgets.QLabel(pt.PRAYER_LABELS[name])
                n.setStyleSheet("color: #94a3b8; font-weight: 600;")
                t = QtWidgets.QLabel("--:--")
                t.setStyleSheet("font-size: 24px; font-weight: 700; color: #f8fafc;")
                v.addWidget(n)
                v.addWidget(t)
                tiles.addWidget(f)
                self.tiles[name] = (f, n, t)
            grid.addLayout(tiles, 1, 0, 1, 2)

            cards = QtWidgets.QHBoxLayout()
            cards.setSpacing(14)
            self.ayah_card = TextCard("Ayah of the day", self.fonts)
            self.hadith_card = TextCard("Hadith of the day", self.fonts)
            cards.addWidget(self.ayah_card, 1)
            cards.addWidget(self.hadith_card, 1)
            grid.addLayout(cards, 2, 0)

            side = QtWidgets.QFrame()
            side.setObjectName("card")
            side.setFixedWidth(270)
            s = QtWidgets.QVBoxLayout(side)
            s.setContentsMargins(16, 14, 16, 14)
            q = QtWidgets.QLabel("Qibla direction")
            q.setObjectName("section")
            s.addWidget(q)
            self.dial = QiblaDial()
            s.addWidget(self.dial, 1)
            self.qibla_text = QtWidgets.QLabel("")
            self.qibla_text.setAlignment(QtCore.Qt.AlignCenter)
            self.qibla_text.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
            s.addWidget(self.qibla_text)
            hint = QtWidgets.QLabel("Degrees clockwise from true north. Line up north with a compass "
                                    "or your phone, then face the gold marker.")
            hint.setObjectName("small")
            hint.setWordWrap(True)
            s.addWidget(hint)
            s.addSpacing(8)
            self.reminder_state = QtWidgets.QLabel("")
            self.reminder_state.setObjectName("muted")
            self.reminder_state.setWordWrap(True)
            s.addWidget(self.reminder_state)
            self.toggle_btn = QtWidgets.QPushButton("")
            self.toggle_btn.setObjectName("primary")
            self.toggle_btn.clicked.connect(self.toggle_service)
            s.addWidget(self.toggle_btn)
            self.method_text = QtWidgets.QLabel("")
            self.method_text.setObjectName("small")
            self.method_text.setWordWrap(True)
            s.addWidget(self.method_text)
            grid.addWidget(side, 2, 1)
            grid.setRowStretch(2, 1)
            return page

        # ----- Settings page
        def build_settings(self):
            page = QtWidgets.QWidget()
            cols = QtWidgets.QHBoxLayout(page)
            cols.setContentsMargins(0, 0, 0, 0)
            cols.setSpacing(14)

            loc = QtWidgets.QFrame()
            loc.setObjectName("card")
            l = QtWidgets.QVBoxLayout(loc)
            l.setContentsMargins(18, 16, 18, 16)
            t = QtWidgets.QLabel("Location")
            t.setObjectName("section")
            l.addWidget(t)
            self.city_search = QtWidgets.QLineEdit()
            self.city_search.setPlaceholderText("Search a city — e.g. Dhaka, Sylhet, London, Makkah")
            self.city_search.textChanged.connect(self.fill_cities)
            l.addWidget(self.city_search)
            self.city_list = QtWidgets.QListWidget()
            l.addWidget(self.city_list, 1)
            self.manual = QtWidgets.QCheckBox("Use my own coordinates instead")
            l.addWidget(self.manual)
            form = QtWidgets.QFormLayout()
            self.lat = QtWidgets.QDoubleSpinBox()
            self.lat.setRange(-90, 90)
            self.lat.setDecimals(4)
            self.lon = QtWidgets.QDoubleSpinBox()
            self.lon.setRange(-180, 180)
            self.lon.setDecimals(4)
            self.tzname = QtWidgets.QLineEdit()
            self.tzname.setPlaceholderText("Time zone, e.g. Asia/Dhaka")
            form.addRow("Latitude", self.lat)
            form.addRow("Longitude", self.lon)
            form.addRow("Time zone", self.tzname)
            l.addLayout(form)
            cols.addWidget(loc, 1)

            calc = QtWidgets.QFrame()
            calc.setObjectName("card")
            c = QtWidgets.QVBoxLayout(calc)
            c.setContentsMargins(18, 16, 18, 16)
            t = QtWidgets.QLabel("Calculation")
            t.setObjectName("section")
            c.addWidget(t)
            f2 = QtWidgets.QFormLayout()
            self.method = QtWidgets.QComboBox()
            for key, m in pt.METHODS.items():
                self.method.addItem(m["name"], key)
            self.asr = QtWidgets.QComboBox()
            self.asr.addItem("Hanafi (later Asr)", "hanafi")
            self.asr.addItem("Shafi'i, Maliki, Hanbali", "shafi")
            self.hijri_adj = QtWidgets.QSpinBox()
            self.hijri_adj.setRange(-2, 2)
            self.hijri_adj.setSuffix(" day(s)")
            f2.addRow("Method", self.method)
            f2.addRow("Asr", self.asr)
            f2.addRow("Hijri date adjust", self.hijri_adj)
            c.addLayout(f2)
            note = QtWidgets.QLabel("Bangladesh, Pakistan and India mostly use Karachi + Hanafi. "
                                    "If your local mosque or moon sighting differs by a day, adjust the Hijri date.")
            note.setObjectName("small")
            note.setWordWrap(True)
            c.addWidget(note)

            t = QtWidgets.QLabel("Notifications")
            t.setObjectName("section")
            c.addSpacing(8)
            c.addWidget(t)
            self.at_prayer = QtWidgets.QCheckBox("Notify me at each prayer time")
            c.addWidget(self.at_prayer)
            f3 = QtWidgets.QFormLayout()
            self.before = QtWidgets.QSpinBox()
            self.before.setRange(0, 120)
            self.before.setSuffix(" min before (0 = off)")
            f3.addRow("Reminder", self.before)
            c.addLayout(f3)
            self.daily = QtWidgets.QCheckBox("Daily Ayah and Hadith notification at")
            self.daily_time = QtWidgets.QTimeEdit()
            self.daily_time.setDisplayFormat("HH:mm")
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.daily)
            row.addWidget(self.daily_time)
            row.addStretch(1)
            c.addLayout(row)
            f4 = QtWidgets.QFormLayout()
            self.language = QtWidgets.QComboBox()
            self.language.addItem("বাংলা (Bangla)", "bn")
            self.language.addItem("English", "en")
            f4.addRow("Translation", self.language)
            c.addLayout(f4)
            snd = QtWidgets.QHBoxLayout()
            self.sound = QtWidgets.QLineEdit()
            self.sound.setReadOnly(True)
            self.sound.setPlaceholderText("No sound (DevOS does not include an adhan)")
            choose = QtWidgets.QPushButton("Choose…")
            choose.clicked.connect(self.choose_sound)
            clear = QtWidgets.QPushButton("Clear")
            clear.clicked.connect(lambda: self.sound.setText(""))
            test = QtWidgets.QPushButton("Test")
            test.clicked.connect(lambda: notifier.notify("DevOS Islamic", "This is how a prayer reminder looks.",
                                                         self.sound.text()))
            snd.addWidget(self.sound, 1)
            snd.addWidget(choose)
            snd.addWidget(clear)
            snd.addWidget(test)
            c.addWidget(QtWidgets.QLabel("Sound at prayer time (your own audio file)"))
            c.addLayout(snd)
            c.addStretch(1)
            self.fetch_status = QtWidgets.QLabel("")
            self.fetch_status.setObjectName("muted")
            self.fetch_status.setWordWrap(True)
            c.addWidget(self.fetch_status)
            buttons = QtWidgets.QHBoxLayout()
            self.fetch_btn = QtWidgets.QPushButton("Download Quran && Hadith texts")
            self.fetch_btn.clicked.connect(self.fetch_texts)
            save = QtWidgets.QPushButton("Save")
            save.setObjectName("primary")
            save.clicked.connect(self.save)
            buttons.addWidget(self.fetch_btn)
            buttons.addStretch(1)
            buttons.addWidget(save)
            c.addLayout(buttons)
            cols.addWidget(calc, 1)
            self.load_form()
            return page

        def load_form(self):
            s = self.settings
            self.city_search.setText("")
            self.fill_cities("")
            items = self.city_list.findItems(s.get("city", "Dhaka"), QtCore.Qt.MatchExactly)
            if items:
                self.city_list.setCurrentItem(items[0])
            m = s.get("manual") or {}
            self.manual.setChecked(bool(s.get("manual")))
            self.lat.setValue(float(m.get("lat", 23.8103)))
            self.lon.setValue(float(m.get("lon", 90.4125)))
            self.tzname.setText(m.get("tz", "Asia/Dhaka"))
            self.method.setCurrentIndex(max(0, self.method.findData(s["method"])))
            self.asr.setCurrentIndex(max(0, self.asr.findData(s["asr"])))
            self.hijri_adj.setValue(int(s.get("hijri_adjust", 0)))
            self.at_prayer.setChecked(bool(s.get("notify_at_prayer", True)))
            self.before.setValue(int(s.get("remind_before_min", 10)))
            self.daily.setChecked(bool(s.get("daily_text", True)))
            hh, mm = notifier._parse_hhmm(s.get("daily_time"))
            self.daily_time.setTime(QtCore.QTime(hh, mm))
            self.language.setCurrentIndex(max(0, self.language.findData(s.get("language", "bn"))))
            self.sound.setText(s.get("sound", ""))

        def fill_cities(self, text):
            current = self.city_list.currentItem().text() if self.city_list.currentItem() else None
            self.city_list.clear()
            for name in pt.search_cities(text, limit=200):
                self.city_list.addItem(name)
            if current:
                items = self.city_list.findItems(current, QtCore.Qt.MatchExactly)
                if items:
                    self.city_list.setCurrentItem(items[0])

        def choose_sound(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose a sound", os.path.expanduser("~"), "Audio (*.ogg *.oga *.wav *.flac *.mp3)")
            if path:
                self.sound.setText(path)

        def save(self):
            s = dict(self.settings)
            item = self.city_list.currentItem()
            if item:
                s["city"] = item.text()
            if self.manual.isChecked():
                tzname = self.tzname.text().strip()
                tz = pt.get_tz(tzname, None)
                s["manual"] = {"name": "My location", "lat": self.lat.value(), "lon": self.lon.value(),
                               "tz": tzname,
                               "offset": pt.utc_offset_hours(tz, _dt.date.today())}
            else:
                s["manual"] = None
            s["method"] = self.method.currentData()
            s["asr"] = self.asr.currentData()
            s["hijri_adjust"] = self.hijri_adj.value()
            s["notify_at_prayer"] = self.at_prayer.isChecked()
            s["remind_before_min"] = self.before.value()
            s["daily_text"] = self.daily.isChecked()
            s["daily_time"] = self.daily_time.time().toString("HH:mm")
            s["language"] = self.language.currentData()
            s["sound"] = self.sound.text()
            notifier.save_settings(s)
            self.settings = notifier.load_settings()
            self.loaded_day = None
            self.refresh()
            self.nav.button(0).setChecked(True)
            self.stack.setCurrentIndex(0)

        def fetch_texts(self):
            if self.proc:
                return
            self.fetch_btn.setEnabled(False)
            self.fetch_status.setText("Downloading the verified texts (%s)…" % TEXT_SIZE_NOTE)
            self.proc = QtCore.QProcess(self)
            self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
            self.proc.readyReadStandardOutput.connect(self.fetch_progress)
            self.proc.finished.connect(self.fetch_done)
            cmd = _self_command() + ["fetch-content", "--system"]
            self.proc.start("pkexec", cmd)

        def fetch_progress(self):
            text = bytes(self.proc.readAllStandardOutput()).decode(errors="replace").strip()
            if text:
                self.fetch_status.setText(text.splitlines()[-1])

        def fetch_done(self, code, _status):
            self.proc = None
            if code in (126, 127):
                # Approval declined: keep a private copy in the home folder instead.
                self.fetch_status.setText("Saving the texts in your home folder instead…")
                self.proc = QtCore.QProcess(self)
                self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
                self.proc.readyReadStandardOutput.connect(self.fetch_progress)
                self.proc.finished.connect(lambda c, s: self.fetch_finished(c))
                self.proc.start(sys.executable, [os.path.abspath(__file__), "fetch-content", "--user"])
                return
            self.fetch_finished(code)

        def fetch_finished(self, code):
            self.proc = None
            self.fetch_btn.setEnabled(True)
            self.fetch_status.setText("Texts downloaded and verified." if code == 0 else
                                      "The download did not finish. Check the internet connection and try again.")
            self.loaded_day = None
            self.refresh()

        def toggle_service(self):
            on = service_enabled()
            if on:
                subprocess.call(["systemctl", "--user", "disable", "--now", SERVICE])
            else:
                if not os.path.exists(notifier.settings_path()):
                    notifier.save_settings(self.settings)
                subprocess.call(["systemctl", "--user", "enable", "--now", SERVICE])
                if not content.have_content():
                    self.nav.button(1).setChecked(True)
                    self.stack.setCurrentIndex(1)
                    self.fetch_texts()
            self.update_service_state()

        def update_service_state(self):
            on = service_enabled()
            self.reminder_state.setText(
                "Prayer reminders are on." if on else
                "Prayer reminders are off. Turn them on to get a notification at each prayer time.")
            self.toggle_btn.setText("Turn reminders off" if on else "Turn on reminders")

        # ----- refresh / tick
        def refresh(self):
            self.info = today_info(self.settings)
            info = self.info
            self.hijri_ar.setText("%s %s %s هـ" % (arabic_digits(info["hijri"]["day"]), info["hijri"]["month_arabic"],
                                                 arabic_digits(info["hijri"]["year"])))
            self.hijri.setText(info["hijri"]["text"])
            self.greg.setText(info["gregorian"])
            self.place.setText("%s · %.4f, %.4f · %s" % (info["location"]["name"], info["location"]["lat"],
                                                        info["location"]["lon"], info["location"]["tz"]))
            self.subtitle.setText("Prayer times, Qibla, and a daily Ayah and Hadith from verified sources")
            for name, (frame, _n, t) in self.tiles.items():
                t.setText(info["times"][name])
            q = info["qibla"]
            self.dial.set_bearing(q)
            self.qibla_text.setText("%.1f° %s" % (q, info["qibla_point"]))
            self.method_text.setText("%s · Asr: %s" % (info["method"], info["asr"]))
            self.update_service_state()
            day = _dt.date.fromisoformat(info["date"])
            if day != self.loaded_day:
                self.loaded_day = day
                lang = self.settings.get("language", "bn")
                missing = ("The Quran and Hadith texts are not on this PC yet. Open Settings and press "
                           "\"Download Quran & Hadith texts\" (%s)." % TEXT_SIZE_NOTE)
                for card, item in ((self.ayah_card, content.ayah_of_the_day(day)),
                                   (self.hadith_card, content.hadith_of_the_day(day))):
                    card.lang = lang
                    card.set_item(item, missing)
            self.tick()

        def tick(self):
            if not self.info:
                return
            now = _dt.datetime.now(_dt.timezone.utc)
            local = now.astimezone(self.info["_now"].tzinfo)
            if local.date().isoformat() != self.info["date"]:
                self.refresh()
                return
            nxt = pt.next_prayer(self.info["_times"], now)
            if nxt is None:
                tomorrow = pt.times_for_settings(local.date() + _dt.timedelta(days=1), self.settings)
                nxt = ("fajr", tomorrow["fajr"])
            name, at = nxt
            self.next_name.setText("Next: %s" % pt.PRAYER_LABELS[name])
            self.countdown.setText(format_countdown((at - now).total_seconds()))
            self.next_at.setText("at %s" % at.strftime("%H:%M"))
            for key, (frame, n, t) in self.tiles.items():
                is_next = key == name and at.date() == local.date()
                want = "tileNext" if is_next else "tile"
                if frame.objectName() != want:
                    frame.setObjectName(want)
                    frame.style().unpolish(frame)
                    frame.style().polish(frame)
                n.setStyleSheet("color: %s; font-weight: 600;" % ("#e0f2fe" if is_next else
                                                                    ("#64748b" if key == "sunrise" else "#94a3b8")))

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-islamic")
    app.setApplicationDisplayName("DevOS Islamic")
    app.setDesktopFileName("devos-islamic")
    window = IslamicWindow()
    window.show()
    if screenshot:
        def grab():
            window.grab().save(screenshot)
            window.stack.setCurrentIndex(1)
            QtCore.QTimer.singleShot(300, grab_settings)

        def grab_settings():
            root, ext = os.path.splitext(screenshot)
            window.grab().save(root + "-settings" + ext)
            app.quit()
        QtCore.QTimer.singleShot(800, grab)
    return app.exec_()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="devos-islamic", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd")
    gui = sub.add_parser("gui", help="open the window (default)")
    gui.add_argument("--screenshot", help=argparse.SUPPRESS)
    sub.add_parser("enable", help="download texts if needed and turn on prayer reminders")
    sub.add_parser("disable", help="turn off prayer reminders")
    times = sub.add_parser("times", help="print prayer times")
    times.add_argument("--date", help="YYYY-MM-DD (default: today)")
    sub.add_parser("today", help="today's information as JSON")
    fetch = sub.add_parser("fetch-content", help="download and verify the Quran and Hadith texts")
    where = fetch.add_mutually_exclusive_group()
    where.add_argument("--system", action="store_true", help="into %s (needs root)" % content.SYSTEM_DIR)
    where.add_argument("--user", action="store_true", help="into ~/.local/share/DevOS/islamic")
    args = parser.parse_args(argv)
    if args.cmd in (None, "gui"):
        return run_gui(getattr(args, "screenshot", None))
    return {"enable": cmd_enable, "disable": cmd_disable, "times": cmd_times,
            "today": cmd_today, "fetch-content": cmd_fetch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
