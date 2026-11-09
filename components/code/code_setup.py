#!/usr/bin/env python3
"""Premium setup window when VS Code is not installed yet.

DevOS Code must never open Kate. Offer a one-click install of the modern editor.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from PyQt5 import QtCore, QtGui, QtWidgets


STYLE = """
QWidget#root {
    background: #f8fafc;
    color: #0f172a;
}
QLabel#brand {
    font-size: 28px;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: -0.4px;
}
QLabel#title {
    font-size: 18px;
    font-weight: 600;
    color: #0f172a;
}
QLabel#body {
    font-size: 13px;
    color: #334155;
}
QPushButton#primary {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
    min-height: 40px;
}
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #93c5fd; }
QPushButton#ghost {
    background: transparent;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 18px;
    min-height: 40px;
}
QProgressBar {
    border: none;
    background: #e2e8f0;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 4px;
}
"""


class InstallWorker(QtCore.QThread):
    failed = QtCore.pyqtSignal(str)
    finished_ok = QtCore.pyqtSignal()

    def run(self):
        installer = "/usr/local/sbin/devos-install-code"
        if not os.path.isfile(installer):
            self.failed.emit("Installer is missing on this system.")
            return
        try:
            proc = subprocess.run(
                ["pkexec", installer],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            self.failed.emit("Install timed out. Check your network and try again.")
            return
        except OSError as exc:
            self.failed.emit(str(exc))
            return
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "Install failed.").strip()
            self.failed.emit(err[-400:] or "Install failed.")
            return
        self.finished_ok.emit()


class SetupWindow(QtWidgets.QWidget):
    def __init__(self, argv):
        super().__init__()
        self.argv = list(argv)
        self.setObjectName("root")
        self.setWindowTitle("DevOS Code")
        self.setWindowIcon(QtGui.QIcon.fromTheme("devos-code"))
        self.resize(520, 360)
        self.setStyleSheet(STYLE)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(12)

        brand = QtWidgets.QLabel("DevOS Code")
        brand.setObjectName("brand")
        layout.addWidget(brand)

        title = QtWidgets.QLabel("Install the modern code editor")
        title.setObjectName("title")
        layout.addWidget(title)

        body = QtWidgets.QLabel(
            "DevOS Code uses Visual Studio Code — a current, premium editor with "
            "extensions, Git, terminal, and DevOS AI. The old Kate editor is not used."
        )
        body.setObjectName("body")
        body.setWordWrap(True)
        layout.addWidget(body)

        self.status = QtWidgets.QLabel("About 100 MB download. Needs internet once.")
        self.status.setObjectName("body")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.hide()
        layout.addWidget(self.bar)

        layout.addStretch(1)

        row = QtWidgets.QHBoxLayout()
        self.cancel = QtWidgets.QPushButton("Not now")
        self.cancel.setObjectName("ghost")
        self.cancel.clicked.connect(self.close)
        row.addWidget(self.cancel)
        row.addStretch(1)
        self.install = QtWidgets.QPushButton("Install DevOS Code")
        self.install.setObjectName("primary")
        self.install.clicked.connect(self.start_install)
        row.addWidget(self.install)
        layout.addLayout(row)

        self.worker = None

    def start_install(self):
        self.install.setEnabled(False)
        self.cancel.setEnabled(False)
        self.bar.show()
        self.status.setText("Downloading and installing Visual Studio Code…")
        self.worker = InstallWorker()
        self.worker.failed.connect(self.on_fail)
        self.worker.finished_ok.connect(self.on_ok)
        self.worker.start()

    def on_fail(self, message: str):
        self.bar.hide()
        self.install.setEnabled(True)
        self.cancel.setEnabled(True)
        self.status.setText(message)

    def on_ok(self):
        self.bar.hide()
        self.status.setText("Installed. Opening DevOS Code…")
        QtCore.QTimer.singleShot(400, self.open_editor)

    def open_editor(self):
        for candidate in ("code", "codium", "code-oss"):
            path = shutil.which(candidate)
            if path:
                subprocess.Popen([path, *self.argv], start_new_session=True)
                self.close()
                return
        self.status.setText("Install finished but the editor binary was not found. Reboot and try again.")
        self.install.setEnabled(True)
        self.cancel.setEnabled(True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app_identity import prepare, apply as apply_identity, show_window
    prepare("devos-code")
    app = QtWidgets.QApplication([sys.argv[0], *argv])
    apply_identity(app, "devos-code")
    app.setApplicationDisplayName("DevOS Code")
    win = SetupWindow(argv)
    show_window(win, "devos-code")
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
