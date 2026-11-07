import QtQuick
import QtQuick.Templates as T
import org.kde.kirigami as Kirigami

T.ApplicationWindow {
    id: control
    font.family: "Inter"
    font.pointSize: 11
    palette.window: "#0d1829"
    palette.windowText: "#f2f8ff"
    palette.text: "#f2f8ff"
    palette.base: "#070e1a"
    palette.button: "#17334d"
    palette.buttonText: "#f2f8ff"
    palette.highlight: "#38bdf8"
    palette.highlightedText: "#041018"
    palette.mid: "#1a2f46"
    palette.dark: "#0a1320"
    palette.light: "#243c58"
    Kirigami.Theme.inherit: false
    Kirigami.Theme.colorSet: Kirigami.Theme.Window
    Kirigami.Theme.backgroundColor: "#0d1829"
    Kirigami.Theme.alternateBackgroundColor: "#121f33"
    Kirigami.Theme.textColor: "#f2f8ff"
    Kirigami.Theme.disabledTextColor: "#8496ad"
    Kirigami.Theme.highlightColor: "#38bdf8"
    Kirigami.Theme.highlightedTextColor: "#041018"
    Kirigami.Theme.activeTextColor: "#6dd9ff"
    Kirigami.Theme.linkColor: "#38bdf8"
    Kirigami.Theme.positiveTextColor: "#4ade80"
    Kirigami.Theme.neutralTextColor: "#fbbf24"
    Kirigami.Theme.negativeTextColor: "#f87171"
    background: Rectangle {
        gradient: Gradient {
            GradientStop { position: 0; color: "#121f33" }
            GradientStop { position: 1; color: "#0a1422" }
        }
        Rectangle {
            width: parent.width
            height: 3
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#0ea5e9" }
                GradientStop { position: 0.5; color: "#38bdf8" }
                GradientStop { position: 1; color: "#22d3ee" }
            }
            opacity: 0.85
        }
    }
}
