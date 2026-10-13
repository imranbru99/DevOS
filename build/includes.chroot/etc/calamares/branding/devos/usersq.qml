/* DevOS account page (usersq module). Everything is pre-filled, so Next
   works straight away: no name or password is required. A password can be
   added here; without one DevOS signs in automatically. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Page {
    id: usersPage
    background: Rectangle { color: "#0b0f1a" }

    component Field: TextField {
        id: field
        Layout.fillWidth: true
        Layout.preferredHeight: 46
        font.pixelSize: 15
        color: "#f8fafc"
        placeholderTextColor: "#64748b"
        leftPadding: 14
        background: Rectangle {
            radius: 12
            color: field.enabled ? "#0f172a" : "#0b1120"
            border.color: field.activeFocus ? "#38bdf8"
                          : (field.text.length && !field.acceptableInput) ? "#ef4444" : "#2a3550"
        }
    }

    component Caption: Text {
        color: "#94a3b8"
        font.pixelSize: 13
        Layout.topMargin: 14
    }

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 80
        clip: true

        ColumnLayout {
            id: form
            x: Math.max(40, (parent.width - width) / 2)
            y: 40
            width: Math.min(usersPage.width - 80, 620)
            spacing: 6

            Text {
                text: "Your account"
                color: "#f8fafc"
                font.pixelSize: 32
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "Optional. Everything is filled in already, so you can just press Next. "
                    + "Add a password to protect your files, or leave it empty and DevOS starts without asking."
                color: "#94a3b8"
                font.pixelSize: 15
                lineHeight: 1.2
                Layout.bottomMargin: 10
            }

            Caption { text: "Your name" }
            Field {
                id: fullName
                text: config.fullName
                placeholderText: "DevOS User"
                onTextChanged: config.setFullName(text)
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Caption { text: "Sign-in name" }
                    Field {
                        id: login
                        text: config.loginName
                        validator: RegularExpressionValidator { regularExpression: /[a-z_][a-z0-9_-]*[$]?/ }
                        onTextChanged: if (acceptableInput && text !== "root") config.setLoginName(text)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Caption { text: "Computer name" }
                    Field {
                        id: hostname
                        text: config.hostname
                        validator: RegularExpressionValidator { regularExpression: /[a-zA-Z0-9][-a-zA-Z0-9_]+/ }
                        onTextChanged: if (acceptableInput) config.setHostName(text)
                    }
                }
            }

            Caption { text: "Password (optional)" }
            RowLayout {
                Layout.fillWidth: true
                spacing: 14
                Field {
                    id: password
                    echoMode: TextInput.Password
                    placeholderText: "No password"
                    text: config.userPassword
                    onTextChanged: config.setUserPassword(text)
                }
                Field {
                    id: confirm
                    echoMode: TextInput.Password
                    placeholderText: "Repeat password"
                    enabled: password.text.length > 0
                    text: config.userPasswordSecondary
                    onTextChanged: config.setUserPasswordSecondary(text)
                }
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font.pixelSize: 13
                visible: password.text.length > 0
                color: config.userPasswordValidity ? "#4ade80" : "#fbbf24"
                text: config.userPasswordValidity
                      ? (password.text === confirm.text ? "Passwords match." : "Repeat the password to confirm it.")
                      : config.userPasswordMessage
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 18
                implicitHeight: autoRow.implicitHeight + 28
                radius: 14
                color: "#0f172a"
                border.color: "#1e293b"
                RowLayout {
                    id: autoRow
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 12
                    CheckBox {
                        id: auto
                        checked: config.doAutoLogin || password.text.length === 0
                        enabled: password.text.length > 0
                        onCheckedChanged: config.setAutoLogin(checked)
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#e2e8f0"
                        font.pixelSize: 14
                        text: password.text.length > 0
                              ? "Sign in automatically when the computer starts"
                              : "No password: DevOS opens the desktop automatically. You can add a password later in Settings."
                    }
                }
            }
        }
    }
}
