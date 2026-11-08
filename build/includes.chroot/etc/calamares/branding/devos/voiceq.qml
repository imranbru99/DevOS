/* DevOS "Voice & Mira" installer page (packagechooserq@voice).
   Stores: mira=1;gender=female;lang=auto;wake=Mira
   Applied into the new system by shellprocess@voice-apply. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Page {
    id: page
    background: InstallerBackground {}

    property bool miraOn: true
    property string gender: "female"   // female | male
    property string lang: "auto"       // auto | en | bn
    property string wakeName: "Mira"

    readonly property var samples: ({
        en_female: "Hello, I'm Mira. I can open apps, search the web, and help with this PC.",
        en_male: "Hello, I'm Mira. I can open apps, search the web, and help with this PC.",
        bn_female: "হ্যালো, আমি মিরা। আমি অ্যাপ খুলতে পারি এবং এই কম্পিউটারে সাহায্য করতে পারি।",
        bn_male: "হ্যালো, আমি মিরা। আমি অ্যাপ খুলতে পারি এবং এই কম্পিউটারে সাহায্য করতে পারি।"
    })

    function sampleKey() {
        var g = gender === "male" ? "male" : "female"
        var l = (testLang.currentIndex === 1) ? "bn" : "en"
        return l + "_" + g
    }
    function sampleText() { return samples[sampleKey()] || samples.en_female }

    function save() {
        var safeWake = (wakeName && wakeName.trim().length) ? wakeName.trim() : "Mira"
        safeWake = safeWake.replace(/[;=]/g, "")
        config.packageChoice = "mira=" + (miraOn ? "1" : "0")
            + ";gender=" + gender
            + ";lang=" + lang
            + ";wake=" + safeWake
    }

    onMiraOnChanged: save()
    onGenderChanged: save()
    onLangChanged: save()
    onWakeNameChanged: save()
    Component.onCompleted: save()

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 80
        clip: true

        ColumnLayout {
            id: form
            x: Math.max(40, (parent.width - width) / 2)
            y: 36
            width: Math.min(page.width - 80, 720)
            spacing: 10

            Text {
                text: "Voice & Mira"
                color: "#f8fafc"
                font.pixelSize: 32
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: "#94a3b8"
                font.pixelSize: 15
                text: "Choose how DevOS AI sounds, and whether saying a name like Mira starts listening without tapping the microphone. Replies follow the language you speak."
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 8
                radius: 14
                color: "#0f172a"
                border.color: "#1e293b"
                implicitHeight: wakeCol.implicitHeight + 28
                ColumnLayout {
                    id: wakeCol
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    Text {
                        text: "Hands-free wake name"
                        color: "#e2e8f0"
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#94a3b8"
                        font.pixelSize: 13
                        text: "When this is on, anyone who says the name out loud starts DevOS AI listening, then it runs the command after they finish speaking."
                    }
                    CheckBox {
                        id: miraBox
                        checked: page.miraOn
                        text: "Enable wake listening (recommended)"
                        onCheckedChanged: page.miraOn = checked
                        contentItem: Text {
                            text: miraBox.text
                            color: "#e2e8f0"
                            font.pixelSize: 14
                            leftPadding: miraBox.indicator.width + 8
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    RowLayout {
                        spacing: 10
                        Text { text: "Name"; color: "#94a3b8"; font.pixelSize: 13 }
                        TextField {
                            Layout.fillWidth: true
                            text: page.wakeName
                            placeholderText: "Mira"
                            color: "#f8fafc"
                            onTextChanged: page.wakeName = text
                            background: Rectangle {
                                radius: 8
                                color: "#0b1220"
                                border.color: "#334155"
                            }
                        }
                    }
                }
            }

            Text {
                Layout.topMargin: 6
                text: "Spoken reply voice"
                color: "#e2e8f0"
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            RowLayout {
                spacing: 10
                Repeater {
                    model: [
                        { id: "female", label: "Female", hint: "Clear, natural" },
                        { id: "male", label: "Male", hint: "Warm, natural" }
                    ]
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        radius: 12
                        implicitHeight: 64
                        color: page.gender === modelData.id ? "#0c2338" : "#0f172a"
                        border.color: page.gender === modelData.id ? "#38bdf8" : "#1e293b"
                        border.width: page.gender === modelData.id ? 2 : 1
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.gender = modelData.id
                        }
                        Column {
                            anchors.centerIn: parent
                            spacing: 2
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: "#f8fafc"
                                font.pixelSize: 15
                                font.weight: Font.DemiBold
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.hint
                                color: "#94a3b8"
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }

            Text {
                Layout.topMargin: 6
                text: "Reply language"
                color: "#e2e8f0"
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            ComboBox {
                id: langBox
                Layout.fillWidth: true
                model: ["Match what I speak (Bangla ↔ English)", "Always English", "Always Bangla"]
                currentIndex: page.lang === "en" ? 1 : (page.lang === "bn" ? 2 : 0)
                onActivated: {
                    page.lang = index === 1 ? "en" : (index === 2 ? "bn" : "auto")
                }
            }

            Text {
                Layout.topMargin: 6
                text: "Sample phrases for this voice"
                color: "#e2e8f0"
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            Rectangle {
                Layout.fillWidth: true
                radius: 12
                color: "#0f172a"
                border.color: "#1e293b"
                implicitHeight: testCol.implicitHeight + 24
                ColumnLayout {
                    id: testCol
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    ComboBox {
                        id: testLang
                        Layout.fillWidth: true
                        model: ["English sample", "Bangla sample"]
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#cbd5e1"
                        font.pixelSize: 13
                        text: "“" + page.sampleText() + "”"
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#64748b"
                        font.pixelSize: 12
                        text: "After install, open DevOS AI → Voice settings → Play sample to hear the male or female neural voice on this PC."
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 4
                wrapMode: Text.WordWrap
                color: "#64748b"
                font.pixelSize: 12
                text: "You can change the wake name, voice, and language anytime in DevOS AI → Voice settings."
            }
        }
    }
}
