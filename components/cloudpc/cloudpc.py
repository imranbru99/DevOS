#!/usr/bin/env python3
"""DevOS Windows App companion: vendor PWA launcher and honest local reminders."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from session import Reminder, clock
from launchers import integrate, restore_companion

URL = 'https://windows.cloud.microsoft/'


def save_settings(path, limit, lead):
    Reminder(limit, lead)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.cloudpc-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump({'limit': limit, 'lead': lead}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_settings(path):
    try:
        data = json.loads(Path(path).read_text())
        reminder = Reminder(int(data['limit']), int(data['lead']))
        if reminder.limit < 120 or reminder.limit % 60 or reminder.lead % 60:
            return 600, 120
        return reminder.limit, reminder.lead
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return 600, 120


def open_windows_app():
    launcher = shutil.which('devos-pwa')
    args = [launcher, URL, 'Windows App', ''] if launcher else ['xdg-open', URL]
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


STYLE = '''
QWidget { background:#0b1220; color:#eaf2ff; font-family:Inter,"Noto Sans"; font-size:11pt; }
QLabel { background:transparent; }
QLabel#eyebrow { color:#57ccff; font-size:9pt; font-weight:600; }
QLabel#heading { font-size:25pt; font-weight:700; }
QLabel#muted { color:#9fb0c7; }
QLabel#clock { font-size:45pt; font-weight:600; color:#77d9ff; }
QFrame#card { background:#111f33; border:1px solid #29415d; border-radius:18px; }
QPushButton { background:#192c43; border:1px solid #35516e; border-radius:10px; padding:11px 18px; font-weight:600; }
QPushButton:hover { background:#21405c; border-color:#58cbff; }
QPushButton:focus { border:2px solid #58cbff; }
QPushButton#primary { background:#30baf0; color:#071725; border-color:#65d8ff; }
QSpinBox { padding:7px; border:1px solid #35516e; border-radius:8px; background:#14243a; }
QCheckBox { spacing:8px; }
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open', action='store_true', help='also open the official Windows App')
    args = parser.parse_args(argv)
    from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from devos_dialogs import install
    from app_identity import prepare
    prepare("devos-web-winapp")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName('devos-windows-app')
    app.setApplicationDisplayName('Windows App • DevOS')
    app.setDesktopFileName('devos-web-winapp')
    from app_identity import apply as apply_identity
    apply_identity(app, 'devos-web-winapp')
    install(app)
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QtGui.QIcon.fromTheme('devos-web-winapp', app.windowIcon()))
    server_name = 'devos-cloudpc-' + str(os.getuid())
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(300):
        socket.write(b'open' if args.open else b'show')
        socket.flush()
        socket.waitForBytesWritten(300)
        return 0
    QtNetwork.QLocalServer.removeServer(server_name)
    server = QtNetwork.QLocalServer(app)
    server.setSocketOptions(QtNetwork.QLocalServer.UserAccessOption)
    if not server.listen(server_name):
        raise RuntimeError('Cannot start the Windows App companion.')

    class Window(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.settings_path = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'devos/cloudpc.json'
            limit, lead = load_settings(self.settings_path)
            self.reminder = Reminder(limit, lead)
            self.notification = None
            self.setWindowTitle('Windows App — DevOS')
            self.setMinimumWidth(560)
            self.resize(600, 650)
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(28, 24, 28, 24)
            layout.setSpacing(15)
            def label(text, name=''):
                item=QtWidgets.QLabel(text);item.setObjectName(name);item.setWordWrap(True);return item
            layout.addWidget(label('DEVOS  /  CLOUD WORKSPACE', 'eyebrow'))
            layout.addWidget(label('Windows App', 'heading'))
            layout.addWidget(label('Your Cloud PC, with a timely reminder to return.', 'muted'))
            card=QtWidgets.QFrame();card.setObjectName('card');box=QtWidgets.QVBoxLayout(card)
            box.setContentsMargins(24, 18, 24, 20)
            self.status=label('Local reminder • paused', 'eyebrow');box.addWidget(self.status)
            self.countdown=label('10:00', 'clock');box.addWidget(self.countdown)
            self.description=label('This is a local reminder, not a live Cloud PC connection status.', 'muted');box.addWidget(self.description)
            layout.addWidget(card)
            open_button=QtWidgets.QPushButton('Open Windows App');open_button.setObjectName('primary');open_button.clicked.connect(self.open_app);layout.addWidget(open_button)
            row=QtWidgets.QHBoxLayout()
            reset=QtWidgets.QPushButton('I’ve used the Cloud PC');reset.clicked.connect(self.reset);row.addWidget(reset)
            self.pause_button=QtWidgets.QPushButton('Start reminders');self.pause_button.clicked.connect(self.toggle);row.addWidget(self.pause_button);layout.addLayout(row)
            form=QtWidgets.QFormLayout()
            self.limit=QtWidgets.QSpinBox();self.limit.setRange(2,120);self.limit.setSuffix(' min');self.limit.setValue(limit//60)
            self.lead=QtWidgets.QSpinBox();self.lead.setRange(1,119);self.lead.setSuffix(' min');self.lead.setValue(lead//60)
            form.addRow('Expected inactivity limit',self.limit);form.addRow('Warn before the limit',self.lead);layout.addLayout(form)
            self.limit.valueChanged.connect(self.configure);self.lead.valueChanged.connect(self.configure)
            self.notice=label('Opening the app does not reset this reminder. Connects to Microsoft 365 Cloud PC or Azure Virtual Desktop. To run Windows .exe files locally, use WinLayer.', 'muted');layout.addWidget(self.notice)
            self.timer=QtCore.QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.refresh)
            self.tray=QtWidgets.QSystemTrayIcon(app.windowIcon(),self)
            menu=QtWidgets.QMenu()
            menu.addAction('Open Windows App',self.open_app);menu.addAction('Show reminder',self.show_window)
            menu.addAction('I’ve used the Cloud PC',self.reset);menu.addAction('Pause reminders',self.pause)
            menu.addSeparator();menu.addAction('Quit companion',app.quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason:self.show_window() if reason==QtWidgets.QSystemTrayIcon.Trigger else None)
            self.tray.messageClicked.connect(self.open_app)
            if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():self.tray.show()
            self.refresh()

        def show_window(self):
            self.showNormal();self.raise_();self.activateWindow()

        def open_app(self):
            try:
                open_windows_app()
                self.notice.setText('Windows App was requested. Connect to and use your Cloud PC, then confirm “I’ve used the Cloud PC”.')
            except OSError as exc:
                self.notice.setText('Could not open Windows App: '+str(exc))
                self.show_window()

        def reset(self):
            self.reminder.start(clock());self.timer.start();self.refresh()

        def pause(self):
            self.reminder.pause();self.timer.stop();self.refresh()

        def toggle(self):
            self.pause() if self.reminder.started is not None else self.reset()

        def configure(self):
            blocker=QtCore.QSignalBlocker(self.lead)
            self.lead.setMaximum(self.limit.value()-1)
            del blocker
            try:
                limit,lead=self.limit.value()*60,self.lead.value()*60
                save_settings(self.settings_path,limit,lead)
            except (ValueError,OSError) as exc:
                self.notice.setText('Settings were not saved: '+str(exc));return
            self.reminder=Reminder(limit,lead);self.timer.stop();self.refresh()
            self.notice.setText('Reminder settings saved. Start reminders when your Cloud PC session begins.')

        def notify(self, expired):
            title='Check your Cloud PC' if expired else 'Your Cloud PC may disconnect soon'
            body=('The local inactivity reminder reached its limit. Open Windows App and check the session.' if expired else
                  f'About {self.reminder.lead//60} minutes remain on your local reminder. Return to Windows App and use the Cloud PC.')
            if self.notification is not None and self.notification.state()!=QtCore.QProcess.NotRunning:
                self.notification.kill()
            executable=shutil.which('notify-send')
            if executable:
                self.notification=QtCore.QProcess(self)
                self.notification.finished.connect(self.notification_finished)
                self.notification.errorOccurred.connect(lambda _:self.tray.showMessage(title,body))
                self.notification.start(executable,['--app-name=Windows App • DevOS','--icon=devos-web-winapp','--expire-time=45000','--wait','--action=open=Open Windows App','--action=show=Show reminder',title,body])
            else:
                self.tray.showMessage(title,body,QtWidgets.QSystemTrayIcon.Information,30000)
                if not self.tray.isVisible():self.show_window()

        def notification_finished(self):
            process=self.sender()
            action=bytes(process.readAllStandardOutput()).decode().strip()
            if action=='open':self.open_app()
            elif action=='show':self.show_window()
            process.deleteLater()
            if self.notification is process:self.notification=None

        def refresh(self):
            event=self.reminder.tick(clock());remaining=self.reminder.remaining(clock())
            self.countdown.setText(f'{remaining//60:02}:{remaining%60:02}')
            active=self.reminder.started is not None
            self.status.setText('LOCAL REMINDER  •  '+('CHECK SESSION' if self.reminder.expired else 'RUNNING' if active else 'PAUSED'))
            self.pause_button.setText('Pause reminders' if active else 'Start reminders')
            self.tray.setToolTip('Windows App • '+('Check your Cloud PC' if self.reminder.expired else self.countdown.text()+' local reminder' if active else 'Reminders paused'))
            if event:self.notify(event=='expired')
            if self.reminder.expired:self.timer.stop()

        def closeEvent(self,event):
            if self.tray.isVisible():self.hide();event.ignore()
            else:app.quit();event.accept()

        def shutdown(self):
            if self.notification is not None and self.notification.state()!=QtCore.QProcess.NotRunning:
                self.notification.kill();self.notification.waitForFinished(1000)

    window=Window()
    # Chrome creates the vendor shortcut asynchronously on first install.
    # Bounded polling repairs old pinned shortcuts without a resident watcher.
    launcher_timer=QtCore.QTimer(window)
    launcher_timer.setInterval(4000)
    attempts=0
    def refresh_launchers():
        nonlocal attempts
        directory = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'applications'
        restore_companion(directory)
        integrate(directory)
        attempts += 1
        if attempts >= 8: launcher_timer.stop()
    refresh_launchers()
    launcher_timer.timeout.connect(refresh_launchers)
    launcher_timer.start()
    def receive():
        client=server.nextPendingConnection()
        client.waitForReadyRead(300)
        if bytes(client.readAll())==b'open':window.open_app()
        client.disconnectFromServer();client.deleteLater();window.show_window()
    server.newConnection.connect(receive)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    if args.open:window.open_app();window.reset()
    return app.exec_()


if __name__=='__main__':raise SystemExit(main())
