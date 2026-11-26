/*
    SPDX-FileCopyrightText: 2011 Martin *Gräßlin <mgraesslin@kde.org>
    SPDX-FileCopyrightText: 2012 Gregor Taetzner <gregor@freenet.de>
    SPDX-FileCopyrightText: 2014 Sebastian Kügler <sebas@kde.org>
    SPDX-FileCopyrightText: 2015-2018 Eike Hein <hein@kde.org>
    SPDX-FileCopyrightText: 2021 Mikel Johnson <mikel5764@gmail.com>
    SPDX-FileCopyrightText: 2021 Noah Davis <noahadvs@gmail.com>
    SPDX-FileCopyrightText: 2022 Nate Graham <nate@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
 */

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC3
import org.kde.kirigami as Kirigami

AbstractKickoffItemDelegate {
    id: root

    leftPadding: KickoffSingleton.listItemMetrics.margins.left
    rightPadding: KickoffSingleton.listItemMetrics.margins.right
    topPadding: Kirigami.Units.smallSpacing * 2
    bottomPadding: Kirigami.Units.smallSpacing * 2

    // devos-keep-category-while-scrolling
    readonly property bool devosCompact: GridView.view ? GridView.view.devosCompact === true : false

    icon.width: devosCompact ? Kirigami.Units.iconSizes.smallMedium : Kirigami.Units.iconSizes.huge
    icon.height: icon.width

    labelTruncated: label.truncated
    descriptionVisible: false

    dragIconItem: iconItem

    contentItem: ColumnLayout {
        spacing: root.spacing

        Kirigami.Icon {
            id: iconItem
            implicitWidth: root.icon.width
            implicitHeight: root.icon.height
            Layout.alignment: Qt.AlignHCenter | Qt.AlignBottom

            animated: false
            selected: root.iconAndLabelsShouldlookSelected
            source: root.decoration || root.icon.name || root.icon.source

            Loader {
                anchors {
                    right: parent.right
                    rightMargin: -root.rightPadding
                    top: parent.top
                }
                visible: active
                active: root.model?.isNewlyInstalled ?? false

                sourceComponent: Badge {
                    text: i18nc("@label Newly installed app, badge, keep short", "New!") // qmllint disable unqualified
                    Accessible.name: i18nc("@label Accessible name for badge", "Newly installed application") // qmllint disable unqualified
                }
            }
        }

        PC3.Label {
            id: label
            Layout.alignment: Qt.AlignHCenter | Qt.AlignTop
            Layout.fillWidth: true
            Layout.preferredHeight: root.devosCompact || label.lineCount > 1 ? label.implicitHeight : label.implicitHeight * 2

            text: root.text
            textFormat: Text.PlainText
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignTop
            maximumLineCount: root.devosCompact ? 1 : 2
            wrapMode: Text.Wrap
            color: root.iconAndLabelsShouldlookSelected ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
        }
    }
}
