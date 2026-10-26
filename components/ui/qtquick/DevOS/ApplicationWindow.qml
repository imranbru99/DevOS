import QtQuick
import QtQuick.Templates as T
import org.kde.kirigami as Kirigami

T.ApplicationWindow {
    id: control
    font.family: "Inter"
    font.pointSize: 11
    palette.window: "#101c30"
    palette.windowText: "#edf7ff"
    palette.text: "#edf7ff"
    palette.base: "#0b1425"
    palette.button: "#14283f"
    palette.buttonText: "#edf7ff"
    palette.highlight: "#38bdf8"
    palette.highlightedText: "#07121e"
    Kirigami.Theme.inherit: false
    Kirigami.Theme.backgroundColor: "#101c30"
    Kirigami.Theme.textColor: "#edf7ff"
    Kirigami.Theme.disabledTextColor: "#9aacc4"
    Kirigami.Theme.highlightColor: "#38bdf8"
    background: Rectangle {
        gradient: Gradient {
            GradientStop { position: 0; color: "#101c30" }
            GradientStop { position: 1; color: "#0b1425" }
        }
        Rectangle { width: parent.width; height: 2; color: "#38bdf8"; opacity: 0.65 }
    }
}
