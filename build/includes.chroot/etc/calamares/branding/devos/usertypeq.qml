/* DevOS "How will you use this PC?" page (packagechooserq@usertype).
   Shown immediately before Choose your apps. Ten categories, the way Windows
   splits Home and Pro. The choice is one id; the apps page ticks that set. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

import "features-catalog.js" as Cat
import "preferred-usertype.js" as Pref

Page {
    id: kindPage
    background: InstallerBackground {}

    property string kind: "normal"
    property bool kindReady: false

    function preferredKind() {
        // boot_ui Premium / Premium+Safe writes preferred-usertype.js via install-gui.
        var text = (Pref.preferred || "").replace(/^\s+|\s+$/g, "")
        if (!text) return "normal"
        for (var j = 0; j < Cat.data.userTypes.length; j++) {
            if (Cat.data.userTypes[j].id === text)
                return text
        }
        return "normal"
    }

    function loadSavedKind() {
        var keys = ["packagechooser_usertype", "usertype"]
        for (var i = 0; i < keys.length; i++) {
            if (!Global.contains(keys[i]))
                continue
            var raw = Global.value(keys[i])
            var text = (raw === undefined || raw === null) ? "" : String(raw).replace(/^\s+|\s+$/g, "")
            for (var k = 0; k < Cat.data.userTypes.length; k++) {
                if (Cat.data.userTypes[k].id === text)
                    return text
            }
        }
        return ""
    }

    function save() { config.packageChoice = kind; }
    onKindChanged: {
        save()
        // Only when the user picks a different PC type — not when this page restores itself.
        if (kindReady) {
            try { Global.insert("devos_features_usertype", ""); } catch (e) {}
        }
    }
    Component.onCompleted: {
        // Keep the user's PC-type pick when they press Back, then Next again.
        kind = loadSavedKind() || preferredKind()
        save()
        kindReady = true
    }

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 48
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: form
            x: Math.max(InstallerAppearance.pageMargin, (kindPage.width - width) / 2)
            y: InstallerAppearance.pageMargin
            width: Math.min(kindPage.width - InstallerAppearance.pageMargin * 2, 920)
            spacing: 8

            PageIntro {
                Layout.fillWidth: true
                Layout.bottomMargin: 8
                eyebrow: "PC TYPE"
                title: "How will you use this PC?"
                subtitle: "Pick the closest one, the way Windows offers Home, Pro and the rest. "
                    + "The next page ticks those apps, and you can still turn any of them on or off."
            }

            Flow {
                id: grid
                Layout.fillWidth: true
                spacing: 10

                Repeater {
                    model: Cat.data.userTypes
                    delegate: Rectangle {
                        readonly property var item: modelData
                        readonly property bool picked: kindPage.kind === item.id
                        readonly property int columns: grid.width >= 700 ? 2 : 1
                        width: Math.floor((grid.width - (columns - 1) * grid.spacing) / columns)
                        implicitHeight: row.implicitHeight + 24
                        radius: 16
                        color: picked ? "#0c2338" : "#0f172a"
                        border.color: picked ? "#38bdf8" : "#1e293b"
                        border.width: picked ? 2 : 1

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: kindPage.kind = item.id
                        }
                        RowLayout {
                            id: row
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12
                            Rectangle {
                                implicitWidth: 46
                                implicitHeight: 46
                                radius: 14
                                color: picked ? "#083044" : "#111827"
                                Text {
                                    anchors.centerIn: parent
                                    text: item.mark
                                    color: picked ? "#7dd3fc" : "#94a3b8"
                                    font.pixelSize: item.mark.length > 2 ? 13 : 18
                                    font.weight: Font.DemiBold
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text {
                                    text: item.name
                                    color: "#f8fafc"
                                    font.pixelSize: 16
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    text: item.about
                                    color: "#94a3b8"
                                    font.pixelSize: 13
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
