/* DevOS installer bottom bar: power + Cancel / Back / Next.
   Height-pinned so Summary cannot push Next under laptop bezels. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import QtQuick.Window 2.15

Rectangle {
    id: navigationBar

    readonly property int barHeight: InstallerAppearance.navBarHeight
    readonly property int buttonHeight: InstallerAppearance.navButtonHeight
    readonly property int sideMargin: InstallerAppearance.tiny ? 10 : (InstallerAppearance.compact ? 14 : 24)
    readonly property bool compact: InstallerAppearance.compact
    readonly property string powerBase: "http://127.0.0.1:41777"

    height: barHeight
    implicitHeight: barHeight
    Layout.preferredHeight: barHeight
    Layout.minimumHeight: barHeight
    Layout.maximumHeight: barHeight
    Layout.fillWidth: true
    color: "#0b0f1a"
    z: 100
    clip: false

    function requestPower(path) {
        var xhr = new XMLHttpRequest()
        xhr.open("POST", navigationBar.powerBase + path)
        xhr.send()
    }

    Rectangle {
        width: parent.width
        height: 1
        color: "#1b2438"
    }

    component NavButton: Button {
        id: btn
        property string label: ""
        property bool primary: false
        property bool danger: false
        text: label.replace(/&/g, "")
        Accessible.name: text
        implicitWidth: Math.max(navigationBar.compact ? 78 : 108, caption.implicitWidth + (navigationBar.compact ? 20 : 36))
        implicitHeight: navigationBar.buttonHeight
        Layout.preferredHeight: navigationBar.buttonHeight
        Layout.minimumHeight: navigationBar.buttonHeight
        Layout.maximumHeight: navigationBar.buttonHeight
        opacity: enabled ? 1.0 : 0.35
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        background: Rectangle {
            radius: navigationBar.compact ? 10 : 12
            color: {
                if (btn.primary)
                    return btn.down ? "#0ea5e9" : btn.hovered ? "#5ec8ff" : "#38bdf8"
                if (btn.danger)
                    return btn.down ? "#7f1d1d" : btn.hovered ? "#3f1d1d" : "#1a1218"
                return btn.down ? "#263754" : btn.hovered ? "#1c2740" : "#141b2d"
            }
            border.width: btn.activeFocus ? 2 : (btn.primary ? 0 : 1)
            border.color: btn.activeFocus ? "#f8fafc" : (btn.danger ? "#7f1d1d" : "#26324d")
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
            color: btn.primary ? "#04121f" : (btn.danger ? "#fecaca" : "#e2e8f0")
            font.pixelSize: InstallerAppearance.tiny ? 11 : (navigationBar.compact ? 12 : 14)
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
        spacing: navigationBar.compact ? 6 : 10

        NavButton {
            label: ViewManager.quitLabel
            visible: ViewManager.quitVisible
            enabled: ViewManager.quitEnabled
            onClicked: ViewManager.quit()
        }

        NavButton {
            label: navigationBar.compact ? "Restart" : "Restart"
            onClicked: powerDialog.openFor("reboot")
        }

        NavButton {
            label: navigationBar.compact ? "Shut down" : "Shut down"
            danger: true
            onClicked: powerDialog.openFor("poweroff")
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

    Dialog {
        id: powerDialog
        property string op: "reboot"
        parent: navigationBar.Window.window ? navigationBar.Window.window.contentItem : navigationBar
        anchors.centerIn: parent
        modal: true
        focus: true
        width: Math.min(420, Math.max(280, navigationBar.width - 40))
        title: op === "reboot" ? "Restart this PC?" : "Shut down this PC?"
        standardButtons: Dialog.NoButton
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        function openFor(nextOp) {
            op = nextOp
            open()
        }

        background: Rectangle {
            radius: 18
            color: "#0f172a"
            border.color: "#1e3a5f"
            border.width: 1
        }

        header: Item {
            height: 56
            width: powerDialog.width
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: powerDialog.title
                color: "#f8fafc"
                font.pixelSize: 18
                font.weight: Font.DemiBold
            }
        }

        contentItem: Text {
            width: powerDialog.availableWidth
            wrapMode: Text.WordWrap
            color: "#94a3b8"
            font.pixelSize: 14
            lineHeight: 1.35
            text: powerDialog.op === "reboot"
                  ? "The installer will close and this PC will restart. Unsaved work in other windows will be lost."
                  : "The installer will close and this PC will shut down. Unsaved work in other windows will be lost."
            padding: 8
        }

        footer: Item {
            height: 64
            width: powerDialog.width
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.bottomMargin: 14
                spacing: 10
                Item { Layout.fillWidth: true }
                NavButton {
                    label: "Cancel"
                    onClicked: powerDialog.close()
                }
                NavButton {
                    label: powerDialog.op === "reboot" ? "Restart now" : "Shut down now"
                    primary: powerDialog.op === "reboot"
                    danger: powerDialog.op === "poweroff"
                    onClicked: {
                        powerDialog.close()
                        navigationBar.requestPower(powerDialog.op === "reboot" ? "/reboot" : "/poweroff")
                    }
                }
            }
        }
    }
}
