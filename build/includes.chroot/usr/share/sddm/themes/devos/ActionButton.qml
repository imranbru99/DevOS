import QtQuick 2.15
import QtQuick.Controls 2.15

Button {
    id: control
    property bool primary: false
    implicitHeight: 44
    implicitWidth: Math.max(88, contentItem.implicitWidth + 32)
    hoverEnabled: true
    font.family: "Inter"
    font.pixelSize: 14
    Accessible.name: text
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.primary ? "#07121f" : "#e2e8f0"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 12
        color: control.primary ? (control.down ? "#38bdf8" : "#7dd3fc")
                               : (control.hovered || control.down ? "#29374d" : "#172337")
        border.color: control.activeFocus ? "#7dd3fc" : "#36465e"
        border.width: control.activeFocus ? 2 : 1
        opacity: control.enabled ? 1 : 0.5
    }
}
