import QtQuick
import QtQuick.Templates as T

T.TextField {
    id: control
    implicitWidth: 340
    implicitHeight: 52
    // Keep room for Kirigami PasswordField's trailing IconOnly reveal button.
    // ActionTextField overrides padding when actions are present; these are the baseline.
    leftPadding: 16
    rightPadding: (echoMode === TextInput.Password || echoMode === TextInput.PasswordEchoOnEdit)
                  ? 44 : 16
    topPadding: 14
    bottomPadding: 14
    font.family: "Inter"
    font.pointSize: 12
    color: "#f2f8ff"
    placeholderTextColor: "#8fa3bc"
    selectionColor: "#1676a5"
    selectedTextColor: "#ffffff"
    passwordCharacter: "●"
    clip: true

    background: Rectangle {
        radius: 12
        color: "#070e1a"
        border.color: control.activeFocus ? "#38bdf8" : control.hovered ? "#4a6a8c" : "#2f4663"
        border.width: control.activeFocus ? 2 : 1
        // Soft inner glow on focus
        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: parent.radius - 1
            color: "transparent"
            border.width: control.activeFocus ? 1 : 0
            border.color: "#203850"
            opacity: 0.9
        }
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    Text {
        x: control.leftPadding
        y: control.topPadding
        width: control.availableWidth
        height: control.availableHeight
        text: control.placeholderText
        font: control.font
        color: control.placeholderTextColor
        visible: !control.length && !control.preeditText
                 && (!control.activeFocus || control.horizontalAlignment !== Qt.AlignHCenter)
        verticalAlignment: control.verticalAlignment
        elide: Text.ElideRight
        renderType: control.renderType
        clip: true
    }
}
