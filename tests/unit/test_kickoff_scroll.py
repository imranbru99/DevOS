"""Scrolling All Applications must not replace that list with Favorites."""

import os
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "components"))

from kickoff.patch_kickoff_scroll import (  # noqa: E402
    MARKER,
    patch_appletsrc,
    patch_applications_page,
    patch_delegate,
    patch_kickoff_tree,
    patch_list_view,
)


LIST_VIEW = textwrap.dedent(
    """\
    EmptyPage {
        id: root
        property bool mainContentView: false
        property bool hasSectionView: false
        header: MouseArea {
            hoverEnabled: HOVER
            onEntered: {}
        }
        footer: MouseArea {
            hoverEnabled: HOVER
            onEntered: {}
        }
        contentItem: ListView {
            id: view
            currentIndex: count > 0 ? 0 : -1
            Connections {
                target: TARGET
                function onExpandedChanged() {
                    if (CONDITION) {
                        view.currentIndex = 0
                        view.positionViewAtBeginning()
                    }
                }
            }
            Keys.onPressed: OPENER
                currentIndex = 0
            }
        }
    }
    """
)

DELEGATE_ENTERED = textwrap.dedent(
    """\
    MouseArea {
        onEntered: {
            root.view.currentIndex = index
        }
        onPressed: mouse => {
            // Select and focus on press to improve responsiveness and touch feedback
            view.currentIndex = index
        }
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad | PointerDevice.Stylus
    }
    """
)

DELEGATE_POSITION = textwrap.dedent(
    """\
    MouseArea {
        onPositionChanged: {
            root.view.currentIndex = index
        }
        onPressed: {
            // Select and focus on press to improve responsiveness and touch feedback
            view.currentIndex = index
        }
    }
    """
)

APPLICATIONS = textwrap.dedent(
    """\
    BasePage {
        id: root
        sideBarComponent: KickoffListView {}
        Connections {
            target: root.sideBarItem
            function onCurrentIndexChanged() {
                // Only update row index if the condition is met.
                if (root.sideBarItem.currentIndex === 0) {
                    stackView.replace(stackView.preferredFavoritesViewComponent)
                }
            }
        }
    }
    """
)

APPLETS = textwrap.dedent(
    """\
    [Containments][1][Applets][4]
    plugin=org.kde.plasma.kickoff

    [Containments][1][Applets][5]
    plugin=org.kde.plasma.icontasks

    [Containments][1][Applets][4][Configuration][General]
    icon=devos-logo
    switchCategoryOnHover=true
    """
)


