"""Shared presentation for DevOS Qt dialogs; authentication remains with Polkit."""
from PyQt5 import QtCore, QtGui, QtWidgets


class DialogStyle(QtCore.QObject):
    def eventFilter(self, widget, event):
        if event.type() == QtCore.QEvent.Show and isinstance(widget, (QtWidgets.QMessageBox, QtWidgets.QInputDialog)):
            if not widget.property('devosDialogStyled'):
                widget.setProperty('devosDialogStyled', True)
                dark = widget.palette().color(QtGui.QPalette.Window).lightness() < 128
                # Most branded apps use a dark stylesheet rather than a dark palette.
                dark = dark or bool(widget.parentWidget() and '#080d1a' in widget.parentWidget().styleSheet())
                bg, fg, panel, border = ('#101828', '#edf3fc', '#1e2d43', '#34465f') if dark else ('#f7f9fd', '#172438', '#e8eef7', '#b9c8da')
                widget.setStyleSheet('''
                    QDialog { background: %s; color: %s; font-family: "Inter", "Noto Sans"; font-size: 11pt; }
                    QLabel { background: transparent; color: %s; padding: 6px 2px; }
                    QPushButton { min-height: 28px; min-width: 86px; padding: 6px 16px;
                        border-radius: 9px; border: 1px solid %s; background: %s; color: %s; }
                    QPushButton:hover { border-color: #38bdf8; }
                    QPushButton:focus { border: 2px solid #38bdf8; }
                    QPushButton:default { border: 2px solid #38bdf8; }
                    QPushButton[devosDestructive="true"] { background: #a52c40; color: white; border-color: #d75a6c; }
                    QPushButton[devosDestructive="true"]:hover { background: #bf354b; }
                    QLineEdit, QTextEdit { padding: 10px; border: 1px solid %s; border-radius: 8px; background: %s; color: %s; }
                    QLineEdit:focus { border: 2px solid #38bdf8; }
                ''' % (bg, fg, fg, border, panel, fg, border, panel, fg))
                screen = widget.screen() or QtWidgets.QApplication.primaryScreen()
                available = screen.availableGeometry().width() - 48 if screen else 600
                widget.setMinimumWidth(min(580, available))
                for button in widget.findChildren(QtWidgets.QPushButton):
                    width = max(110, len(button.text().replace('&', '')) * 9 + 16)
                    # Keep dialog button colors — only size, never wipe the themed sheet.
                    button.setMinimumWidth(width)
                    button.setMinimumHeight(44)
                if widget.layout():
                    widget.layout().setContentsMargins(24, 20, 24, 20)
                    widget.layout().setSpacing(14)
                if isinstance(widget, QtWidgets.QMessageBox):
                    for label in widget.findChildren(QtWidgets.QLabel):
                        if label.objectName() in ('qt_msgbox_label', 'qt_msgbox_informativelabel'):
                            label.setWordWrap(True)
                            label.setMaximumWidth(520)
                            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse)
                widget.setWindowIcon(QtWidgets.QApplication.windowIcon())
        return False


def install(app):
    """Install once per application without changing dialog results or safe defaults."""
    from devos_appearance import install as install_appearance
    install_appearance(app)
    if not hasattr(app, '_devos_dialog_style'):
        app._devos_dialog_style = DialogStyle(app)
        app.installEventFilter(app._devos_dialog_style)
