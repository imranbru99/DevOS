/* DevOS "Choose your DevOS AI" page (packagechooserq@aimodel).
   aimodel-hw.js is rewritten at live boot by devos-ai-hwprobe with this PC's
   RAM, processor and disk, so the page can pre-select the model that fits and
   grey out the ones that would make the PC slow. The choice is stored as
   "<size>[+vision][+coder]" (config.packageChoice); contextualprocess@aimodel
   writes it into the new system, which downloads it once it is online. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

import "aimodel-hw.js" as HW

Page {
    id: aiPage
    background: Rectangle { color: "#0b0f1a" }

    property string chat: HW.hw.recommended
    property bool vision: HW.hw.recommended_extras.indexOf("vision") >= 0
    property bool coder: false

    function sizeOf(id) {
        for (var i = 0; i < HW.hw.models.length; i++)
            if (HW.hw.models[i].id === id) return HW.hw.models[i].built_in ? 0 : HW.hw.models[i].size_mb;
        return 0;
    }
    function coderSize() { return (chat === "large" || chat === "xl") ? 4680 : 1120; }
    function totalMb() { return sizeOf(chat) + (vision ? 520 : 0) + (coder ? coderSize() : 0); }
    function human(mb) { return mb >= 1000 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB"; }
    function save() {
        config.packageChoice = chat + (vision ? "+vision" : "") + (coder ? "+coder" : "");
    }

    onChatChanged: save()
    onVisionChanged: save()
    onCoderChanged: save()
    Component.onCompleted: save()

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 80
        clip: true

        ColumnLayout {
            id: form
            x: Math.max(40, (parent.width - width) / 2)
            y: 40
            width: Math.min(aiPage.width - 80, 720)
            spacing: 8

            Text {
                text: "Choose your DevOS AI"
                color: "#f8fafc"
                font.pixelSize: 32
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "DevOS AI runs privately on this PC. Bigger models answer better but need more memory. "
                    + "We picked the best one for this computer."
                color: "#94a3b8"
                font.pixelSize: 15
            }
            Text {
                Layout.fillWidth: true
                Layout.bottomMargin: 8
                wrapMode: Text.WordWrap
                color: "#64748b"
                font.pixelSize: 13
                text: "This PC: " + HW.hw.ram_gb + " GB RAM · " + HW.hw.threads + " processor threads"
                    + (HW.hw.cpu ? " · " + HW.hw.cpu : "")
                    + (HW.hw.gpu ? "\nGraphics: " + HW.hw.gpu : "")
            }

            Repeater {
                model: HW.hw.models
                delegate: Rectangle {
                    readonly property var m: modelData
                    readonly property bool picked: aiPage.chat === m.id
                    Layout.fillWidth: true
                    implicitHeight: row.implicitHeight + 24
                    radius: 14
                    opacity: m.fits ? 1.0 : 0.45
                    color: picked ? "#0c2338" : "#0f172a"
                    border.color: picked ? "#38bdf8" : "#1e293b"
                    border.width: picked ? 2 : 1

                    MouseArea {
                        anchors.fill: parent
                        enabled: m.fits
                        cursorShape: m.fits ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: aiPage.chat = m.id
                    }
                    RowLayout {
                        id: row
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 14
                        RadioButton {
                            checked: parent.parent.picked
                            enabled: m.fits
                            onClicked: aiPage.chat = m.id
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            RowLayout {
                                spacing: 10
                                Text {
                                    text: m.name + "  ·  " + m.params
                                    color: "#f8fafc"
                                    font.pixelSize: 16
                                    font.weight: Font.DemiBold
                                }
                                Rectangle {
                                    visible: m.id === HW.hw.recommended
                                    radius: 8
                                    color: "#14532d"
                                    implicitWidth: rec.implicitWidth + 14
                                    implicitHeight: rec.implicitHeight + 6
                                    Text { id: rec; anchors.centerIn: parent; text: "Recommended for this PC"; color: "#4ade80"; font.pixelSize: 12 }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: "#94a3b8"
                                font.pixelSize: 13
                                text: m.about + (m.fits ? "" : "  Needs " + m.min_ram_gb + " GB RAM.")
                            }
                        }
                        Text {
                            color: "#cbd5e1"
                            font.pixelSize: 13
                            text: m.built_in ? "Included" : aiPage.human(m.size_mb)
                        }
                    }
                }
            }

            Text {
                text: "Extras"
                color: "#f8fafc"
                font.pixelSize: 18
                font.weight: Font.DemiBold
                Layout.topMargin: 14
            }
            Repeater {
                model: HW.hw.extras
                delegate: Rectangle {
                    readonly property var e: modelData
                    Layout.fillWidth: true
                    implicitHeight: erow.implicitHeight + 20
                    radius: 14
                    color: "#0f172a"
                    border.color: "#1e293b"
                    opacity: e.fits ? 1.0 : 0.45
                    RowLayout {
                        id: erow
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 12
                        CheckBox {
                            enabled: e.fits
                            checked: e.id === "vision" ? aiPage.vision : aiPage.coder
                            onToggled: {
                                if (e.id === "vision") aiPage.vision = checked;
                                else aiPage.coder = checked;
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Text { text: e.name; color: "#f8fafc"; font.pixelSize: 15 }
                            Text {
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: "#94a3b8"
                                font.pixelSize: 13
                                text: e.about
                            }
                        }
                        Text {
                            color: "#cbd5e1"
                            font.pixelSize: 13
                            text: aiPage.human(e.id === "coder" ? aiPage.coderSize() : e.size_mb)
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 14
                implicitHeight: info.implicitHeight + 28
                radius: 14
                color: "#0f172a"
                border.color: "#1e293b"
                Text {
                    id: info
                    anchors.fill: parent
                    anchors.margins: 14
                    wrapMode: Text.WordWrap
                    color: "#e2e8f0"
                    font.pixelSize: 14
                    text: HW.hw.built_in_skills + "\n"
                        + (aiPage.totalMb() > 0
                           ? "Download after install: " + aiPage.human(aiPage.totalMb())
                             + ". It starts by itself when the PC is online; DevOS AI works with the built-in model meanwhile."
                           : "Nothing to download.")
                        + " Change it any time in DevOS AI Models."
                }
            }
        }
    }
}
