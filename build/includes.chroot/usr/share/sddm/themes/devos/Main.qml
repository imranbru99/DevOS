import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtGraphicalEffects 1.15

Item {
    id: root
    width: 1366
    height: 768

    property string currentUserName: (userModel && userModel.lastUser) ? userModel.lastUser : "devos"
    property string currentRealName: currentUserName
    property int selectedSessionIndex: (sessionModel && sessionModel.lastIndex >= 0) ? sessionModel.lastIndex : 0
    property bool showPassword: false
    property bool loggingIn: false
    property var currentTime: new Date()

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: root.currentTime = new Date()
    }

    // 1. Wallpaper Background
    Image {
        id: bgImage
        anchors.fill: parent
        source: config.background || "background.png"
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true

        // Soft dark gradient overlay for contrast and depth
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0.04, 0.06, 0.10, 0.45) }
                GradientStop { position: 0.5; color: Qt.rgba(0.04, 0.06, 0.10, 0.55) }
                GradientStop { position: 1.0; color: Qt.rgba(0.02, 0.03, 0.06, 0.75) }
            }
        }
    }

    // 2. Header Bar (Top)
    RowLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 16

        // DevOS Branding Pill
        Rectangle {
            height: 38
            width: brandRow.width + 24
            radius: 19
            color: Qt.rgba(0.08, 0.12, 0.20, 0.60)
            border.color: Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            RowLayout {
                id: brandRow
                anchors.centerIn: parent
                spacing: 8

                Image {
                    source: config.logo || "logo.png"
                    width: 22
                    height: 22
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                }

                Text {
                    text: "DevOS"
                    color: "#ffffff"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    font.family: config.fontFamily || "sans-serif"
                }
            }
        }

        Item { Layout.fillWidth: true }

        // Session Selector Pill (if multiple sessions exist)
        Rectangle {
            id: sessionPill
            visible: sessionModel && sessionModel.count > 1
            height: 38
            width: sessionText.width + 36
            radius: 19
            color: sessionMouse.containsMouse ? Qt.rgba(0.12, 0.18, 0.30, 0.85) : Qt.rgba(0.08, 0.12, 0.20, 0.60)
            border.color: sessionMouse.containsMouse ? "#38bdf8" : Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            Text {
                id: sessionText
                anchors.centerIn: parent
                text: (sessionModel && sessionModel.count > 0 && root.selectedSessionIndex < sessionModel.count)
                      ? sessionModel.data(sessionModel.index(root.selectedSessionIndex, 0), Qt.DisplayRole) || "Plasma"
                      : "Plasma"
                color: "#e2e8f0"
                font.pixelSize: 13
                font.family: config.fontFamily || "sans-serif"
            }

            MouseArea {
                id: sessionMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (sessionModel && sessionModel.count > 1) {
                        root.selectedSessionIndex = (root.selectedSessionIndex + 1) % sessionModel.count
                    }
                }
            }
        }

        // Keyboard Layout Pill
        Rectangle {
            id: kbdPill
            visible: keyboard && keyboard.layouts && keyboard.layouts.length > 0
            height: 38
            width: kbdText.width + 24
            radius: 19
            color: kbdMouse.containsMouse ? Qt.rgba(0.12, 0.18, 0.30, 0.85) : Qt.rgba(0.08, 0.12, 0.20, 0.60)
            border.color: kbdMouse.containsMouse ? "#38bdf8" : Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            Text {
                id: kbdText
                anchors.centerIn: parent
                text: (keyboard && keyboard.layouts && keyboard.currentLayout < keyboard.layouts.length)
                      ? (keyboard.layouts[keyboard.currentLayout].shortName || keyboard.layouts[keyboard.currentLayout].name || "EN")
                      : "EN"
                color: "#e2e8f0"
                font.pixelSize: 13
                font.weight: Font.Medium
                font.family: config.fontFamily || "sans-serif"
            }

            MouseArea {
                id: kbdMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (keyboard && keyboard.layouts && keyboard.layouts.length > 1) {
                        keyboard.currentLayout = (keyboard.currentLayout + 1) % keyboard.layouts.length
                    }
                }
            }
        }
    }

    // 3. Center Section: Clock + Login Card
    ColumnLayout {
        id: centerColumn
        anchors.centerIn: parent
        spacing: 28

        // Modern Clock & Date
        ColumnLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 4

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: Qt.formatTime(root.currentTime, config.clockFormat || "hh:mm")
                color: "#ffffff"
                font.pixelSize: 64
                font.weight: Font.Light
                font.family: config.fontFamily || "sans-serif"
                style: Text.Raised
                styleColor: Qt.rgba(0, 0, 0, 0.35)
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: Qt.formatDate(root.currentTime, config.dateFormat || "dddd, MMMM d")
                color: "#94a3b8"
                font.pixelSize: 16
                font.weight: Font.Normal
                font.family: config.fontFamily || "sans-serif"
                style: Text.Raised
                styleColor: Qt.rgba(0, 0, 0, 0.35)
            }
        }

        // Modern Glassmorphism Login Card
        Item {
            id: cardWrapper
            width: 370
            height: loginCard.height
            Layout.alignment: Qt.AlignHCenter

            Rectangle {
                id: loginCard
                width: 370
                height: cardContent.height + 48
                radius: 24
                color: Qt.rgba(0.08, 0.10, 0.16, 0.78)
                border.color: Qt.rgba(1, 1, 1, 0.14)
                border.width: 1

                // Subtle inner highlight line
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    radius: 24
                    color: Qt.rgba(1, 1, 1, 0.25)
                }

                // Shake animation on wrong password
                SequentialAnimation {
                    id: shakeAnimation
                    loops: 1
                    NumberAnimation { target: loginCard; property: "x"; to: -14; duration: 45; easing.type: Easing.InOutQuad }
                    NumberAnimation { target: loginCard; property: "x"; to: 14; duration: 45; easing.type: Easing.InOutQuad }
                    NumberAnimation { target: loginCard; property: "x"; to: -10; duration: 45; easing.type: Easing.InOutQuad }
                    NumberAnimation { target: loginCard; property: "x"; to: 10; duration: 45; easing.type: Easing.InOutQuad }
                    NumberAnimation { target: loginCard; property: "x"; to: -4; duration: 45; easing.type: Easing.InOutQuad }
                    NumberAnimation { target: loginCard; property: "x"; to: 0; duration: 45; easing.type: Easing.InOutQuad }
                }

                ColumnLayout {
                    id: cardContent
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.topMargin: 24
                    anchors.leftMargin: 28
                    anchors.rightMargin: 28
                    spacing: 14

                    // User Avatar with Gradient Glow Ring
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 82
                        height: 82
                        radius: 41
                        color: "transparent"
                        border.color: "#38bdf8"
                        border.width: 2.5

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 4
                            radius: 37
                            color: Qt.rgba(0.12, 0.16, 0.26, 0.90)

                            Text {
                                anchors.centerIn: parent
                                text: root.currentUserName.length > 0 ? root.currentUserName.charAt(0).toUpperCase() : "U"
                                color: "#38bdf8"
                                font.pixelSize: 32
                                font.weight: Font.Bold
                                font.family: config.fontFamily || "sans-serif"
                            }
                        }
                    }

                    // User Name & Subtitle
                    ColumnLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 2

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: root.currentRealName
                            color: "#ffffff"
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.family: config.fontFamily || "sans-serif"
                        }

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: config.welcomeText || "Welcome back"
                            color: "#94a3b8"
                            font.pixelSize: 12
                            font.family: config.fontFamily || "sans-serif"
                        }
                    }

                    Item { height: 4; Layout.fillWidth: true }

                    // Password Input Pill Container
                    Rectangle {
                        id: passwordBox
                        Layout.fillWidth: true
                        height: 48
                        radius: 24
                        color: Qt.rgba(1, 1, 1, 0.08)
                        border.color: passwordInput.activeFocus ? "#38bdf8" : Qt.rgba(1, 1, 1, 0.16)
                        border.width: passwordInput.activeFocus ? 2 : 1

                        Behavior on border.color {
                            ColorAnimation { duration: 150 }
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 6
                            spacing: 8

                            // Lock Glyph
                            Text {
                                text: "🔒"
                                font.pixelSize: 14
                                opacity: 0.65
                            }

                            // Password Text Input
                            TextInput {
                                id: passwordInput
                                Layout.fillWidth: true
                                echoMode: root.showPassword ? TextInput.Normal : TextInput.Password
                                passwordCharacter: "•"
                                color: "#ffffff"
                                font.pixelSize: 15
                                font.family: config.fontFamily || "sans-serif"
                                focus: true
                                selectByMouse: true
                                clip: true

                                Text {
                                    anchors.fill: parent
                                    text: config.promptText || "Password"
                                    color: "#64748b"
                                    font.pixelSize: 15
                                    font.family: config.fontFamily || "sans-serif"
                                    visible: !passwordInput.text && !passwordInput.inputMethodComposing
                                }

                                onAccepted: root.doLogin()
                                onTextChanged: {
                                    if (errorMessage.text.length > 0) {
                                        errorMessage.text = ""
                                    }
                                }
                            }

                            // Show/Hide Password Eye Button
                            Rectangle {
                                width: 28
                                height: 28
                                radius: 14
                                color: eyeMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent"
                                visible: passwordInput.text.length > 0

                                Text {
                                    anchors.centerIn: parent
                                    text: root.showPassword ? "👁" : "👁‍🗨"
                                    font.pixelSize: 13
                                    opacity: 0.75
                                }

                                MouseArea {
                                    id: eyeMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.showPassword = !root.showPassword
                                }
                            }

                            // Submit Login Button (illuminates when password entered)
                            Rectangle {
                                id: submitBtn
                                width: 36
                                height: 36
                                radius: 18
                                color: passwordInput.text.length > 0 ? (submitMouse.containsMouse ? "#0284c7" : "#38bdf8") : Qt.rgba(1, 1, 1, 0.10)
                                opacity: root.loggingIn ? 0.5 : 1.0

                                Behavior on color {
                                    ColorAnimation { duration: 150 }
                                }

                                Text {
                                    anchors.centerIn: parent
                                    text: root.loggingIn ? "…" : "➔"
                                    color: passwordInput.text.length > 0 ? "#0f172a" : "#64748b"
                                    font.pixelSize: 16
                                    font.weight: Font.Bold
                                }

                                MouseArea {
                                    id: submitMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: passwordInput.text.length > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: root.doLogin()
                                }
                            }
                        }
                    }

                    // Error Message Display
                    Text {
                        id: errorMessage
                        Layout.alignment: Qt.AlignHCenter
                        text: ""
                        color: "#f87171"
                        font.pixelSize: 12
                        font.family: config.fontFamily || "sans-serif"
                        font.weight: Font.Medium
                        visible: text.length > 0
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    // 4. Footer Bar (Bottom Power Actions)
    RowLayout {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 12

        // Sleep / Suspend Button
        Rectangle {
            id: sleepBtn
            visible: sddm ? sddm.canSuspend : true
            width: 42
            height: 42
            radius: 21
            color: sleepMouse.containsMouse ? Qt.rgba(0.12, 0.18, 0.30, 0.85) : Qt.rgba(0.08, 0.12, 0.20, 0.60)
            border.color: sleepMouse.containsMouse ? "#38bdf8" : Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            Text {
                anchors.centerIn: parent
                text: "🌙"
                font.pixelSize: 15
            }

            ToolTip.visible: sleepMouse.containsMouse
            ToolTip.text: "Sleep"

            MouseArea {
                id: sleepMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (sddm) sddm.suspend()
            }
        }

        // Reboot Button
        Rectangle {
            id: rebootBtn
            visible: sddm ? sddm.canReboot : true
            width: 42
            height: 42
            radius: 21
            color: rebootMouse.containsMouse ? Qt.rgba(0.12, 0.18, 0.30, 0.85) : Qt.rgba(0.08, 0.12, 0.20, 0.60)
            border.color: rebootMouse.containsMouse ? "#38bdf8" : Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            Text {
                anchors.centerIn: parent
                text: "🔄"
                font.pixelSize: 15
            }

            ToolTip.visible: rebootMouse.containsMouse
            ToolTip.text: "Restart"

            MouseArea {
                id: rebootMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (sddm) sddm.reboot()
            }
        }

        // Shut Down Button
        Rectangle {
            id: powerBtn
            visible: sddm ? sddm.canPowerOff : true
            width: 42
            height: 42
            radius: 21
            color: powerMouse.containsMouse ? Qt.rgba(0.80, 0.20, 0.20, 0.75) : Qt.rgba(0.08, 0.12, 0.20, 0.60)
            border.color: powerMouse.containsMouse ? "#ef4444" : Qt.rgba(1, 1, 1, 0.12)
            border.width: 1

            Text {
                anchors.centerIn: parent
                text: "⏻"
                color: powerMouse.containsMouse ? "#ffffff" : "#f87171"
                font.pixelSize: 16
                font.weight: Font.Bold
            }

            ToolTip.visible: powerMouse.containsMouse
            ToolTip.text: "Shut Down"

            MouseArea {
                id: powerMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (sddm) sddm.powerOff()
            }
        }
    }

    // Login Action Handler
    function doLogin() {
        if (passwordInput.text.length === 0 || root.loggingIn) return;
        errorMessage.text = "";
        root.loggingIn = true;
        if (sddm) {
            sddm.login(root.currentUserName, passwordInput.text, root.selectedSessionIndex);
        }
    }

    // SDDM Signal Connections
    Connections {
        target: sddm
        ignoreUnknownSignals: true
        function onLoginFailed() {
            root.loggingIn = false;
            errorMessage.text = qsTr("Incorrect password. Please try again.");
            shakeAnimation.start();
            passwordInput.selectAll();
            passwordInput.forceActiveFocus();
        }
        function onLoginSucceeded() {
            errorMessage.text = "";
        }
    }

    Component.onCompleted: {
        passwordInput.forceActiveFocus()
    }
}
