/* DevOS installer bottom bar: Cancel / Back / Next — always height-pinned so
   Summary and tall pages cannot push Next under laptop bezels or panels. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Rectangle {
    id: navigationBar

    readonly property int barHeight: InstallerAppearance.navBarHeight
    readonly property int buttonHeight: InstallerAppearance.navButtonHeight
    readonly property int sideMargin: InstallerAppearance.tiny ? 12 : (InstallerAppearance.compact ? 16 : 28)
    readonly property bool compact: InstallerAppearance.compact

    height: barHeight
    implicitHeight: barHeight
    Layout.preferredHeight: barHeight
    Layout.minimumHeight: barHeight
    Layout.maximumHeight: barHeight
    Layout.fillWidth: true
    color: "#0b0f1a"
    z: 100
    clip: false

    Rectangle {
        width: parent.width
        height: 1
        color: "#1b2438"
    }

    component NavButton: Button {
        id: btn
        property string label: ""
        property bool primary: false
        text: label.replace(/&/g, "")
        Accessible.name: text
        implicitWidth: Math.max(navigationBar.compact ? 88 : 120, caption.implicitWidth + (navigationBar.compact ? 24 : 44))
        implicitHeight: navigationBar.buttonHeight
        Layout.preferredHeight: navigationBar.buttonHeight
        Layout.minimumHeight: navigationBar.buttonHeight
        Layout.maximumHeight: navigationBar.buttonHeight
        opacity: enabled ? 1.0 : 0.35
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        background: Rectangle {
            radius: navigationBar.compact ? 10 : 12
            color: btn.primary ? (btn.down ? "#0ea5e9" : btn.hovered ? "#5ec8ff" : "#38bdf8")
                               : (btn.down ? "#263754" : btn.hovered ? "#1c2740" : "#141b2d")
            border.width: btn.activeFocus ? 2 : btn.primary ? 0 : 1
            border.color: btn.activeFocus ? "#f8fafc" : "#26324d"
            Behavior on color {
                enabled: InstallerAppearance.motionEnabled
                ColorAnimation { duration: 120 }
            }
        }
        contentItem: Text {
            id: caption
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: btn.text
            color: btn.primary ? "#04121f" : "#e2e8f0"
            font.pixelSize: InstallerAppearance.tiny ? 12 : (navigationBar.compact ? 13 : 15)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: navigationBar.sideMargin
        anchors.rightMargin: navigationBar.sideMargin
        anchors.topMargin: InstallerAppearance.tiny ? 6 : (navigationBar.compact ? 8 : 12)
        anchors.bottomMargin: InstallerAppearance.tiny ? 6 : (navigationBar.compact ? 8 : 12)
        spacing: navigationBar.compact ? 8 : 12

        NavButton {
            label: ViewManager.quitLabel
            visible: ViewManager.quitVisible
            enabled: ViewManager.quitEnabled
            onClicked: ViewManager.quit()
        }

        Item { Layout.fillWidth: true }

        NavButton {
            label: ViewManager.backLabel
            visible: ViewManager.backAndNextVisible
            enabled: ViewManager.backEnabled
            onClicked: ViewManager.back()
        }

        NavButton {
            id: nextButton
            label: ViewManager.nextLabel
            primary: true
            visible: ViewManager.backAndNextVisible
            enabled: ViewManager.nextEnabled
            onClicked: ViewManager.next()
        }
    }
}
