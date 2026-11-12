"""Profile editor for the Agents button in DevOS AI Chat."""

from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from agents import Profile, approved_folder


class AgentDialog(QtWidgets.QDialog):
    def __init__(self, store, profiles, apps, active, parent):
        super().__init__(parent)
        self.setWindowTitle("DevOS AI Agents")
        area = parent.screen().availableGeometry()
        self.resize(min(510, area.width() - 40), min(510, area.height() - 60))
        self.store = store
        self.profiles = dict(profiles)
        self.apps = apps
        self.active = active
        self.selected = QtWidgets.QComboBox()
        self.name = QtWidgets.QLineEdit()
        self.name.setMaxLength(48)
        self.instructions = QtWidgets.QPlainTextEdit()
        self.instructions.setPlaceholderText("Example: Summarize my study notes and cite the filenames.")
        self.folder = QtWidgets.QLineEdit()
        self.folder.setReadOnly(True)
        self.folder.setPlaceholderText("No folder access")
        self.diagnostics = QtWidgets.QCheckBox("Read PC status and scan for cleanup opportunities")
        self.app_list = QtWidgets.QListWidget()
        self.app_list.setMinimumHeight(90)
        self.app_list.setToolTip("Check the apps this agent may ask you to open.")
        for app_id, app in sorted(apps.items(), key=lambda item: item[1].name.casefold()):
            row = QtWidgets.QListWidgetItem(app.name, self.app_list)
            row.setData(QtCore.Qt.UserRole, app_id)
            row.setCheckState(QtCore.Qt.Unchecked)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(QtCore.Qt.PlainText)

        outer = QtWidgets.QVBoxLayout(self)
        outer.addWidget(self.selected)
        scroll = QtWidgets.QScrollArea()
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(body)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        form.addRow("Name", self.name)
        form.addRow("Instructions", self.instructions)
        form.addRow("Read-only folder", self.folder)
        folder_buttons = QtWidgets.QHBoxLayout()
        browse = QtWidgets.QPushButton("Choose folder")
        browse.clicked.connect(self.choose_folder)
        clear = QtWidgets.QPushButton("Clear")
        clear.clicked.connect(self.folder.clear)
        folder_buttons.addWidget(browse)
        folder_buttons.addWidget(clear)
        form.addRow(folder_buttons)
        form.addRow(self.diagnostics)
        form.addRow("Allowed app launches", self.app_list)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.error)

        buttons = QtWidgets.QGridLayout()
        self.delete_button = QtWidgets.QPushButton("Delete agent")
        self.delete_button.clicked.connect(self.delete_profile)
        use_chat = QtWidgets.QPushButton("Use regular chat")
        use_chat.clicked.connect(self.use_chat)
        save = QtWidgets.QPushButton("Save and use")
        save.clicked.connect(self.save_profile)
        close = QtWidgets.QPushButton("Cancel")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.delete_button, 0, 0)
        buttons.addWidget(use_chat, 0, 1)
        buttons.addWidget(close, 1, 0)
        buttons.addWidget(save, 1, 1)
        outer.addLayout(buttons)
        self.selected.currentIndexChanged.connect(self.load_profile)
        self.refresh(active.name if active else None)

    def refresh(self, name=None):
        self.selected.blockSignals(True)
        self.selected.clear()
        self.selected.addItem("Create an agent", None)
        for key in sorted(self.profiles, key=str.casefold):
            self.selected.addItem(key, key)
        self.selected.setCurrentIndex(max(0, self.selected.findData(name)))
        self.selected.blockSignals(False)
        self.load_profile()

    def load_profile(self):
        key = self.selected.currentData()
        profile = self.profiles.get(key, Profile("", ""))
        self.name.setText(profile.name)
        self.instructions.setPlainText(profile.instructions)
        self.folder.setText(profile.folder)
        self.diagnostics.setChecked(profile.diagnostics)
        for index in range(self.app_list.count()):
            row = self.app_list.item(index)
            row.setCheckState(QtCore.Qt.Checked if row.data(QtCore.Qt.UserRole) in profile.apps
                              else QtCore.Qt.Unchecked)
        self.delete_button.setEnabled(key is not None)
        self.error.clear()

    def choose_folder(self):
        value = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Approve a folder for this agent", self.folder.text() or str(Path.home()))
        if value:
            try:
                path = approved_folder(str(Path(value).resolve(strict=True)))
                self.folder.setText(str(path))
                self.error.clear()
            except (OSError, ValueError) as exc:
                self.error.setText(str(exc))

    def persist(self, profiles):
        try:
            self.store.save(profiles)
        except OSError as exc:
            self.error.setText(f"Could not save agents. {exc}")
            return False
        self.profiles = profiles
        return True

    def save_profile(self):
        name = " ".join(self.name.text().split())
        instructions = self.instructions.toPlainText().strip()
        previous = self.selected.currentData()
        if not name or not instructions or len(instructions) > 1800:
            self.error.setText("Enter a name and instructions up to 1,800 characters.")
            return
        if any(key != previous and key.casefold() == name.casefold() for key in self.profiles):
            self.error.setText("An agent already uses that name.")
            return
        try:
            folder = str(approved_folder(self.folder.text())) if self.folder.text() else ""
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        apps = tuple(self.app_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.app_list.count())
                     if self.app_list.item(i).checkState() == QtCore.Qt.Checked)
        profile = Profile(name, instructions, folder, apps, self.diagnostics.isChecked())
        profiles = dict(self.profiles)
        profiles.pop(previous, None)
        profiles[name] = profile
        if self.persist(profiles):
            self.active = profile
            self.accept()

    def delete_profile(self):
        key = self.selected.currentData()
        if key not in self.profiles:
            return
        if QtWidgets.QMessageBox.question(self, "Delete agent", "Delete this saved agent profile?",
                                          QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                          QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        profiles = dict(self.profiles)
        del profiles[key]
        if self.persist(profiles):
            if self.active and self.active.name == key:
                self.active = None
            self.refresh()

    def use_chat(self):
        self.active = None
        self.accept()
