/* DevOS installer sidebar: logo, numbered steps with a progress rail. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Rectangle {
    id: sideBar
    anchors.fill: parent
    implicitWidth: 248
    gradient: Gradient {
        GradientStop { position: 0.0; color: "#0a0f1d" }
        GradientStop { position: 1.0; color: "#070912" }
    }

    Rectangle {
        anchors.right: parent.right
        width: 1
        height: parent.height
        color: "#1b2438"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 0

        RowLayout {
            spacing: 12
            Layout.bottomMargin: 34
            MotionLogo {
                animated: sideBar.visible && InstallerAppearance.motionEnabled
                source: "file:/" + Branding.imagePath(Branding.ProductLogo)
                Layout.preferredWidth: 44
                Layout.preferredHeight: 44
            }
            Column {
                Text {
                    text: "DevOS"
                    color: "#f8fafc"
                    font.pixelSize: 20
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Installer"
                    color: "#64748b"
                    font.pixelSize: 12
                    font.letterSpacing: 1.5
                }
            }
        }

        Repeater {
            id: stepRepeater
            model: ViewManager
            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(48, Math.max(30, (sideBar.height - 210) / Math.max(1, stepRepeater.count)))
                readonly property bool current: index === ViewManager.currentStepIndex
                readonly property bool done: index < ViewManager.currentStepIndex

                // Rail between the step dots
                Rectangle {
                    visible: index > 0
                    x: 15
                    y: 14 - parent.height / 2
                    width: 2
                    height: Math.max(2, parent.height - 28)
                    color: (done || current) ? "#38bdf8" : "#1f2a40"
                    Behavior on color { ColorAnimation { duration: 350 } }
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: -8
                    radius: 10
                    color: current ? "#13203a" : "transparent"
                    border.color: current ? "#1e3a5f" : "transparent"
                    Behavior on color { ColorAnimation { duration: 300 } }
                }

                Rectangle {
                    id: dot
                    SequentialAnimation on scale {
                        running: current && sideBar.visible && InstallerAppearance.motionEnabled
                        loops: Animation.Infinite
                        NumberAnimation { to: 1.08; duration: 1100; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 1100; easing.type: Easing.InOutSine }
                    }
                    x: 2
                    anchors.verticalCenter: parent.verticalCenter
                    width: 28
                    height: 28
                    radius: 14
                    color: done ? "#38bdf8" : current ? "#0b1220" : "#111827"
                    border.width: 2
                    border.color: (done || current) ? "#38bdf8" : "#2a3550"
                    Text {
                        anchors.centerIn: parent
                        text: done ? "✓" : (index + 1)
                        color: done ? "#04121f" : current ? "#7dd3fc" : "#64748b"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }

                Text {
                    anchors.left: dot.right
                    anchors.leftMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    text: display
                    color: current ? "#f8fafc" : done ? "#cbd5e1" : "#7c879c"
                    font.pixelSize: 15
                    font.weight: current ? Font.DemiBold : Font.Normal
                }
            }
        }

        Item { Layout.fillHeight: true }

        CheckBox {
            text: "Animations"
            checked: InstallerAppearance.motionEnabled
            onToggled: InstallerAppearance.motionEnabled = checked
            Accessible.name: "Installer animations"
            contentItem: Text {
                text: parent.text
                leftPadding: parent.indicator.width + parent.spacing
                verticalAlignment: Text.AlignVCenter
                color: "#cbd5e1"
                font.pixelSize: 13
            }
        }

        Text {
            Layout.fillWidth: true
            text: Branding.string(Branding.VersionedName)
            color: "#475569"
            font.pixelSize: 12
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: debug.about()
            }
        }
    }
}
