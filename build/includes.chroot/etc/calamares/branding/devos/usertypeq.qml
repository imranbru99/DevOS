/* DevOS "How will you use this PC?" page (packagechooserq@usertype).
   Shown immediately before Choose your apps. Ten categories, the way Windows
   splits Home and Pro. The choice is one id; the apps page ticks that set. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

import "features-catalog.js" as Cat

Page {
    id: kindPage
    background: Rectangle { color: "#0b0f1a" }

    property string kind: "normal"

    function save() { config.packageChoice = kind; }
    onKindChanged: save()
    Component.onCompleted: save()

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 48
        clip: true

        ColumnLayout {
            id: form
            x: Math.max(28, (kindPage.width - width) / 2)
            y: 28
            width: Math.min(kindPage.width - 56, 920)
            spacing: 8

            Text {
                text: "How will you use this PC?"
                color: "#f8fafc"
                font.pixelSize: 32
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                Layout.bottomMargin: 8
                wrapMode: Text.WordWrap
                color: "#94a3b8"
                font.pixelSize: 15
                text: "Pick the closest one, the way Windows offers Home, Pro and the rest. "
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
