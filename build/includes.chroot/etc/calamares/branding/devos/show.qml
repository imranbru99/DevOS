/* DevOS install slideshow (slideshowAPI 2).
   Calamares does not give the slideshow the install progress, so this page
   shows no steps or bar of its own: the real progress bar and the current
   task are directly below it. It only rotates short highlights. */
import QtQuick 2.15
import calamares.slideshow 1.0

Presentation {
    id: presentation

    property int current: 0
    readonly property var cards: [
        { tag: "WINDOWS APPS", title: "Run .exe programs", body: "Double-click a Windows installer and DevOS opens it in its own safe space. No Windows licence needed." },
        { tag: "ANDROID APPS", title: "Install .apk files", body: "Android apps open in their own window next to your desktop apps." },
        { tag: "LOCAL AI", title: "A private assistant", body: "DevOS AI runs on this computer. Your questions and files never leave it." },
        { tag: "ALWAYS FAST", title: "Optimizer keeps it quick", body: "Unused apps and leftover files are pointed out before they slow you down." },
        { tag: "FOR BUILDERS", title: "Ready to code", body: "Git, Node.js, Python, PHP, databases and VS Code are already installed." }
    ]

    function onActivate() { rotator.running = true }
    function onLeave() { rotator.running = false }

    // Slides keep a 16:9 box in the middle; paint the area around it too,
    // otherwise the slideshow sat in a white frame.
    Rectangle {
        anchors.fill: parent
        z: -1
        color: "#0b0f1a"
    }

    Timer {
        id: rotator
        interval: 7000
        repeat: true
        running: false
        onTriggered: fade.restart()
    }

    SequentialAnimation {
        id: fade
        NumberAnimation { target: card; property: "opacity"; to: 0; duration: 300 }
        ScriptAction { script: presentation.current = (presentation.current + 1) % presentation.cards.length }
        NumberAnimation { target: card; property: "opacity"; to: 1; duration: 450 }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            clip: true
            radius: 16
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0a1020" }
                GradientStop { position: 1.0; color: "#120d24" }
            }

            // Soft glow behind the card
            Rectangle {
                width: parent.width * 0.7
                height: width
                radius: width / 2
                x: parent.width * 0.45
                y: -height * 0.35
                color: "#1438bdf8"
            }

            Column {
                id: card
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: Math.max(40, parent.width * 0.08)
                width: Math.min(parent.width * 0.7, 680)
                spacing: 14

                Text {
                    text: presentation.cards[presentation.current].tag
                    color: "#38bdf8"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    font.letterSpacing: 3
                }
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: presentation.cards[presentation.current].title
                    color: "#f8fafc"
                    font.pixelSize: 38
                    font.weight: Font.Bold
                }
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: presentation.cards[presentation.current].body
                    color: "#cbd5e1"
                    font.pixelSize: 18
                    lineHeight: 1.25
                }
            }

            Row {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 28
                anchors.left: card.left
                spacing: 8
                Repeater {
                    model: presentation.cards.length
                    Rectangle {
                        width: index === presentation.current ? 26 : 8
                        height: 8
                        radius: 4
                        color: index === presentation.current ? "#38bdf8" : "#334155"
                        Behavior on width { NumberAnimation { duration: 250 } }
                    }
                }
            }
        }
    }
}
