#!/usr/bin/env python3
"""DevOS PC owner profile — name, email, bio, portfolio for Settings + DevOS AI.

Stored at ~/.config/devos/owner.json so the on-device assistant can answer
“who owns this PC?” without inventing details. Separate from DevOS creator info.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pwd
import re
import socket
import sys
from typing import Any, Dict, List, Optional

APP_ID = "devos-profile"
APP_TITLE = "My Profile"
CONFIG_DIR = os.path.expanduser("~/.config/devos")
CONFIG_FILE = os.path.join(CONFIG_DIR, "owner.json")

FIELDS = (
    "display_name",
    "email",
    "bio",
    "portfolio",
    "phone",
    "organization",
    "linkedin",
    "github",
    "website",
)

LABELS = {
    "display_name": "Full name",
    "email": "Email",
    "bio": "Bio",
    "portfolio": "Portfolio website",
    "phone": "Phone",
    "organization": "Organization",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "website": "Website",
}

DEFAULTS: Dict[str, str] = {key: "" for key in FIELDS}


def _gecos_name() -> str:
    try:
        gecos = pwd.getpwuid(os.getuid()).pw_gecos or ""
    except KeyError:
        return ""
    return (gecos.split(",")[0] or "").strip()


def _accounts_email() -> str:
    """Best-effort email from AccountsService (same source as Users settings)."""
    try:
        import dbus  # type: ignore
    except ImportError:
        return ""
    try:
        bus = dbus.SystemBus()
        manager = bus.get_object("org.freedesktop.Accounts", "/org/freedesktop/Accounts")
        iface = dbus.Interface(manager, "org.freedesktop.Accounts")
        path = iface.FindUserByName(getpass.getuser())
        user = bus.get_object("org.freedesktop.Accounts", path)
        props = dbus.Interface(user, "org.freedesktop.DBus.Properties")
        email = str(props.Get("org.freedesktop.Accounts.User", "Email") or "").strip()
        return email
    except Exception:
        return ""


def seed_from_system(profile: Dict[str, str]) -> Dict[str, str]:
    out = dict(DEFAULTS)
    out.update({k: str(profile.get(k) or "") for k in FIELDS})
    if not out["display_name"]:
        out["display_name"] = _gecos_name()
    if not out["email"]:
        out["email"] = _accounts_email()
    return out


def load_profile(path: str = CONFIG_FILE) -> Dict[str, str]:
    data: Dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError, TypeError):
            data = {}
    return seed_from_system(data)


def save_profile(profile: Dict[str, Any], path: str = CONFIG_FILE) -> Dict[str, str]:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    clean = dict(DEFAULTS)
    for key in FIELDS:
        clean[key] = str(profile.get(key) or "").strip()
    # Normalize URLs a little so AI answers stay clickable.
    for key in ("portfolio", "website", "linkedin", "github"):
        val = clean[key]
        if val and not re.match(r"^[a-z][a-z0-9+.-]*:", val, re.I):
            clean[key] = "https://" + val.lstrip("/")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return clean


def username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "user"


def hostname() -> str:
    try:
        return socket.gethostname() or "DevOS-PC"
    except OSError:
        return "DevOS-PC"


def has_owner_details(profile: Optional[Dict[str, str]] = None) -> bool:
    p = profile if profile is not None else load_profile()
    return any(str(p.get(k) or "").strip() for k in ("display_name", "email", "bio", "portfolio", "website"))


def owner_facts_line(profile: Optional[Dict[str, str]] = None) -> str:
    """One compact line for AI system prompts."""
    p = profile if profile is not None else load_profile()
    bits: List[str] = []
    if p.get("display_name"):
        bits.append(f"name {p['display_name']}")
    bits.append(f"username {username()}")
    if p.get("email"):
        bits.append(f"email {p['email']}")
    if p.get("portfolio"):
        bits.append(f"portfolio {p['portfolio']}")
    elif p.get("website"):
        bits.append(f"website {p['website']}")
    if p.get("organization"):
        bits.append(f"organization {p['organization']}")
    if p.get("phone"):
        bits.append(f"phone {p['phone']}")
    if p.get("linkedin"):
        bits.append(f"LinkedIn {p['linkedin']}")
    if p.get("github"):
        bits.append(f"GitHub {p['github']}")
    if p.get("bio"):
        bio = re.sub(r"\s+", " ", p["bio"]).strip()
        if len(bio) > 220:
            bio = bio[:217].rstrip() + "…"
        bits.append(f"bio {bio}")
    if not has_owner_details(p):
        return (
            f"PC owner profile is empty (signed-in username {username()} on {hostname()}). "
            "If asked who owns this PC, say the owner has not filled My Profile yet "
            "and suggest Start menu → My Profile."
        )
    return "PC owner (this computer's user): " + "; ".join(bits)


def owner_answer_text(profile: Optional[Dict[str, str]] = None) -> str:
    """User-facing answer for “who owns this PC?”."""
    p = profile if profile is not None else load_profile()
    if not has_owner_details(p):
        return (
            f"This PC is signed in as **{username()}** on **{hostname()}**, "
            "but the owner profile is still empty.\n\n"
            "Open **Start → My Profile** to add name, email, bio, and portfolio — "
            "then I can introduce the owner next time."
        )
    lines = [
        f"This PC belongs to **{p.get('display_name') or username()}** "
        f"(account `{username()}` on {hostname()}).",
        "",
    ]
    if p.get("email"):
        lines.append(f"- Email: {p['email']}")
    if p.get("portfolio"):
        lines.append(f"- Portfolio: {p['portfolio']}")
    if p.get("website") and p.get("website") != p.get("portfolio"):
        lines.append(f"- Website: {p['website']}")
    if p.get("organization"):
        lines.append(f"- Organization: {p['organization']}")
    if p.get("phone"):
        lines.append(f"- Phone: {p['phone']}")
    if p.get("linkedin"):
        lines.append(f"- LinkedIn: {p['linkedin']}")
    if p.get("github"):
        lines.append(f"- GitHub: {p['github']}")
    if p.get("bio"):
        lines.extend(["", p["bio"].strip()])
    lines.extend(
        [
            "",
            "_Not the same as who made DevOS — that is the DevOS team / Imran Dev. "
            "This is the person who owns and uses this computer._",
        ]
    )
    return "\n".join(lines)


def sync_accounts_email(email: str) -> None:
    """Write email into AccountsService when possible (shows on Users page)."""
    email = (email or "").strip()
    if not email:
        return
    try:
        import dbus  # type: ignore
    except ImportError:
        return
    try:
        bus = dbus.SystemBus()
        manager = bus.get_object("org.freedesktop.Accounts", "/org/freedesktop/Accounts")
        iface = dbus.Interface(manager, "org.freedesktop.Accounts")
        path = iface.FindUserByName(getpass.getuser())
        user = bus.get_object("org.freedesktop.Accounts", path)
        uiface = dbus.Interface(user, "org.freedesktop.Accounts.User")
        uiface.SetEmail(email)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

STYLE = """
QMainWindow, QWidget#root {
  background: #0b1220; color: #f8fafc;
  font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px;
}
QLabel#title { font-size: 26px; font-weight: 800; color: #f8fafc; }
QLabel#sub { color: #94a3b8; font-size: 13px; }
QLabel#hint { color: #64748b; font-size: 12px; }
QLabel#fieldLabel { color: #94a3b8; font-weight: 600; }
QLineEdit, QTextEdit {
  background: #111827; color: #f8fafc; border: 1px solid #1f2937;
  border-radius: 10px; padding: 10px 12px; selection-background-color: #0ea5e9;
}
QLineEdit:focus, QTextEdit:focus { border-color: #38bdf8; }
QLineEdit:disabled { color: #64748b; background: #0f172a; }
QPushButton#primary {
  background: #0ea5e9; color: #0b1220; border: none; border-radius: 10px;
  padding: 10px 18px; font-weight: 700;
}
QPushButton#primary:hover { background: #38bdf8; }
QPushButton#ghost {
  background: transparent; color: #94a3b8; border: 1px solid #1f2937;
  border-radius: 10px; padding: 10px 16px; font-weight: 600;
}
QPushButton#ghost:hover { color: #f8fafc; border-color: #38bdf8; }
QFrame#card {
  background: #111827; border: 1px solid #1f2937; border-radius: 16px;
}
QLabel#statusOk { color: #34d399; }
QLabel#statusErr { color: #f87171; }
"""


def run_gui(argv: Optional[List[str]] = None) -> int:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QApplication,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app_identity import apply as apply_identity, prepare as prepare_identity, show_window
    from devos_appearance import adapt_stylesheet, current_mode, install as install_appearance

    prepare_identity(APP_ID)
    app = QApplication(list(sys.argv if argv is None else argv))
    apply_identity(app, APP_ID)
    install_appearance(app)

    profile = load_profile()
    win = QMainWindow()
    win.setWindowTitle(APP_TITLE)
    win.resize(720, 780)
    win.setMinimumSize(560, 560)

    root = QWidget()
    root.setObjectName("root")
    win.setCentralWidget(root)
    outer = QVBoxLayout(root)
    outer.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    host = QWidget()
    host.setObjectName("root")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(14)

    title = QLabel("My Profile")
    title.setObjectName("title")
    lay.addWidget(title)
    sub = QLabel(
        "Basic info for this PC’s owner. DevOS AI uses it when someone asks "
        "who owns this computer — name, email, bio, and portfolio."
    )
    sub.setObjectName("sub")
    sub.setWordWrap(True)
    lay.addWidget(sub)

    card = QFrame()
    card.setObjectName("card")
    form_wrap = QVBoxLayout(card)
    form_wrap.setContentsMargins(20, 18, 20, 18)
    form = QFormLayout()
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(12)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def labeled(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("fieldLabel")
        return lab

    edits: Dict[str, Any] = {}

    user_edit = QLineEdit(username())
    user_edit.setReadOnly(True)
    user_edit.setEnabled(False)
    form.addRow(labeled("Username"), user_edit)

    host_edit = QLineEdit(hostname())
    host_edit.setReadOnly(True)
    host_edit.setEnabled(False)
    form.addRow(labeled("This PC"), host_edit)

    for key in FIELDS:
        if key == "bio":
            widget = QTextEdit()
            widget.setPlainText(profile.get(key) or "")
            widget.setFixedHeight(110)
            widget.setPlaceholderText("Short intro — what you do, where you’re based…")
        else:
            widget = QLineEdit(profile.get(key) or "")
            placeholders = {
                "display_name": "Your full name",
                "email": "you@example.com",
                "portfolio": "https://yoursite.com",
                "phone": "+880…",
                "organization": "Company or school",
                "linkedin": "https://linkedin.com/in/…",
                "github": "https://github.com/…",
                "website": "https://…",
            }
            widget.setPlaceholderText(placeholders.get(key, ""))
        edits[key] = widget
        form.addRow(labeled(LABELS[key]), widget)

    form_wrap.addLayout(form)
    lay.addWidget(card)

    hint = QLabel(
        "Tip: Portfolio and email are what DevOS AI shares first. "
        "Leave a field blank if you don’t want it spoken aloud."
    )
    hint.setObjectName("hint")
    hint.setWordWrap(True)
    lay.addWidget(hint)

    status = QLabel("")
    status.setObjectName("statusOk")
    lay.addWidget(status)

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    open_users = QPushButton("Users & password…")
    open_users.setObjectName("ghost")
    save_btn = QPushButton("Save profile")
    save_btn.setObjectName("primary")
    buttons.addWidget(open_users)
    buttons.addWidget(save_btn)
    lay.addLayout(buttons)
    lay.addStretch(1)

    scroll.setWidget(host)
    outer.addWidget(scroll)

    def collect() -> Dict[str, str]:
        out = dict(DEFAULTS)
        for key, widget in edits.items():
            if isinstance(widget, QTextEdit):
                out[key] = widget.toPlainText().strip()
            else:
                out[key] = widget.text().strip()
        return out

    def on_save():
        data = collect()
        if data.get("email") and "@" not in data["email"]:
            status.setObjectName("statusErr")
            status.setStyleSheet("color: #f87171;")
            status.setText("Email looks incomplete — include an @ sign.")
            return
        saved = save_profile(data)
        sync_accounts_email(saved.get("email") or "")
        status.setObjectName("statusOk")
        status.setStyleSheet("color: #34d399;")
        status.setText("Saved. DevOS AI can use this when asked who owns this PC.")

    def on_users():
        for cmd in (
            ["kcmshell6", "kcm_users"],
            ["kcmshell5", "kcm_users"],
            ["systemsettings", "kcm_users"],
            ["systemsettings5", "kcm_users"],
        ):
            try:
                import subprocess

                subprocess.Popen(cmd)
                return
            except OSError:
                continue
        QMessageBox.information(win, APP_TITLE, "Open Settings → Users to change password or account type.")

    save_btn.clicked.connect(on_save)
    open_users.clicked.connect(on_users)

    try:
        mode = current_mode()
    except Exception:
        mode = "dark"
    win.setStyleSheet(adapt_stylesheet(STYLE, mode))
    show_window(win, APP_ID)
    return app.exec_()


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="DevOS PC owner profile")
    parser.add_argument("--json", action="store_true", help="print profile as JSON")
    parser.add_argument("--facts", action="store_true", help="print AI facts line")
    parser.add_argument("--answer", action="store_true", help="print owner answer text")
    parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), action="append", default=[],
                        help="set a field (repeatable) then save")
    args = parser.parse_args(argv)

    if args.set:
        profile = load_profile()
        for key, value in args.set:
            if key not in FIELDS:
                print(f"Unknown field: {key}", file=sys.stderr)
                return 2
            profile[key] = value
        save_profile(profile)
        sync_accounts_email(profile.get("email") or "")

    if args.json:
        print(json.dumps(load_profile(), indent=2, ensure_ascii=False))
        return 0
    if args.facts:
        print(owner_facts_line())
        return 0
    if args.answer:
        print(owner_answer_text())
        return 0
    if args.set:
        return 0
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
