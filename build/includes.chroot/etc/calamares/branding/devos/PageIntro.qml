/* Shared premium page header: eyebrow + title + subtitle with enter motion. */
import QtQuick 2.15
import QtQuick.Layouts 1.3

ColumnLayout {
    id: intro
    property string eyebrow: ""
    property string title: ""
    property string subtitle: ""
    property int titleSize: InstallerAppearance.pageTitleSize
    property bool entered: false
    property real rise: 18
    spacing: 0

    Component.onCompleted: {
        rise = 0
        entered = true
    }
    opacity: entered ? 1 : 0
    transform: Translate { y: intro.rise }
    Behavior on opacity {
        enabled: InstallerAppearance.motionEnabled
        NumberAnimation { duration: 520; easing.type: Easing.OutCubic }
    }
    Behavior on rise {
        enabled: InstallerAppearance.motionEnabled
        NumberAnimation { duration: 560; easing.type: Easing.OutCubic }
    }

    Text {
        visible: intro.eyebrow.length > 0
        text: intro.eyebrow
        color: "#38bdf8"
        font.pixelSize: 12
        font.weight: Font.DemiBold
        font.letterSpacing: 2.4
    }
    Text {
        Layout.topMargin: intro.eyebrow.length ? 8 : 0
        Layout.fillWidth: true
        text: intro.title
        color: "#f8fafc"
        font.pixelSize: intro.titleSize
        font.weight: Font.Bold
        wrapMode: Text.WordWrap
    }
    Text {
        visible: intro.subtitle.length > 0
        Layout.topMargin: 10
        Layout.fillWidth: true
        Layout.bottomMargin: 6
        text: intro.subtitle
        color: "#94a3b8"
        font.pixelSize: 15
        wrapMode: Text.WordWrap
        lineHeight: 1.25
    }
}
