#!/usr/bin/env python3
"""
DevOS AI Models window: the same choice as the installer's "Choose your
DevOS AI" page, after install, plus the local AI API switch.

Changes go through "pkexec devos-ai-models ..." because the models live in
/var/lib/DevOS/models and the API settings in /etc/devos (shared by every
account on the PC).
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import model_catalog as catalog  # noqa: E402
import models_cli  # noqa: E402

from PyQt5 import QtCore, QtWidgets  # noqa: E402

CLI = "/usr/local/bin/devos-ai-models"

STYLE = """
QWidget { background: #0b0f1a; color: #e2e8f0; font-size: 14px; }
QLabel#title { font-size: 24px; font-weight: 600; color: #f8fafc; }
QLabel#muted { color: #94a3b8; }
QFrame#card { background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; }
QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 7px 14px; }
QPushButton#primary { background: #0284c7; border-color: #38bdf8; color: white; }
QPushButton:disabled { color: #64748b; }
QProgressBar { background: #0f172a; border: 1px solid #1e293b; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #38bdf8; border-radius: 6px; }
QLineEdit { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 6px; }
"""


class ModelsWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DevOS AI Models")
        self.resize(720, 760)
        self.setStyleSheet(STYLE)
        self.info = models_cli.hardware()
        self.choice = catalog.read_choice()
        self.proc = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QtWidgets.QLabel("DevOS AI Models")
        title.setObjectName("title")
        layout.addWidget(title)
        facts = QtWidgets.QLabel(
            f"This PC: {self.info['ram_gb']} GB RAM · {self.info['threads']} threads · "
            f"{self.info['disk_gb']} GB free. {catalog.BUILT_IN_SKILLS}")
        facts.setObjectName("muted")
        facts.setWordWrap(True)
        layout.addWidget(facts)

        self.group = QtWidgets.QButtonGroup(self)
        for model in self.info["models"]:
            have = model.get("built_in") or catalog.installed_file(model["file"])
            text = f"{model['name']} · {model['params']} — {model['about']}"
            if model["id"] == self.info["recommended"]:
                text += "  (recommended)"
            size = "Included" if model.get("built_in") else f"{model['size_mb'] / 1024:.1f} GB"
            radio = QtWidgets.QRadioButton(f"{text}\n{size}{' · downloaded' if have else ''}"
                                           f"{'' if model['fits'] else ' · needs ' + str(model['min_ram_gb']) + ' GB RAM'}")
            radio.setEnabled(model["fits"])
            radio.setChecked(model["id"] == self.choice["chat"])
            radio.setProperty("model_id", model["id"])
            self.group.addButton(radio)
            layout.addWidget(radio)

        self.extras = {}
        for extra in self.info["extras"]:
            box = QtWidgets.QCheckBox(f"{extra['name']} — {extra['about']}")
            box.setEnabled(extra["fits"])
            box.setChecked(bool(self.choice.get(extra["id"])))
            self.extras[extra["id"]] = box
            layout.addWidget(box)

        row = QtWidgets.QHBoxLayout()
        self.apply = QtWidgets.QPushButton("Use and download")
        self.apply.setObjectName("primary")
        self.apply.clicked.connect(self.use_choice)
        row.addWidget(self.apply)
        row.addStretch(1)
        layout.addLayout(row)
        self.bar = QtWidgets.QProgressBar()
        self.bar.hide()
        layout.addWidget(self.bar)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # --- local AI API
        api_title = QtWidgets.QLabel("Local AI API")
        api_title.setStyleSheet("font-size: 18px; font-weight: 600; color: #f8fafc;")
        layout.addWidget(api_title)
        api_help = QtWidgets.QLabel(
            "Apps on this PC can always use DevOS AI at http://127.0.0.1:11434/v1 (OpenAI-compatible, "
            "models devos-ai, devos-ai-code, devos-ai-embed). The reference is at "
            "http://127.0.0.1:11434/docs. Turn on network access to use it from your "
            "phone or other PCs on the same Wi-Fi; they need the API key.")
        api_help.setObjectName("muted")
        api_help.setWordWrap(True)
        layout.addWidget(api_help)
        self.endpoint = QtWidgets.QLineEdit("http://127.0.0.1:11434/v1")
        self.endpoint.setReadOnly(True)
        layout.addWidget(self.endpoint)
        api_row = QtWidgets.QHBoxLayout()
        self.lan_on = QtWidgets.QPushButton("Share on my network")
        self.lan_on.clicked.connect(lambda: self.api(["lan", "on"]))
        self.lan_off = QtWidgets.QPushButton("This PC only")
        self.lan_off.clicked.connect(lambda: self.api(["lan", "off"]))
        show = QtWidgets.QPushButton("Show address and key")
        show.clicked.connect(lambda: self.api([]))
        api_row.addWidget(self.lan_on)
        api_row.addWidget(self.lan_off)
        api_row.addWidget(show)
        api_row.addStretch(1)
        layout.addLayout(api_row)
        self.api_text = QtWidgets.QPlainTextEdit()
        self.api_text.setReadOnly(True)
        self.api_text.setMaximumHeight(150)
        layout.addWidget(self.api_text)
        layout.addStretch(1)

    def selected(self) -> dict:
        button = self.group.checkedButton()
        return {
            "chat": button.property("model_id") if button else "tiny",
            "vision": self.extras.get("vision") and self.extras["vision"].isChecked(),
            "coder": self.extras.get("coder") and self.extras["coder"].isChecked(),
        }

    def use_choice(self):
        choice = self.selected()
        value = choice["chat"] + ("+vision" if choice["vision"] else "") + ("+coder" if choice["coder"] else "")
        self.apply.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText("Downloading… you can keep using the PC. DevOS AI switches when it is done.")
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self.progress)
        self.proc.finished.connect(lambda code, _status: self.done(code, choice))
        self.proc.start("pkexec", [CLI, "choose", "--value", value])

    def progress(self):
        text = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        for line in text.splitlines():
            if line.startswith("[Downloading]"):
                try:
                    done, total = line.split("]", 1)[1].replace("MB", "").split("/")
                    self.bar.setRange(0, 1000)
                    self.bar.setValue(int(float(done) / max(float(total), 1) * 1000))
                    self.bar.setFormat(f"{float(done):.0f} / {float(total):.0f} MB")
                except ValueError:
                    pass
            elif line.strip():
                self.status.setText(line.strip())

    def done(self, code, choice):
        self.apply.setEnabled(True)
        self.bar.hide()
        if code == 0:
            self.status.setText("DevOS AI is ready with the new model.")
            if choice.get("vision"):
                subprocess.Popen([CLI, "user-extras"], start_new_session=True)
        elif code in (126, 127):
            self.status.setText("Nothing changed (administrator approval was cancelled).")
        else:
            self.status.setText("The download stopped. It continues automatically when the PC is online, "
                                "or press the button again.")

    def api(self, action):
        out = subprocess.run(["pkexec", CLI, "api"] + action, capture_output=True, text=True)
        text = (out.stdout or out.stderr).strip()
        self.api_text.setPlainText(text or "Nothing changed.")
        for line in text.splitlines():
            if "On your network:" in line:
                self.endpoint.setText(line.split(":", 1)[1].strip())
                break
        else:
            self.endpoint.setText("http://127.0.0.1:11434/v1")


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DevOS AI Models")
    window = ModelsWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
