/* DevOS "Choose your apps" page (packagechooserq@features).
   Like Windows' optional features, but at install time and fitted to this PC:
   "Recommended for this PC" (the default) ticks the everyday set minus apps
   this PC's RAM or disk can't run well (features-catalog.js recommended(),
   "Choose later" keeps only what is already on the PC.
   "Premium" ticks every app except Family Safety and the modesty filter.
   same rules as feature_catalog.recommended_ids). aimodel-hw.js holds the RAM
   and disk measured at live boot by devos-ai-hwprobe.
   The ticked ids go to global storage as "a,b,c"; preservefiles copies it into
   the new system and devos-features removes unticked built-ins during install
   and downloads the rest on the first online boot. */
import io.calamares.core 1.0 as Core
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

import "features-catalog.js" as Cat
import "aimodel-hw.js" as HW

Page {
    id: page
    background: Rectangle { color: "#0b0f1a" }

    readonly property real ramGb: HW.hw.ram_gb
    readonly property real diskGb: HW.hw.disk_gb
    property var picked: Cat.recommended(ramGb, diskGb)
    property string preset: "recommended"
    property string appliedKind: ""

    readonly property var icons: ({
        office: "✎", internet: "◎", chat: "✉", media: "♫", creative: "✦", games: "♞",
        developer: "</>", utilities: "⚙", security: "◈", language: "অ", compat: "⊞",
        devos: "✦", family: "☪"
    })

    function has(id) { return picked.indexOf(id) >= 0; }
    function feature(id) {
        for (var i = 0; i < Cat.data.features.length; i++)
            if (Cat.data.features[i].id === id) return Cat.data.features[i];
        return null;
    }
    function tooHeavy(f) { return page.ramGb + 0.5 < f.min_ram_gb; }
    function toggle(id, on) {
        var next = picked.filter(function (x) { return x !== id; });
        if (on) next.push(id);
        picked = next;
        preset = "";
    }
    function usePreset(p) {
        if (p === "later") {
            var keep = [];
            for (var k = 0; k < Cat.data.features.length; k++)
                if (Cat.data.features[k].preinstalled && !Cat.data.features[k].optin)
                    keep.push(Cat.data.features[k].id);
            picked = keep;
        } else if (p === "minimal") {
            var bare = [];
            for (var n = 0; n < Cat.data.features.length; n++)
                if (Cat.data.features[n].presets.indexOf("minimal") >= 0)
                    bare.push(Cat.data.features[n].id);
            picked = bare;
        } else if (p === "windows") {
            var win = [];
            for (var w = 0; w < Cat.data.features.length; w++)
                if (Cat.data.features[w].presets.indexOf("windows") >= 0)
                    win.push(Cat.data.features[w].id);
            picked = win;
        } else {
            var kind = (p === "recommended") ? "normal" : p;
            picked = Cat.userTypeIds(kind, ramGb, diskGb);
        }
        preset = p;
    }
    function userKind() {
        var keys = ["packagechooser_usertype", "usertype"];
        var raw = "";
        for (var i = 0; i < keys.length; i++) {
            if (Core.Global.contains(keys[i])) {
                raw = Core.Global.value(keys[i]);
                break;
            }
        }
        var text = (raw === undefined || raw === null) ? "" : String(raw);
        for (var k = 0; k < Cat.data.userTypes.length; k++)
            if (Cat.data.userTypes[k].id === text) return text;
        return "normal";
    }
    function applyUserType() {
        var kind = userKind();
        var chip = kind === "normal" ? "recommended" : kind;
        if (kind === appliedKind && preset === chip)
            return;
        usePreset(chip);
        appliedKind = kind;
    }
    function onActivate() { applyUserType(); }
    function inCategory(cat) {
        return Cat.data.features.filter(function (f) { return f.category === cat; });
    }
    function downloadMb() {
        var mb = 0;
        for (var i = 0; i < picked.length; i++) {
            var f = feature(picked[i]);
            if (f && !f.preinstalled) mb += f.size_mb;
        }
        return mb;
    }
    function removedCount() {
        var n = 0;
        for (var i = 0; i < Cat.data.features.length; i++) {
            var f = Cat.data.features[i];
            if (f.preinstalled && !f.optin && !has(f.id)) n++;
        }
        return n;
    }
    // ~14 GB for DevOS itself; unknown disk (0) hides the estimate.
    function freeAfterGb() { return diskGb > 0 ? diskGb - 14 - downloadMb() / 1024 : -1; }
    function human(mb) { return mb >= 1000 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB"; }
    function save() { config.packageChoice = picked.join(","); }

    onPickedChanged: save()
    Component.onCompleted: applyUserType()

    Flickable {
        id: flick
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: footer.top }
        contentHeight: form.implicitHeight + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: form
            x: Math.max(32, (flick.width - width) / 2)
            y: 32
            width: Math.min(flick.width - 64, 780)
            spacing: 8

            Text {
                text: "Choose your apps"
                color: "#f8fafc"
                font.pixelSize: 32
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: "#94a3b8"
                font.pixelSize: 15
                text: "These apps follow the kind of PC you just chose. Turn any of them off, or pick another category. "
                    + "After install you can still add or remove apps in DevOS Features, or ask DevOS AI, "
                    + "for example “install Zoom” or “uninstall Spotify”."
            }

            // ---- this PC
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 8
                implicitHeight: hwRow.implicitHeight + 28
                radius: 16
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#0c2338" }
                    GradientStop { position: 1.0; color: "#1a1336" }
                }
                border.color: "#1e3a5f"
                RowLayout {
                    id: hwRow
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 14
                    Rectangle {
                        implicitWidth: 44; implicitHeight: 44; radius: 12
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#38bdf8" }
                            GradientStop { position: 1.0; color: "#818cf8" }
                        }
                        Text { anchors.centerIn: parent; text: "⚡"; color: "white"; font.pixelSize: 22 }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: "Fitted to this PC"
                            color: "#f8fafc"; font.pixelSize: 16; font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: "#bae6fd"; font.pixelSize: 13
                            text: page.ramGb + " GB RAM" + (page.diskGb > 0 ? " · " + Math.round(page.diskGb) + " GB disk" : "")
                                + (HW.hw.cpu ? " · " + HW.hw.cpu : "")
                                + "\nNormal and Family leave heavy apps off. The other categories tick their full set."
                        }
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                spacing: 8
                Repeater {
                    model: Cat.data.presets
                    delegate: Rectangle {
                        readonly property bool on: page.preset === modelData.id
                        radius: 17
                        implicitWidth: label.implicitWidth + 30
                        implicitHeight: 34
                        color: on ? "#0c2338" : "#0f172a"
                        border.color: on ? "#38bdf8" : "#1e293b"
                        border.width: on ? 2 : 1
                        Text {
                            id: label
                            anchors.centerIn: parent
                            text: (modelData.id === "recommended" ? "★ " : modelData.id === "premium" ? "◆ " : modelData.id === "later" ? "… " : "") + modelData.name
                            color: on ? "#e0f2fe" : "#cbd5e1"
                            font.pixelSize: 14
                            font.weight: on ? Font.DemiBold : Font.Normal
                        }
                        MouseArea {
                            id: chipMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.usePreset(modelData.id)
                        }
                        ToolTip.visible: chipMouse.containsMouse
                        ToolTip.text: modelData.about
                    }
                }
            }

            Repeater {
                model: Cat.data.categories
                delegate: ColumnLayout {
                    readonly property var cat: modelData
                    Layout.fillWidth: true
                    spacing: 6
                    RowLayout {
                        Layout.topMargin: 18
                        spacing: 10
                        Rectangle {
                            implicitWidth: 30; implicitHeight: 30; radius: 9
                            color: "#13233d"
                            border.color: "#1e3a5f"
                            Text {
                                anchors.centerIn: parent
                                text: page.icons[cat.id] || "•"
                                color: "#7dd3fc"
                                font.pixelSize: cat.id === "developer" ? 11 : 15
                                font.weight: Font.DemiBold
                            }
                        }
                        Text {
                            text: cat.name
                            color: "#f8fafc"
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                    }
                    Repeater {
                        model: page.inCategory(cat.id)
                        delegate: Rectangle {
                            id: rowCard
                            readonly property var f: modelData
                            readonly property bool on: page.has(f.id)
                            readonly property bool heavy: page.tooHeavy(f)
                            Layout.fillWidth: true
                            implicitHeight: row.implicitHeight + 18
                            radius: 12
                            color: on ? "#0c1a2e" : (rowMouse.containsMouse ? "#111c31" : "#0f172a")
                            border.color: on ? "#2563eb" : "#1e293b"
                            Behavior on color { ColorAnimation { duration: 120 } }
                            MouseArea {
                                id: rowMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.toggle(rowCard.f.id, !rowCard.on)
                            }
                            RowLayout {
                                id: row
                                anchors.fill: parent
                                anchors.margins: 9
                                spacing: 12
                                Rectangle {
                                    implicitWidth: 22; implicitHeight: 22; radius: 6
                                    color: rowCard.on ? "#38bdf8" : "transparent"
                                    border.color: rowCard.on ? "#38bdf8" : "#475569"
                                    border.width: 2
                                    Text {
                                        anchors.centerIn: parent
                                        visible: rowCard.on
                                        text: "✓"; color: "#0b0f1a"; font.pixelSize: 14; font.weight: Font.Bold
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Text { text: rowCard.f.name; color: "#f8fafc"; font.pixelSize: 15 }
                                        Rectangle {
                                            visible: rowCard.f.windows !== ""
                                            radius: 6
                                            color: "#172554"
                                            implicitWidth: tag.implicitWidth + 12
                                            implicitHeight: tag.implicitHeight + 4
                                            Text { id: tag; anchors.centerIn: parent; text: "Like " + rowCard.f.windows; color: "#93c5fd"; font.pixelSize: 11 }
                                        }
                                        Rectangle {
                                            visible: rowCard.heavy
                                            radius: 6
                                            color: "#3b2506"
                                            implicitWidth: warn.implicitWidth + 12
                                            implicitHeight: warn.implicitHeight + 4
                                            Text { id: warn; anchors.centerIn: parent; text: "Needs " + rowCard.f.min_ram_gb + " GB RAM"; color: "#fbbf24"; font.pixelSize: 11 }
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                        color: "#94a3b8"
                                        font.pixelSize: 13
                                        text: rowCard.f.about
                                    }
                                }
                                Text {
                                    color: rowCard.f.optin ? (rowCard.on ? "#86efac" : "#64748b")
                                           : rowCard.f.preinstalled && !rowCard.on ? "#fca5a5" : "#cbd5e1"
                                    font.pixelSize: 12
                                    text: rowCard.f.optin ? (rowCard.on ? "Turns on" : "Off")
                                          : rowCard.f.preinstalled ? (rowCard.on ? "Included" : "Will be removed")
                                          : page.human(rowCard.f.size_mb)
                                }
                            }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 14
                wrapMode: Text.WordWrap
                color: "#64748b"
                font.pixelSize: 12
                visible: page.has("msfonts")
                text: "Microsoft core fonts are downloaded from Microsoft; keeping them ticked accepts Microsoft's font licence."
            }
        }
    }

    // ---- summary bar, always visible
    Rectangle {
        id: footer
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 58
        color: "#0d1424"
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: 1; color: "#1e293b" }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 32
            anchors.rightMargin: 32
            spacing: 22
            Text {
                text: page.picked.length + " apps & features"
                color: "#f8fafc"; font.pixelSize: 14; font.weight: Font.DemiBold
            }
            Text {
                text: "Download after install: " + (page.downloadMb() > 0 ? page.human(page.downloadMb()) : "nothing")
                color: "#cbd5e1"; font.pixelSize: 13
            }
            Text {
                visible: page.freeAfterGb() >= 0
                text: "≈ " + Math.max(0, Math.round(page.freeAfterGb())) + " GB free afterwards"
                color: page.freeAfterGb() < 10 ? "#fbbf24" : "#86efac"
                font.pixelSize: 13
            }
            Text {
                visible: page.removedCount() > 0
                text: page.removedCount() + " built-in left out"
                color: "#fca5a5"; font.pixelSize: 13
            }
            Item { Layout.fillWidth: true }
        }
    }
}
