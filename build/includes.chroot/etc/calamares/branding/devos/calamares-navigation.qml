/* DevOS installer bottom bar: Cancel on the left, Back / Next on the right. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.15
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

    component NavButton: Rectangle {
        id: btn
        property string label: ""
        property bool primary: false
        signal clicked()
        implicitWidth: Math.max(120, caption.implicitWidth + 44)
        implicitHeight: 44
        radius: 12
        opacity: enabled ? 1.0 : 0.35
        color: primary ? (area.containsMouse ? "#5ec8ff" : "#38bdf8")
                       : (area.containsMouse ? "#1c2740" : "#141b2d")
        border.width: primary ? 0 : 1
        border.color: "#26324d"
        Behavior on color { ColorAnimation { duration: 120 } }
        Text {
            id: caption
            anchors.centerIn: parent
            text: btn.label.replace("&", "")
            color: btn.primary ? "#04121f" : "#e2e8f0"
            font.pixelSize: 15
            font.weight: Font.DemiBold
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (btn.enabled) btn.clicked()
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
