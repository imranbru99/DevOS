import QtQuick
import QtQuick.Templates as T

T.ToolButton {
    id: control

    // Kirigami PasswordField / ActionTextField uses IconOnly inline actions.
    // Showing the full "Show Password" label here overflows the field.
    readonly property bool iconOnly: control.display === T.AbstractButton.IconOnly
            || (control.display !== T.AbstractButton.TextOnly
                && control.icon.name !== ""
                && control.text === "" )

    implicitWidth: iconOnly
                   ? Math.max(36, implicitHeight)
                   : Math.max(40, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(36, contentItem.implicitHeight + topPadding + bottomPadding)

    padding: iconOnly ? 6 : 8
    leftPadding: padding
    rightPadding: padding
    topPadding: padding
    bottomPadding: padding
    spacing: 6
    hoverEnabled: true
    flat: true
    font.family: "Inter"
    font.pointSize: 11

    contentItem: Item {
        implicitWidth: {
            if (control.iconOnly)
                return iconLabel.implicitWidth
            const tw = label.implicitWidth
            const iw = (control.icon.name || control.icon.source.toString()) ? iconLabel.implicitWidth : 0
            if (control.display === T.AbstractButton.TextOnly || iw === 0)
                return tw
            if (control.display === T.AbstractButton.TextUnderIcon)
                return Math.max(tw, iw)
            return iw + control.spacing + tw
        }
        implicitHeight: {
            if (control.iconOnly)
                return iconLabel.implicitHeight
            const th = label.implicitHeight
            const ih = (control.icon.name || control.icon.source.toString()) ? iconLabel.implicitHeight : 0
            if (control.display === T.AbstractButton.TextOnly || ih === 0)
                return th
            if (control.display === T.AbstractButton.TextUnderIcon)
                return ih + control.spacing + th
            return Math.max(th, ih)
        }

        Image {
            id: iconLabel
            anchors.centerIn: control.iconOnly ? parent : undefined
            anchors.verticalCenter: !control.iconOnly
                                    && control.display !== T.AbstractButton.TextUnderIcon
                                    ? parent.verticalCenter : undefined
            anchors.left: !control.iconOnly
                          && control.display === T.AbstractButton.TextBesideIcon
                          ? parent.left : undefined
            anchors.horizontalCenter: control.display === T.AbstractButton.TextUnderIcon
                                      ? parent.horizontalCenter : undefined
            anchors.top: control.display === T.AbstractButton.TextUnderIcon
                         ? parent.top : undefined
            width: 18
            height: 18
            fillMode: Image.PreserveAspectFit
            visible: (control.icon.name !== "" || control.icon.source.toString() !== "")
                     && control.display !== T.AbstractButton.TextOnly
            source: {
                if (control.icon.source.toString() !== "")
                    return control.icon.source
                if (control.icon.name !== "")
                    return "image://icon/" + control.icon.name
                return ""
            }
            opacity: control.enabled ? 1.0 : 0.45
        }

        Text {
            id: label
            anchors.verticalCenter: control.display !== T.AbstractButton.TextUnderIcon
                                    ? parent.verticalCenter : undefined
            anchors.left: control.display === T.AbstractButton.TextBesideIcon
                          && iconLabel.visible ? iconLabel.right : parent.left
            anchors.leftMargin: control.display === T.AbstractButton.TextBesideIcon
                                && iconLabel.visible ? control.spacing : 0
            anchors.horizontalCenter: control.display === T.AbstractButton.TextUnderIcon
                                      || control.display === T.AbstractButton.TextOnly
                                      || !iconLabel.visible
                                      ? parent.horizontalCenter : undefined
            anchors.bottom: control.display === T.AbstractButton.TextUnderIcon
                            ? parent.bottom : undefined
            anchors.right: control.display === T.AbstractButton.TextBesideIcon
                           ? parent.right : undefined
            text: control.text
            font: control.font
            color: control.enabled ? "#d7e7f8" : "#7f90a8"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            visible: !control.iconOnly && control.display !== T.AbstractButton.IconOnly
                     && control.text.length > 0
        }
    }

    background: Rectangle {
        radius: 10
        color: control.down ? "#1a3a55"
             : control.hovered || control.visualFocus ? "#152f46"
             : "transparent"
        border.color: control.visualFocus ? "#38bdf8" : "transparent"
        border.width: control.visualFocus ? 2 : 0
        Behavior on color { ColorAnimation { duration: 100 } }
    }

    // Keep the full label available for tooltips / accessibility when icon-only.
    Accessible.name: control.text
}
