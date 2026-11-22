"""All Applications stays put, with small Favorite icons and large app icons."""

import os
import sys
import textwrap
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "components"))

from kickoff.patch_kickoff_scroll import MARKER, patch_appletsrc  # noqa: E402

PKG = os.path.join(
    ROOT,
    "build/includes.chroot/usr/local/share/plasma/plasmoids/org.kde.plasma.kickoff",
)


def read(relative):
    with open(os.path.join(PKG, relative), encoding="utf-8") as handle:
        return handle.read()


APPLETS = textwrap.dedent(
    """\
    [Containments][1][Applets][4]
    plugin=org.kde.plasma.kickoff

    [Containments][1][Applets][5]
    plugin=org.kde.plasma.icontasks

    [Containments][1][Applets][4][Configuration][General]
    icon=devos-logo
    switchCategoryOnHover=true
    favoritesDisplay=1
    applicationsDisplay=1
    """
)


class TestKickoffScroll(unittest.TestCase):
    def test_model_reload_does_not_jump_to_favorites(self):
        text = read("contents/ui/KickoffListView.qml")
        self.assertIn(MARKER, text)
        self.assertNotIn("currentIndex: count > 0 ? 0 : -1", text)
        self.assertNotIn("if (!activeFocus)", text)
        self.assertNotIn("view.currentIndex = 0", text)
        self.assertIn("root.isSidebar", text)
        self.assertEqual(text.count("hoverEnabled: root.mainContentView"), 2)
        self.assertIn("function devosNoteUserPick", text)

    def test_resting_on_a_category_does_not_select_it(self):
        text = read("contents/ui/AbstractKickoffItemDelegate.qml")
        entered = text.split("onEntered:", 1)[1].split("onPressed:", 1)[0]
        self.assertLess(entered.index("if (root.isCategoryListItem)"), entered.index("return"))
        pressed = text.split("onPressed:", 1)[1]
        self.assertLess(
            pressed.index("devosNoteUserPick(root.index)"),
            pressed.index("root.view.currentIndex = root.index"),
        )

    def test_unsolicited_favorites_selection_is_restored_before_the_page_swap(self):
        text = read("contents/ui/ApplicationsPage.qml")
        self.assertIn("property int devosHeldCategory: 0", text)
        restore_at = text.index("root.sideBarItem.currentIndex = stackView.devosHeldCategory")
        after = text[restore_at:]
        self.assertLess(
            after.index("return"),
            after.index("stackView.replace(stackView.preferredFavoritesViewComponent)"),
        )
        self.assertIn("devosCompact: true", text)

    def test_favorites_are_small_and_applications_are_large(self):
        delegate = read("contents/ui/KickoffGridDelegate.qml")
        self.assertIn("Kirigami.Units.iconSizes.smallMedium", delegate)
        self.assertIn("Kirigami.Units.iconSizes.huge", delegate)
        grid = read("contents/ui/KickoffGridView.qml")
        self.assertIn("property bool devosCompact: false", grid)
        self.assertIn("root.devosCompact", grid)
        config = read("contents/config/main.xml")
        self.assertIn("<entry name=\"applicationsDisplay\"", config)
        apps = config.split("<entry name=\"applicationsDisplay\"", 1)[1].split("</entry>", 1)[0]
        self.assertIn("<default>0</default>", apps)

    def test_installed_config(self):
        config = patch_appletsrc(APPLETS)
        self.assertIn("switchCategoryOnHover=false", config)
        self.assertNotIn("switchCategoryOnHover=true", config)
        self.assertIn("favoritesDisplay=0", config)
        self.assertIn("applicationsDisplay=0", config)
        self.assertNotIn("applicationsDisplay=1", config)
        self.assertIn("plugin=org.kde.plasma.icontasks", config)
        self.assertEqual(patch_appletsrc(config), config)
        self.assertEqual(
            patch_appletsrc("plugin=org.kde.plasma.icontasks\n"),
            "plugin=org.kde.plasma.icontasks\n",
        )
        added = patch_appletsrc("[Containments][2][Applets][9]\nplugin=org.kde.plasma.kickoff\n")
        self.assertIn("[Containments][2][Applets][9][Configuration][General]", added)
        self.assertIn("switchCategoryOnHover=false", added)
        self.assertIn("applicationsDisplay=0", added)

    def test_menu_package_and_installer(self):
        apply_ui = os.path.join(ROOT, "build/includes.chroot/usr/local/share/devos/apply-ui.js")
        layout = os.path.join(
            ROOT,
            "build/includes.chroot/usr/share/plasma/look-and-feel/org.devos.desktop/contents/layouts/org.kde.plasma.desktop-layout.js",
        )
        hook = os.path.join(ROOT, "build/hooks/07-app-menu-scroll.hook.chroot")
        fixer = os.path.join(ROOT, "build/includes.chroot/usr/local/bin/devos-fix-app-menu-scroll")
        with open(apply_ui, encoding="utf-8") as handle:
            apply_text = handle.read()
        self.assertIn('writeConfig("switchCategoryOnHover", false)', apply_text)
        self.assertIn('writeConfig("applicationsDisplay", 0)', apply_text)
        with open(layout, encoding="utf-8") as handle:
            layout_text = handle.read()
        self.assertIn('writeConfig("switchCategoryOnHover", false)', layout_text)
        self.assertIn('writeConfig("applicationsDisplay", 0)', layout_text)
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertTrue(os.access(fixer, os.X_OK))
        with open(fixer, encoding="utf-8") as handle:
            fixer_text = handle.read()
        self.assertNotIn("/usr/share/plasma/plasmoids/org.kde.plasma.kickoff/contents/ui/ApplicationsPage.qml", fixer_text)
        self.assertIn("org.kde.plasma.kickoff.so", fixer_text)
        self.assertIn("dpkg-divert", fixer_text)
        self.assertIn(MARKER, fixer_text)
        with open(os.path.join(PKG, "metadata.json"), encoding="utf-8") as handle:
            metadata = handle.read()
        self.assertIn("org.kde.plasma.kickoff", metadata)
        self.assertIn("Plasma/Applet", metadata)
        for relative in (
            "contents/ui/main.qml",
            "contents/ui/KickoffListView.qml",
            "contents/ui/code/tools.js",
            "contents/ui/qmldir",
        ):
            self.assertTrue(os.path.isfile(os.path.join(PKG, relative)), relative)
        self.assertIn(MARKER, read("contents/ui/ApplicationsPage.qml"))


if __name__ == "__main__":
    unittest.main()
