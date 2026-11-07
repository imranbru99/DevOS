"""DevOS PolicyKit authentication dialog styling is packaged and wired."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
STYLE = ROOT / "components/ui/qtquick/DevOS"
AGENT = ROOT / "build/includes.chroot/usr/local/bin/devos-authentication-agent"
DROPIN = ROOT / "build/includes.chroot/etc/systemd/user/plasma-polkit-agent.service.d/20-devos-style.conf"
CHROOT_STYLE = ROOT / "build/includes.chroot/usr/local/share/devos/components/ui/qtquick/DevOS"


class AuthenticationStyleTests(unittest.TestCase):
    def test_quick_controls_module_is_complete(self):
        required = (
            "qmldir",
            "ApplicationWindow.qml",
            "Button.qml",
            "TextField.qml",
            "ToolButton.qml",
            "Label.qml",
            "Control.qml",
            "Pane.qml",
            "Frame.qml",
        )
        for name in required:
            self.assertTrue((STYLE / name).is_file(), name)
        qmldir = (STYLE / "qmldir").read_text(encoding="utf-8")
        self.assertIn("module DevOS", qmldir)
        self.assertIn("Button 2.15", qmldir)
        self.assertIn("TextField 2.15", qmldir)

    def test_toolbutton_respects_icon_only_for_password_reveal(self):
        """Kirigami PasswordField embeds an IconOnly ToolButton; text must not paint."""
        text = (STYLE / "ToolButton.qml").read_text(encoding="utf-8")
        self.assertIn("IconOnly", text)
        self.assertIn("iconOnly", text)
        field = (STYLE / "TextField.qml").read_text(encoding="utf-8")
        self.assertIn("Password", field)

    def test_agent_wrapper_enables_devos_style(self):
        text = AGENT.read_text(encoding="utf-8")
        self.assertIn("QT_QUICK_CONTROLS_STYLE=DevOS", text)
        self.assertIn("QML_IMPORT_PATH", text)
        self.assertIn("polkit-kde-authentication-agent-1", text)
        self.assertIn("KDE_COLOR_SCHEME", text)

    def test_systemd_and_chroot_ship_the_style(self):
        self.assertIn("devos-authentication-agent", DROPIN.read_text(encoding="utf-8"))
        self.assertTrue((CHROOT_STYLE / "qmldir").is_file())
        self.assertTrue((CHROOT_STYLE / "Button.qml").is_file())


if __name__ == "__main__":
    unittest.main()
