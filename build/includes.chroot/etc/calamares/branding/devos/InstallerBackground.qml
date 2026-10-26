/* Shared restrained motion; no videos, network downloads or per-frame scripts. */
import QtQuick 2.15

Rectangle {
    id: scene
    color: "#070a12"
    clip: true
    Image {
        anchors.fill: parent
        source: "installer-background.svg"
        fillMode: Image.PreserveAspectCrop
        opacity: 0.7
    }
    Rectangle {
        width: Math.min(scene.width * 0.48, 480)
        height: width
        radius: width / 2
        x: scene.width * 0.65
        y: scene.height * 0.08
        color: "#0d6895"
        opacity: 0.07
        SequentialAnimation on y {
            running: scene.visible && InstallerAppearance.motionEnabled
            loops: Animation.Infinite
            NumberAnimation { from: scene.height * 0.04; to: scene.height * 0.22; duration: 14000; easing.type: Easing.InOutSine }
            NumberAnimation { to: scene.height * 0.04; duration: 14000; easing.type: Easing.InOutSine }
        }
    }
    Rectangle {
        width: Math.min(scene.width * 0.4, 400)
        height: width
        radius: width / 2
        x: scene.width * 0.52
        y: scene.height * 0.6
        color: "#5453b6"
        opacity: 0.06
        SequentialAnimation on x {
            running: scene.visible && InstallerAppearance.motionEnabled
            loops: Animation.Infinite
            NumberAnimation { from: scene.width * 0.4; to: scene.width * 0.6; duration: 18000; easing.type: Easing.InOutSine }
            NumberAnimation { to: scene.width * 0.4; duration: 18000; easing.type: Easing.InOutSine }
        }
    }
}
