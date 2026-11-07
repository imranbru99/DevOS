import QtQuick
import QtQuick.Templates as T

T.Button {
    id: control
    implicitWidth: Math.max(120, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 48
    leftPadding: 22
    rightPadding: 22
    topPadding: 12
    bottomPadding: 12
    hoverEnabled: true
    font.family: "Inter"
    font.pointSize: 11
    font.weight: Font.DemiBold

    readonly property bool primary: control.highlighted || control.checked

    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? "#f2f8ff" : "#7f90a8"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 12
        gradient: Gradient {
            GradientStop {
                position: 0
                color: control.down ? "#0f4f7a"
                     : control.hovered ? "#1a5f8c"
                     : (control.primary ? "#1670a8" : "#17334d")
            }
            GradientStop {
                position: 1
                color: control.down ? "#0c3d5e"
                     : control.hovered ? "#154e73"
                     : (control.primary ? "#0f5a8a" : "#12283d")
            }
        }
        border.color: control.visualFocus ? "#6dd9ff"
                     : control.hovered ? "#4cc4f0"
                     : (control.primary ? "#38bdf8" : "#3a5878")
        border.width: control.visualFocus ? 2 : 1
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