class TestKickoffScroll(unittest.TestCase):
    def test_plasma6_list_keeps_the_category_while_the_model_reloads(self):
        text = LIST_VIEW.replace(
            "HOVER",
            "mainContentView || Plasmoid.configuration.switchCategoryOnHover",
        ).replace("TARGET", "kickoff").replace("CONDITION", "!kickoff.expanded").replace(
            "OPENER",
            "event => {",
        )
        patched = patch_list_view(text)
        self.assertIn(MARKER, patched)
        self.assertNotIn("currentIndex: count > 0 ? 0 : -1", patched)
        self.assertNotIn("view.currentIndex = 0", patched)
        self.assertNotIn("switchCategoryOnHover", patched)
        self.assertEqual(patched.count("hoverEnabled: root.mainContentView"), 2)
        self.assertIn("devosHeldIndex", patched)
        self.assertIn("root.devosNoteUserPick(currentIndex)", patched)
        self.assertEqual(patch_list_view(patched), patched)

    def test_plasma5_list_uses_the_same_guard(self):
        text = LIST_VIEW.replace("HOVER", "true").replace("TARGET", "plasmoid").replace(
            "CONDITION",
            "plasmoid.expanded",
        ).replace("OPENER", "{")
        patched = patch_list_view(text)
        self.assertIn(MARKER, patched)
        self.assertNotIn("hoverEnabled: true", patched)
        self.assertIn("root.devosNoteUserPick(currentIndex)", patched)

    def test_hover_cannot_select_a_category(self):
        entered = patch_delegate(DELEGATE_ENTERED)
        self.assertIn("if (root.isCategoryListItem)", entered)
        self.assertNotIn("TouchPad", entered)
        self.assertLess(
            entered.index("if (root.isCategoryListItem)"),
            entered.index("root.view.currentIndex = index"),
        )
        self.assertIn("devosNoteUserPick(index)", entered)
        position = patch_delegate(DELEGATE_POSITION)
        self.assertIn("onPositionChanged:", position)
        self.assertIn("if (root.isCategoryListItem)", position)
        self.assertEqual(patch_delegate(entered), entered)

    def test_unsolicited_favorites_selection_is_restored_before_the_page_swap(self):
        patched = patch_applications_page(APPLICATIONS)
        self.assertIn("property int devosStickCategory: 0", patched)
        self.assertLess(
            patched.index("devosBar.currentIndex = devosKeep"),
            patched.index("preferredFavoritesViewComponent"),
        )
        self.assertLess(
            patched.index("return"),
            patched.index("preferredFavoritesViewComponent"),
        )
        self.assertEqual(patch_applications_page(patched), patched)

    def test_installed_tree_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            ui = os.path.join(tmp, "contents", "ui")
            os.makedirs(ui)
            list_text = LIST_VIEW.replace(
                "HOVER",
                "mainContentView || Plasmoid.configuration.switchCategoryOnHover",
            ).replace("TARGET", "kickoff").replace("CONDITION", "!kickoff.expanded").replace(
                "OPENER",
                "event => {",
            )
            with open(os.path.join(ui, "KickoffListView.qml"), "w", encoding="utf-8") as handle:
                handle.write(list_text)
            with open(os.path.join(ui, "AbstractKickoffItemDelegate.qml"), "w", encoding="utf-8") as handle:
                handle.write(DELEGATE_ENTERED)
            with open(os.path.join(ui, "ApplicationsPage.qml"), "w", encoding="utf-8") as handle:
                handle.write(APPLICATIONS)
            from pathlib import Path

            changed = patch_kickoff_tree(Path(tmp))
            self.assertEqual(len(changed), 3)
            self.assertEqual(patch_kickoff_tree(Path(tmp)), [])
        config = patch_appletsrc(APPLETS)
        self.assertIn("switchCategoryOnHover=false", config)
        self.assertNotIn("switchCategoryOnHover=true", config)
        self.assertIn("plugin=org.kde.plasma.icontasks", config)
        self.assertEqual(patch_appletsrc(config), config)
        self.assertEqual(patch_appletsrc("plugin=org.kde.plasma.icontasks\n"), "plugin=org.kde.plasma.icontasks\n")
        added = patch_appletsrc("[Containments][2][Applets][9]\nplugin=org.kde.plasma.kickoff\n")
        self.assertIn("[Containments][2][Applets][9][Configuration][General]", added)
        self.assertIn("switchCategoryOnHover=false", added)

    def test_menu_config_disables_hover_switching(self):
        apply_ui = os.path.join(ROOT, "build/includes.chroot/usr/local/share/devos/apply-ui.js")
        layout = os.path.join(
            ROOT,
            "build/includes.chroot/usr/share/plasma/look-and-feel/org.devos.desktop/contents/layouts/org.kde.plasma.desktop-layout.js",
        )
        hook = os.path.join(ROOT, "build/hooks/07-app-menu-scroll.hook.chroot")
        fixer = os.path.join(ROOT, "build/includes.chroot/usr/local/bin/devos-fix-app-menu-scroll")
        with open(apply_ui, encoding="utf-8") as handle:
            self.assertIn('writeConfig("switchCategoryOnHover", false)', handle.read())
        with open(layout, encoding="utf-8") as handle:
            self.assertIn('writeConfig("switchCategoryOnHover", false)', handle.read())
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertTrue(os.access(fixer, os.X_OK))
        with open(fixer, encoding="utf-8") as handle:
            self.assertIn("patch_kickoff_scroll.py", handle.read())


if __name__ == "__main__":
    unittest.main()
