import QtQuick
import QtQuick.Templates as T

T.TextField {
    id: control
    implicitWidth: 320
    implicitHeight: 50
    leftPadding: 14
    rightPadding: 14
    topPadding: 12
    bottomPadding: 12
    font.family: "Inter"
    font.pointSize: 11
    color: "#edf7ff"
    placeholderTextColor: "#9aacc4"
    selectionColor: "#1676a5"
    selectedTextColor: "#ffffff"
    background: Rectangle {
        radius: 11
        color: "#0b1425"
        border.color: control.activeFocus ? "#38bdf8" : "#38506e"
        border.width: control.activeFocus ? 2 : 1
    }
    Text {
        x: control.leftPadding
        y: control.topPadding
        width: control.availableWidth
        height: control.availableHeight
        text: control.placeholderText
        font: control.font
        color: control.placeholderTextColor
        visible: !control.length && !control.preeditText && (!control.activeFocus || control.horizontalAlignment !== Qt.AlignHCenter)
        verticalAlignment: control.verticalAlignment
        elide: Text.ElideRight
        renderType: control.renderType
    }
}
