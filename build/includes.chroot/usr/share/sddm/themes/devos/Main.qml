import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Keep the greeter independent of effects modules and GPU compositing.
Pane {
    id: root
    width: 1366
    height: 768
    padding: 0
    font.family: "Inter"
    palette.text: "#f1f5f9"
    palette.windowText: "#f1f5f9"
    palette.buttonText: "#f1f5f9"
    palette.button: "#172337"
    palette.base: "#101b2d"
    palette.window: "#101b2d"
    palette.highlight: "#38bdf8"
    palette.highlightedText: "#07121f"
    property bool loggingIn: false
    property string failure: ""
    property var currentTime: new Date()
    readonly property bool compact: height < 700
    readonly property string userName: users.currentIndex >= 0 ? users.currentValue : manualUser.text
    readonly property string displayName: users.currentIndex >= 0 ? users.displayText : qsTr("Welcome back")

    background: Rectangle { color: "#080f1d" }
    Image {
        anchors.fill: parent
        source: config.background || "background.png"
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#99080f1d" }
            GradientStop { position: 1; color: "#ed080f1d" }
        }
    }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: root.currentTime = new Date()
    }
    RowLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 28
        spacing: 10
        Image {
            source: config.logo || "logo.png"
            Layout.preferredWidth: 30; Layout.preferredHeight: 30
            fillMode: Image.PreserveAspectFit
        }
        Text { text: "DevOS"; color: "#ffffff"; font.pixelSize: 20; font.weight: Font.DemiBold }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(400, root.width - 48)
        spacing: root.compact ? 14 : 24
        ColumnLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 4
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: Qt.formatTime(root.currentTime, config.clockFormat || "hh:mm")
                color: "#ffffff"; font.pixelSize: root.compact ? 40 : 64; font.weight: Font.Light
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: Qt.formatDate(root.currentTime, config.dateFormat || "dddd, MMMM d")
                color: "#cbd5e1"; font.pixelSize: 14
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: form.implicitHeight + (root.compact ? 32 : 48)
            radius: 24
            color: "#f2101b2d"
            border.color: "#3b4b63"
            ColumnLayout {
                id: form
                anchors.fill: parent
                anchors.margins: root.compact ? 16 : 24
                spacing: 14
                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    width: root.compact ? 48 : 64; height: width; radius: width / 2
                    color: "#1e3650"; border.color: "#7dd3fc"
                    Text {
                        anchors.centerIn: parent
                        text: root.displayName.charAt(0).toUpperCase()
                        color: "#bae6fd"; font.pixelSize: 26; font.weight: Font.DemiBold
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: root.displayName
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    color: "#ffffff"; font.pixelSize: 22; font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTr("Sign in to your workspace")
                    horizontalAlignment: Text.AlignHCenter
                    color: "#bccbde"; font.pixelSize: 14
                }
                ComboBox {
                    id: users
                    Layout.fillWidth: true
                    visible: count > 1
                    model: userModel
                    textRole: "realName"; valueRole: "name"
                    currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : (count ? 0 : -1)
                    displayText: currentIndex >= 0 ? (currentText || currentValue) : ""
                    enabled: !root.loggingIn
                    Accessible.name: qsTr("User account")
                    onActivated: {
                        password.clear()
                        reveal.checked = false
                        root.failure = ""
                        password.forceActiveFocus()
                    }
                }
                TextField {
                    id: manualUser
                    Layout.fillWidth: true
                    visible: users.count === 0
                    placeholderText: qsTr("Username")
                    enabled: !root.loggingIn
                    Accessible.name: qsTr("Username")
                }
                TextField {
                    id: password
                    Layout.fillWidth: true
                    implicitHeight: 48
                    placeholderText: config.promptText || qsTr("Password")
                    placeholderTextColor: "#a9bad0"
                    color: "#ffffff"
                    font.pixelSize: 16
                    leftPadding: 14
                    echoMode: reveal.checked ? TextInput.Normal : TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                    selectByMouse: true
                    enabled: !root.loggingIn
                    Accessible.name: qsTr("Password")
                    background: Rectangle {
                        radius: 12; color: "#0a1322"
                        border.color: password.activeFocus ? "#7dd3fc" : "#53647d"
                        border.width: password.activeFocus ? 2 : 1
                    }
                    onAccepted: root.doLogin()
                    onTextChanged: root.failure = ""
                }
                CheckBox {
                    id: reveal
                    text: qsTr("Show password")
                    enabled: !root.loggingIn
                }
                Text {
                    Layout.fillWidth: true
                    visible: keyboard.capsLock
                    text: qsTr("Caps Lock is on")
                    color: "#fcd34d"; font.pixelSize: 13
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.failure.length > 0
                    text: root.failure
                    color: "#fda4af"; font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    Accessible.role: Accessible.AlertMessage
                    Accessible.name: text
                }
                ActionButton {
                    Layout.fillWidth: true
                    primary: true
                    text: root.loggingIn ? qsTr("Signing in…") : qsTr("Sign in")
                    enabled: !root.loggingIn && root.userName.length > 0
                    onClicked: root.doLogin()
                }
            }
        }
    }
    RowLayout {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 24
        spacing: 12
        ComboBox {
            id: sessions
            implicitWidth: Math.min(240, root.width * 0.3)
            model: sessionModel; textRole: "name"
            currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
            Accessible.name: qsTr("Desktop session")
            enabled: !root.loggingIn
        }
        ComboBox {
            implicitWidth: 100
            model: keyboard.layouts; textRole: "shortName"
            currentIndex: keyboard.currentLayout
            visible: count > 1
            Accessible.name: qsTr("Keyboard layout")
            onActivated: keyboard.currentLayout = currentIndex
        }
    }
    RowLayout {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 24
        spacing: 8
        ActionButton { text: qsTr("Sleep"); visible: sddm.canSuspend && root.width >= 1000; onClicked: sddm.suspend() }
        ActionButton { text: qsTr("Restart"); visible: sddm.canReboot; onClicked: sddm.reboot() }
        ActionButton { text: qsTr("Shut down"); visible: sddm.canPowerOff; onClicked: sddm.powerOff() }
    }
    function doLogin() {
        if (loggingIn || !userName || sessions.currentIndex < 0) return
        failure = ""
        loggingIn = true
        sddm.login(userName, password.text, sessions.currentIndex)
    }
    Connections {
        target: sddm
        function onLoginFailed() {
            root.loggingIn = false
            password.clear()
            root.failure = qsTr("Sign-in failed. Check your password and try again.")
            password.forceActiveFocus()
        }
        function onLoginSucceeded() { password.clear() }
    }
    Component.onCompleted: {
        if (users.count === 0) manualUser.forceActiveFocus()
        else password.forceActiveFocus()
    }
}
