/* Lightweight motion shared by the welcome page and installer sidebar. */
import QtQuick 2.15

Item {
    id: emblem
    property url source
    property bool animated: visible && InstallerAppearance.motionEnabled
    implicitWidth: 64
    implicitHeight: 64

    Rectangle {
        anchors.centerIn: parent
        width: parent.width
        height: width
        radius: width / 2
        color: "transparent"
        border.color: "#38bdf8"
        border.width: 1
        SequentialAnimation on scale {
            running: emblem.animated
            loops: Animation.Infinite
            NumberAnimation { from: 0.82; to: 1.18; duration: 1900; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.82; duration: 1900; easing.type: Easing.InOutSine }
        }
        SequentialAnimation on opacity {
            running: emblem.animated
            loops: Animation.Infinite
            NumberAnimation { from: 0.15; to: 0.5; duration: 1900 }
            NumberAnimation { to: 0.15; duration: 1900 }
        }
    }
    Item {
        anchors.fill: parent
        RotationAnimator on rotation {
            running: emblem.animated
            from: 0; to: 360; duration: 9000; loops: Animation.Infinite
        }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            y: -2
            width: 5; height: 5; radius: 2.5
            color: "#7dd3fc"
        }
    }
    Image {
        anchors.centerIn: parent
        width: parent.width * 0.78
        height: width
        source: emblem.source
        sourceSize.width: 160
        sourceSize.height: 160
        fillMode: Image.PreserveAspectFit
    }
}
