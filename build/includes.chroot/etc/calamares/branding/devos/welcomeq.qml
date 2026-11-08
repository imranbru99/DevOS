/* DevOS welcome page (welcomeq module). Overrides the built-in welcomeq.qml. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Page {
    id: welcome
    clip: true
    background: InstallerBackground {}

    Image {
        id: hero
        anchors.fill: parent
        source: "file:/" + Branding.imagePath(Branding.ProductWelcome)
        fillMode: Image.PreserveAspectCrop
        opacity: 0.55
        SequentialAnimation on scale {
            running: welcome.visible && InstallerAppearance.motionEnabled
            loops: Animation.Infinite
            NumberAnimation { from: 1; to: 1.04; duration: 12000; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1; duration: 12000; easing.type: Easing.InOutSine }
        }
    }
    // Darken the left side so the text stays readable over the artwork.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#f2070a12" }
            GradientStop { position: 0.55; color: "#b3070a12" }
            GradientStop { position: 1.0; color: "#1a070a12" }
        }
    }

    Flickable {
        id: welcomeScroll
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: Math.max(height, welcomeContent.implicitHeight + 64)
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        Item {
            width: welcomeScroll.width
            height: welcomeScroll.contentHeight

            ColumnLayout {
                id: welcomeContent
                property bool entered: false
                Component.onCompleted: entered = true
                opacity: entered ? 1 : 0
                Behavior on opacity {
                    enabled: InstallerAppearance.motionEnabled
                    NumberAnimation { duration: 650; easing.type: Easing.OutCubic }
                }
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Math.max(24, parent.width * 0.07)
                width: Math.min(parent.width - anchors.leftMargin - 24, 640)
                spacing: 0

                MotionLogo {
                    source: "file:/" + Branding.imagePath(Branding.ProductLogo)
                    animated: welcome.visible && InstallerAppearance.motionEnabled
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 80
                    Layout.bottomMargin: 22
                }

                PageIntro {
                    Layout.fillWidth: true
                    eyebrow: "WELCOME"
                    title: Branding.string(Branding.ProductName) + " " + Branding.string(Branding.Version)
                    titleSize: InstallerAppearance.tiny ? 28 : (InstallerAppearance.compact ? 34 : 44)
                    subtitle: "One fast desktop for Linux, Windows and Android apps, with a private AI assistant built in."
                }

                Flow {
                    Layout.topMargin: 28
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: ["Erase & format disk", "Windows apps", "Android apps", "Local AI", "Voice Typing", "Developer tools"]
                        Rectangle {
                            height: 34
                            width: chip.implicitWidth + 28
                            radius: 17
                            color: "#1a0f172a"
                            border.color: index === 0 ? "#38bdf8" : "#334a6e"
                            opacity: InstallerAppearance.motionEnabled ? 0 : 1
                            SequentialAnimation on opacity {
                                running: welcome.visible && InstallerAppearance.motionEnabled
                                loops: 1
                                PauseAnimation { duration: 90 * index }
                                NumberAnimation { from: 0; to: 1; duration: 420; easing.type: Easing.OutCubic }
                            }
                            Text {
                                id: chip
                                anchors.centerIn: parent
                                text: modelData
                                color: index === 0 ? "#7dd3fc" : "#e2e8f0"
                                font.pixelSize: 14
                            }
                        }
                    }
                }

                Text {
                    Layout.topMargin: 40
                    text: "Language"
                    color: "#94a3b8"
                    font.pixelSize: 13
                    font.letterSpacing: 1
                }
                ComboBox {
                    id: languages
                    Layout.topMargin: 8
                    Layout.preferredWidth: Math.min(360, welcomeContent.width)
                    Layout.preferredHeight: 46
                    textRole: "label"
                    model: config.languagesModel
                    currentIndex: config.localeIndex
                    onCurrentIndexChanged: config.localeIndex = currentIndex
                    font.pixelSize: 15
                    background: Rectangle {
                        radius: 12
                        color: "#0f172a"
                        border.color: languages.activeFocus ? "#38bdf8" : "#2a3550"
                    }
                    contentItem: Text {
                        leftPadding: 16
                        verticalAlignment: Text.AlignVCenter
                        text: languages.displayText
                        color: "#f8fafc"
                        font: languages.font
                        elide: Text.ElideRight
                    }
                }

                // Only shown when the computer misses something (disk size, RAM...).
                Rectangle {
                    Layout.topMargin: 28
                    Layout.fillWidth: true
                    visible: !config.requirementsModel.satisfiedRequirements
                    implicitHeight: reqColumn.implicitHeight + 32
                    radius: 14
                    color: config.requirementsModel.satisfiedMandatory ? "#1f1a0b" : "#2a1014"
                    border.color: config.requirementsModel.satisfiedMandatory ? "#a16207" : "#b91c1c"
                    Column {
                        id: reqColumn
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 6
                        Text {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            color: "#f8fafc"
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            text: config.requirementsModel.satisfiedMandatory
                                  ? "DevOS can be installed, but this computer misses a recommendation:"
                                  : "DevOS cannot be installed on this computer yet:"
                        }
                        // No per-item list: Calamares fills requirementsModel from a
                        // worker thread, and delegates bound to it crashed the
                        // installer ("different thread than the QML engine").
                        Text {
                            width: reqColumn.width
                            wrapMode: Text.WordWrap
                            color: "#cbd5e1"
                            font.pixelSize: 14
                            text: "DevOS needs at least 32 GB of disk space and 2 GB of memory. "
                                + "For comfortable daily use, allow 64 GB of storage and 4 GB of memory. "
                                + "Plug in the charger on a laptop."
                        }
                    }
                }
            }
        }
    }
}
