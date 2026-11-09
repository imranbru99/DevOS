"""Chrome Start-menu cleaner: no raw URLs, no duplicate Windows App."""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components"))

from browser.chrome_start_menu import clean_chrome_start_menu, friendly_url_name  # noqa: E402


def test_friendly_url_names():
    assert friendly_url_name("https://onedrive.live.com/") == "OneDrive"
    assert friendly_url_name("https://www.office.com/") == "Microsoft 365"
    assert friendly_url_name("https://www.youtube.com/watch?v=1") == "YouTube"
    assert friendly_url_name("https://windows.cloud.microsoft/") == "Windows App"
    assert friendly_url_name("Not a URL") is None


def test_hides_url_named_and_duplicate_windows_app(tmp_path, monkeypatch):
    apps = tmp_path / "applications"
    apps.mkdir()
    # Fake system companion so Windows App Chrome copy must hide.
    sys_apps = tmp_path / "system"
    sys_apps.mkdir()
    (sys_apps / "devos-web-winapp.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Windows App\nExec=/usr/local/bin/devos-windows-app\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "browser.chrome_start_menu._SYSTEM_APP_DIRS",
        (sys_apps,),
    )

    url_desk = apps / ("chrome-" + ("a" * 32) + "-Default.desktop")
    url_desk.write_text(
        "[Desktop Entry]\nType=Application\nName=https://onedrive.live.com/\n"
        "Exec=/usr/bin/google-chrome-stable --app-id=" + ("a" * 32) + "\n"
        "Categories=Chrome Apps;Network;\n",
        encoding="utf-8",
    )
    win_desk = apps / ("chrome-" + ("b" * 32) + "-Default.desktop")
    win_desk.write_text(
        "[Desktop Entry]\nType=Application\nName=Windows App\n"
        "Exec=/usr/bin/google-chrome-stable --app-id=" + ("b" * 32) + "\n",
        encoding="utf-8",
    )
    prof = apps / ("chrome-" + ("c" * 32) + "-Profile_1.desktop")
    prof.write_text(
        "[Desktop Entry]\nType=Application\nName=YouTube\n"
        "Exec=/usr/bin/google-chrome-stable --app-id=" + ("c" * 32) + "\n",
        encoding="utf-8",
    )

    assert clean_chrome_start_menu(apps) >= 2
    url_text = url_desk.read_text(encoding="utf-8")
    assert "Name=OneDrive" in url_text
    # Companion exists for OneDrive? not in fake system — rename only, may stay visible
    win_text = win_desk.read_text(encoding="utf-8")
    assert "NoDisplay=true" in win_text
    assert "NoDisplay=true" in prof.read_text(encoding="utf-8")


def test_debrand_hides_calamares_htop_ibus():
    script = (
        ROOT / "build/includes.chroot/usr/local/sbin/devos-debrand-desktop"
    ).read_text(encoding="utf-8", errors="replace")
    for needle in ('"calamares"', '"htop"', '"ibus-setup"', '"winetricks"',
                   '"org.kde.kdeconnect.app"', r"\bCalamares\b", "Phone Link",
                   "Disk Management", "About this PC"):
        assert needle in script, needle
    apply = (
        ROOT / "build/includes.chroot/usr/local/bin/devos-apply-desktop"
    ).read_text(encoding="utf-8", errors="replace")
    assert "chrome_start_menu.py" in apply
