import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Keep the greeter independent of effects modules; motion uses plain transforms.
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

    Item {
        id: scenic
        anchors.fill: parent
        clip: true
        z: 0

        Image {
            id: backdrop
            width: parent.width * 1.18
            height: parent.height * 1.18
            // Centered manually so Ken Burns x/y motion is not fighting anchors.
            x: (parent.width - width) / 2
            y: (parent.height - height) / 2
            source: config.background || "background.png"
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            opacity: 0.92
            transformOrigin: Item.Center

            SequentialAnimation on scale {
                loops: Animation.Infinite
                NumberAnimation { from: 1.0; to: 1.08; duration: 18000; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 18000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation {
                    from: (scenic.width - backdrop.width) / 2 - scenic.width * 0.04
                    to: (scenic.width - backdrop.width) / 2 + scenic.width * 0.04
                    duration: 22000
                    easing.type: Easing.InOutSine
                }
                NumberAnimation {
                    to: (scenic.width - backdrop.width) / 2 - scenic.width * 0.04
                    duration: 22000
                    easing.type: Easing.InOutSine
                }
            }
            SequentialAnimation on y {
                loops: Animation.Infinite
                NumberAnimation {
                    from: (scenic.height - backdrop.height) / 2 + scenic.height * 0.02
                    to: (scenic.height - backdrop.height) / 2 - scenic.height * 0.03
                    duration: 26000
                    easing.type: Easing.InOutSine
                }
                NumberAnimation {
                    to: (scenic.height - backdrop.height) / 2 + scenic.height * 0.02
                    duration: 26000
                    easing.type: Easing.InOutSine
                }
            }
        }

        // Soft drifting color washes (no GraphicalEffects dependency).
        Rectangle {
            id: glowCyan
            width: Math.max(root.width, root.height) * 0.55
            height: width
            radius: width / 2
            color: "#3322d3ee"
            x: root.width * 0.55
            y: root.height * -0.12
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.42; duration: 16000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.62; duration: 16000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                loops: Animation.Infinite
                NumberAnimation { to: root.height * 0.08; duration: 14000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.height * -0.16; duration: 14000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { from: 0.35; to: 0.7; duration: 9000; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.35; duration: 9000; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {
            id: glowViolet
            width: Math.max(root.width, root.height) * 0.48
            height: width
            radius: width / 2
            color: "#338b5cf6"
            x: root.width * -0.18
            y: root.height * 0.45
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.05; duration: 19000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * -0.2; duration: 19000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on y {
                loops: Animation.Infinite
                NumberAnimation { to: root.height * 0.28; duration: 17000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.height * 0.55; duration: 17000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { from: 0.28; to: 0.62; duration: 11000; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.28; duration: 11000; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {
            id: glowBlue
            width: Math.max(root.width, root.height) * 0.36
            height: width
            radius: width / 2
            color: "#334facfe"
            x: root.width * 0.28
            y: root.height * 0.62
            SequentialAnimation on x {
                loops: Animation.Infinite
                NumberAnimation { to: root.width * 0.4; duration: 15000; easing.type: Easing.InOutSine }
                NumberAnimation { to: root.width * 0.2; duration: 15000; easing.type: Easing.InOutSine }
            }
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { from: 0.22; to: 0.55; duration: 10000; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.22; duration: 10000; easing.type: Easing.InOutSine }
            }
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: "#99080f1d" }
                GradientStop { position: 0.45; color: "#66080f1d" }
                GradientStop { position: 1; color: "#ed080f1d" }
            }
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
