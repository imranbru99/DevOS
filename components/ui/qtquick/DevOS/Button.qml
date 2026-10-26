import QtQuick
import QtQuick.Templates as T

T.Button {
    id: control
    implicitWidth: Math.max(112, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 46
    leftPadding: 20
    rightPadding: 20
    topPadding: 10
    bottomPadding: 10
    hoverEnabled: true
    font.family: "Inter"
    font.pointSize: 11
    font.weight: Font.DemiBold
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? "#edf7ff" : "#8191a8"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 11
        color: control.down ? "#145579" : control.hovered ? "#183e58" : "#14283f"
        border.color: control.visualFocus ? "#6dd9ff" : control.hovered ? "#38bdf8" : "#355574"
        border.width: control.visualFocus ? 2 : 1
        Behavior on color { ColorAnimation { duration: 100 } }
    }
}
