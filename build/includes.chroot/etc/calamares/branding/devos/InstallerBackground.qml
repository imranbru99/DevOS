/* Premium animated installer backdrop: soft photo crossfade + aurora motion.
   Used by every custom QML page so text never sits on a flat black panel. */
import QtQuick 2.15

Rectangle {
    id: scene
    color: "#070a12"
    clip: true

    readonly property var slides: [
        "bg/02.jpg", "bg/03.jpg", "bg/04.jpg", "bg/05.jpg", "bg/06.jpg",
        "bg/01.jpg", "installer-background.svg"
    ]
    property int current: 0
    property bool motionOn: InstallerAppearance.motionEnabled

    // Crossfading scenic layer
    Repeater {
        model: scene.slides.length
        Image {
            id: plate
            anchors.fill: parent
            source: scene.slides[index]
            fillMode: Image.PreserveAspectCrop
            opacity: index === scene.current ? 0.72 : 0
            z: index === scene.current ? 1 : 0
            scale: index === scene.current ? 1.14 : 1.0
            Behavior on opacity {
                enabled: scene.motionOn
                NumberAnimation { duration: 800; easing.type: Easing.InOutCubic }
            }
            SequentialAnimation on scale {
                running: scene.visible && scene.motionOn && index === scene.current
                loops: Animation.Infinite
                NumberAnimation { from: 1.08; to: 1.22; duration: 6200; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.08; duration: 6200; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on x {
                running: scene.visible && scene.motionOn && index === scene.current
                loops: Animation.Infinite
                NumberAnimation { from: -28; to: 28; duration: 4800; easing.type: Easing.InOutSine }
                NumberAnimation { to: -28; duration: 4800; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                running: scene.visible && scene.motionOn && index === scene.current
                loops: Animation.Infinite
                NumberAnimation { from: -12; to: 12; duration: 5600; easing.type: Easing.InOutSine }
                NumberAnimation { to: -12; duration: 5600; easing.type: Easing.InOutSine }
            }
        }
    }

    Timer {
        interval: 4500
        running: scene.visible && scene.motionOn && scene.slides.length > 1
        repeat: true
        onTriggered: scene.current = (scene.current + 1) % scene.slides.length
    }

    // Aurora orbs — stronger drift so motion is obvious on camera
    Rectangle {
        width: Math.min(scene.width * 0.55, 560)
        height: width
        radius: width / 2
        x: scene.width * 0.58
        y: -height * 0.25
        color: "#0ea5e9"
        opacity: 0.22
        SequentialAnimation on y {
            running: scene.visible && scene.motionOn
            loops: Animation.Infinite
            NumberAnimation { from: -height * 0.28; to: scene.height * 0.12; duration: 7000; easing.type: Easing.InOutSine }
            NumberAnimation { to: -height * 0.28; duration: 7000; easing.type: Easing.InOutSine }
        }
    }
    Rectangle {
        width: Math.min(scene.width * 0.42, 420)
        height: width
        radius: width / 2
        x: -width * 0.2
        y: scene.height * 0.55
        color: "#0ea5e9"
        opacity: 0.18
        SequentialAnimation on x {
            running: scene.visible && scene.motionOn
            loops: Animation.Infinite
            NumberAnimation { from: -width * 0.25; to: scene.width * 0.15; duration: 8000; easing.type: Easing.InOutSine }
            NumberAnimation { to: -width * 0.25; duration: 8000; easing.type: Easing.InOutSine }
        }
    }
    Rectangle {
        width: Math.min(scene.width * 0.28, 280)
        height: width
        radius: width / 2
        x: scene.width * 0.35
        y: scene.height * 0.7
        color: "#22d3ee"
        opacity: 0.14
        SequentialAnimation on opacity {
            running: scene.visible && scene.motionOn
            loops: Animation.Infinite
            NumberAnimation { from: 0.08; to: 0.22; duration: 3500; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.08; duration: 3500; easing.type: Easing.InOutSine }
        }
    }

    // Left readability veil for form text
    Rectangle {
        anchors.fill: parent
        z: 5
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#e6070a12" }
            GradientStop { position: 0.45; color: "#99070a12" }
            GradientStop { position: 1.0; color: "#33070a12" }
        }
    }

    // Soft top/bottom vignette
    Rectangle {
        anchors.fill: parent
        z: 6
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#66070a12" }
            GradientStop { position: 0.2; color: "#00000000" }
            GradientStop { position: 0.8; color: "#00000000" }
            GradientStop { position: 1.0; color: "#88070a12" }
        }
    }
}
