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
            // During install exec the modal can fail to raise; force reboot immediately
            // so the user is never trapped at a stuck shell step.
            onClicked: {
                if (!ViewManager.backAndNextVisible)
                    navigationBar.requestPower("/reboot")
                else
                    powerWin.openFor("reboot")
            }
        }

        NavButton {
            label: navigationBar.compact ? "Shut down" : "Shut down"
            danger: true
            onClicked: {
                if (!ViewManager.backAndNextVisible)
                    navigationBar.requestPower("/poweroff")
                else
                    powerWin.openFor("poweroff")
            }
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
            onClicked: {
                // Replace Calamares' stock QMessageBox ("Install Now") with a
                // fullscreen branded card — prompt-install is false in settings.
                var label = String(ViewManager.nextLabel || "").replace(/&/g, "").toLowerCase()
                if (label.indexOf("install") >= 0)
                    installWin.open()
                else
                    ViewManager.next()
            }
        }
    }

    // Top-level Window (not an Item in the nav bar). Calamares branding QML has
    // no usable Window.window/Overlay — a previous overlay stayed parented to the
    // bottom nav strip, so the confirm text appeared under the progress bar.
    function coverScreen(win) {
        var scr = Screen
        if (typeof Qt !== "undefined" && Qt.application && Qt.application.screens && Qt.application.screens.length)
            scr = Qt.application.screens[0]
        win.width = scr.width || 1280
        win.height = scr.height || 720
        win.x = scr.virtualX || 0
        win.y = scr.virtualY || 0
        win.visible = true
        win.raise()
        win.requestActivate()
    }

    Window {
        id: installWin
        visible: false
        color: "#cc020617"
        title: "Install DevOS?"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        modality: Qt.ApplicationModal

        function open() {
            navigationBar.coverScreen(installWin)
            installCancel.forceActiveFocus()
        }
        function close() { visible = false }

        Rectangle {
            anchors.fill: parent
            color: "#cc020617"
            focus: true
            Keys.onEscapePressed: installWin.close()
            MouseArea {
                anchors.fill: parent
                onClicked: installWin.close()
            }

            Rectangle {
                width: Math.min(480, Math.max(320, parent.width - 64))
                height: installCol.implicitHeight + 44
                radius: 20
                color: "#0f172a"
                border.color: "#38bdf8"
                border.width: 1
                anchors.centerIn: parent
                MouseArea { anchors.fill: parent; onClicked: {} }

                ColumnLayout {
                    id: installCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 26
                    spacing: 12

                    Text {
                        text: "INSTALL"
                        color: "#38bdf8"
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        font.letterSpacing: 2.2
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Install DevOS now?"
                        color: "#f8fafc"
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#94a3b8"
                        font.pixelSize: 14
                        lineHeight: 1.4
                        text: "This writes DevOS to the disk you chose. Existing files on that system disk will be replaced. Nothing has been written yet."
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 10
                        Item { Layout.fillWidth: true }
                        NavButton {
                            id: installCancel
                            label: "Go back"
                            onClicked: installWin.close()
                        }
                        NavButton {
                            label: "Install Now"
                            primary: true
                            onClicked: {
                                installWin.close()
                                ViewManager.next()
                            }
                        }
                    }
                }
            }
        }
    }

    Window {
        id: powerWin
        property string op: "reboot"
        property string titleText: op === "reboot" ? "Restart this PC?" : "Shut down this PC?"
        visible: false
        color: "#cc020617"
        title: titleText
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        modality: Qt.ApplicationModal

        function openFor(nextOp) {
            op = nextOp
            navigationBar.coverScreen(powerWin)
            cancelBtn.forceActiveFocus()
        }

        function close() {
            visible = false
        }

        Rectangle {
            anchors.fill: parent
            color: "#cc020617"
            focus: true
            Keys.onEscapePressed: powerWin.close()
            MouseArea {
                anchors.fill: parent
                onClicked: powerWin.close()
            }

            Rectangle {
                id: powerCard
                width: Math.min(440, Math.max(300, parent.width - 64))
                height: cardCol.implicitHeight + 40
                radius: 18
                color: "#0f172a"
                border.color: "#1e3a5f"
                border.width: 1
                anchors.centerIn: parent
                MouseArea { anchors.fill: parent; onClicked: {} }

                ColumnLayout {
                    id: cardCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 24
                    spacing: 14

                    Text {
                        Layout.fillWidth: true
                        text: powerWin.titleText
                        color: "#f8fafc"
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#94a3b8"
                        font.pixelSize: 14
                        lineHeight: 1.35
                        text: powerWin.op === "reboot"
                              ? "The installer will close and this PC will restart. Unsaved work in other windows will be lost."
                              : "The installer will close and this PC will shut down. Unsaved work in other windows will be lost."
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        spacing: 10
                        Item { Layout.fillWidth: true }
                        NavButton {
                            id: cancelBtn
                            label: "Cancel"
                            onClicked: powerWin.close()
                        }
                        NavButton {
                            label: powerWin.op === "reboot" ? "Restart now" : "Shut down now"
                            primary: powerWin.op === "reboot"
                            danger: powerWin.op === "poweroff"
                            onClicked: {
                                powerWin.close()
                                navigationBar.requestPower(powerWin.op === "reboot" ? "/reboot" : "/poweroff")
                            }
                        }
                    }
                }
            }
        }
    }
}
