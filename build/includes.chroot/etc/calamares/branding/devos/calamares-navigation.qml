/* DevOS installer bottom bar: Cancel on the left, Back / Next on the right. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Rectangle {
    id: navigationBar
    implicitHeight: 76
    color: "#0b0f1a"

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
        implicitWidth: Math.max(120, caption.implicitWidth + 44)
        implicitHeight: 44
        opacity: enabled ? 1.0 : 0.35
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        background: Rectangle {
            radius: 12
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
            font.pixelSize: 15
            font.weight: Font.DemiBold
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 28
        anchors.rightMargin: 28
        spacing: 12

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
            label: ViewManager.nextLabel
            primary: true
            visible: ViewManager.backAndNextVisible
            enabled: ViewManager.nextEnabled
            onClicked: ViewManager.next()
        }
    }
}
