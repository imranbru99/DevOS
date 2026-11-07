import QtQuick
import QtQuick.Templates as T

T.Label {
    id: control
    color: control.enabled ? "#e8f1fb" : "#8496ad"
    linkColor: "#38bdf8"
    font.family: "Inter"
    font.pointSize: 11
    opacity: enabled ? 1 : 0.7
}
