/* DevOS installer sidebar: logo + steps. Narrows on short/narrow screens. */
import io.calamares.ui 1.0
import io.calamares.core 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Rectangle {
    id: sideBar
    anchors.fill: parent
    implicitWidth: InstallerAppearance.sidebarWidth
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
        anchors.margins: InstallerAppearance.tiny ? 12 : (InstallerAppearance.compact ? 14 : 22)
        spacing: 0

        RowLayout {
            spacing: InstallerAppearance.tiny ? 8 : 12
            Layout.bottomMargin: InstallerAppearance.tiny ? 14 : (InstallerAppearance.compact ? 20 : 34)
            MotionLogo {
                animated: sideBar.visible && InstallerAppearance.motionEnabled
                source: "file:/" + Branding.imagePath(Branding.ProductLogo)
                Layout.preferredWidth: InstallerAppearance.tiny ? 32 : 44
                Layout.preferredHeight: InstallerAppearance.tiny ? 32 : 44
            }
            Column {
                visible: !InstallerAppearance.tiny || sideBar.width >= 160
                Text {
                    text: "DevOS"
                    color: "#f8fafc"
                    font.pixelSize: InstallerAppearance.compact ? 16 : 20
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Installer"
                    color: "#64748b"
                    font.pixelSize: 11
                    font.letterSpacing: 1.2
                }
            }
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: stepsCol.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            ColumnLayout {
                id: stepsCol
                width: parent.width
                spacing: 0

                Repeater {
                    id: stepRepeater
                    model: ViewManager
                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(
                            InstallerAppearance.tiny ? 34 : 48,
                            Math.max(InstallerAppearance.tiny ? 26 : 30,
                                     (sideBar.height - (InstallerAppearance.tiny ? 120 : 210))
                                     / Math.max(1, stepRepeater.count))
                        )
                        readonly property bool current: index === ViewManager.currentStepIndex
                        readonly property bool done: index < ViewManager.currentStepIndex

                        Rectangle {
                            visible: index > 0
                            x: InstallerAppearance.tiny ? 11 : 15
                            y: 14 - parent.height / 2
                            width: 2
                            height: Math.max(2, parent.height - 28)
                            color: (done || current) ? "#38bdf8" : "#1f2a40"
                        }

                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: -6
                            radius: 10
                            color: current ? "#13203a" : "transparent"
                            border.color: current ? "#1e3a5f" : "transparent"
                        }

                        Rectangle {
                            id: dot
                            x: InstallerAppearance.tiny ? 0 : 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: InstallerAppearance.tiny ? 22 : 28
                            height: width
                            radius: width / 2
                            color: done ? "#38bdf8" : current ? "#0b1220" : "#111827"
                            border.width: 2
                            border.color: (done || current) ? "#38bdf8" : "#2a3550"
                            Text {
                                anchors.centerIn: parent
                                text: done ? "✓" : (index + 1)
                                color: done ? "#04121f" : current ? "#7dd3fc" : "#64748b"
                                font.pixelSize: InstallerAppearance.tiny ? 11 : 13
                                font.bold: true
                            }
                        }

                        Text {
                            anchors.left: dot.right
                            anchors.leftMargin: InstallerAppearance.tiny ? 8 : 14
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: display
                            elide: Text.ElideRight
                            color: current ? "#f8fafc" : done ? "#cbd5e1" : "#7c879c"
                            font.pixelSize: InstallerAppearance.tiny ? 12 : (InstallerAppearance.compact ? 13 : 15)
                            font.weight: current ? Font.DemiBold : Font.Normal
                        }
                    }
                }
            }
        }

        CheckBox {
            text: InstallerAppearance.tiny ? "Motion" : "Animations"
            checked: InstallerAppearance.motionEnabled
            onToggled: InstallerAppearance.motionEnabled = checked
            Accessible.name: "Installer animations"
            contentItem: Text {
                text: parent.text
                leftPadding: parent.indicator.width + parent.spacing
                verticalAlignment: Text.AlignVCenter
                color: "#cbd5e1"
                font.pixelSize: 12
            }
        }

        Text {
            Layout.fillWidth: true
            text: Branding.string(Branding.ShortVersionedName)
            elide: Text.ElideRight
            color: "#475569"
            font.pixelSize: 11
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: debug.about()
            }
        }
    }
}
