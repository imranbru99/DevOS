import QtQuick 2.15

Rectangle {
    id: splash
    property int stage: 0
    readonly property real scaleUnit: Math.max(0.75, Math.min(1.5, Math.min(width / 1024, height / 640)))
    color: "#080e1b"

    Column {
        anchors.centerIn: parent
        spacing: 18 * splash.scaleUnit

        Image {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 88 * splash.scaleUnit
            height: width
            source: "file:///usr/share/pixmaps/devos-logo.png"
            fillMode: Image.PreserveAspectFit
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "DevOS"
            color: "#f1f7ff"
            font.pixelSize: 44 * splash.scaleUnit
            font.weight: Font.DemiBold
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("Starting your desktop")
            color: "#b8cce6"
            font.pixelSize: 16 * splash.scaleUnit
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 176 * splash.scaleUnit
            height: 4 * splash.scaleUnit
            radius: height / 2
            color: "#22334b"

            Rectangle {
                width: parent.width * Math.max(0.12, Math.min(1, splash.stage / 6))
                height: parent.height
                radius: height / 2
                color: "#38bdf8"
                Behavior on width { NumberAnimation { duration: 180 } }
            }
        }
    }
}
