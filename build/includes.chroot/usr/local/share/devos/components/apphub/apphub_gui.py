#!/usr/bin/env python3
"""Friendly DevOS App Hub window — install Windows, Android, or Linux packages."""

import os
import shutil
import subprocess
import sys

from PyQt5 import QtCore, QtGui, QtWidgets

OPEN_APP = "/usr/local/bin/devos-open-app"
FEATURES = "/usr/local/bin/devos-features"

STYLE = """
QWidget { background: #f4f6fb; color: #0f172a; font-size: 14px; }
QLabel#title { font-size: 28px; font-weight: 700; color: #0b1220; }
QLabel#sub { color: #64748b; font-size: 15px; }
QFrame#card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
}
QPushButton#action {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 12px;
  padding: 14px 18px;
  font-size: 15px;
  font-weight: 600;
  text-align: left;
}
QPushButton#action:hover { background: #1e293b; }
QPushButton#ghost {
  background: transparent;
  color: #0369a1;
  border: none;
  padding: 8px;
  font-weight: 600;
}
QLabel#hint { color: #94a3b8; font-size: 12px; }
"""


class HubWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DevOS App Hub")
        self.setWindowIcon(QtGui.QIcon.fromTheme("devos-apphub"))
        self.resize(560, 520)
        try:
            from devos_appearance import adapt_stylesheet, current_mode
            self.setStyleSheet(adapt_stylesheet(STYLE, current_mode()))
        except Exception:
            self.setStyleSheet(STYLE)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(16)

        title = QtWidgets.QLabel("App Hub")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QtWidgets.QLabel(
            "Install a downloaded Windows, Android, or Linux app in a few clicks. "
            "DevOS checks the file and opens it safely."
        )
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        card = QtWidgets.QFrame()
        card.setObjectName("card")
        card_l = QtWidgets.QVBoxLayout(card)
        card_l.setContentsMargins(16, 16, 16, 16)
        card_l.setSpacing(10)

        for label, filt, tip in (
            ("Windows app (.exe / .msi)",
             "Windows (*.exe *.msi *.bat *.cmd);;All files (*)",
             "Runs with Windows support on DevOS"),
            ("Android app (.apk)",
             "Android (*.apk *.xapk);;All files (*)",
             "Installs into the Android environment"),
            ("Linux package (.deb / AppImage)",
             "Linux (*.deb *.AppImage *.appimage);;All files (*)",
             "Installs a native DevOS / Linux package"),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("action")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, f=filt: self._pick(f))
            card_l.addWidget(btn)
            hint = QtWidgets.QLabel(tip)
            hint.setObjectName("hint")
            card_l.addWidget(hint)

        root.addWidget(card)

        more = QtWidgets.QPushButton("Browse more apps in DevOS Features…")
        more.setObjectName("ghost")
        more.setCursor(QtCore.Qt.PointingHandCursor)
        more.clicked.connect(self._features)
        root.addWidget(more)
        root.addStretch(1)

    def _pick(self, file_filter: str) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose an app to install", os.path.expanduser("~"), file_filter
        )
        if not path:
            return
        if not os.path.isfile(OPEN_APP):
            QtWidgets.QMessageBox.critical(
                self, "App Hub", "The installer helper is missing on this PC."
            )
            return
        subprocess.Popen([OPEN_APP, path], start_new_session=True)
        self.close()

    def _features(self) -> None:
        if os.path.isfile(FEATURES):
            subprocess.Popen([FEATURES], start_new_session=True)
        else:
            QtWidgets.QMessageBox.information(
                self, "App Hub", "Open DevOS Features from the app menu to add more apps."
            )


def main() -> int:
    if not shutil.which("python3") and not sys.executable:
        print("Python is required for App Hub.", file=sys.stderr)
        return 1
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DevOS App Hub")
    win = HubWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
