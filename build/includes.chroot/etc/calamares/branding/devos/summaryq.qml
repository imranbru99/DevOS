/* Premium install preview — motion backdrop + clear, modern summary cards.
   Replaces the stock QWidget Summary so text is not a flat wall on black. */
import io.calamares.core 1.0
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

Page {
    id: page
    background: InstallerBackground {}

    function g(key, fallback) {
        if (!Core.Global.contains(key))
            return fallback || ""
        var v = Core.Global.value(key)
        if (v === undefined || v === null)
            return fallback || ""
        return String(v)
    }

    function firstGlobal(keys, fallback) {
        for (var i = 0; i < keys.length; i++) {
            var v = g(keys[i], "")
            if (v.length)
                return v
        }
        return fallback || ""
    }

    function partitions() {
        if (!Core.Global.contains("partitions"))
            return []
        var raw = Core.Global.value("partitions")
        if (!raw)
            return []
        try {
            if (typeof raw.length === "number")
                return raw
        } catch (e) {}
        return []
    }

    function humanSize(bytes) {
        var n = Number(bytes)
        if (!isFinite(n) || n <= 0)
            return ""
        var gib = n / 1073741824
        if (gib >= 10)
            return Math.round(gib) + " GB"
        if (gib >= 1)
            return (Math.round(gib * 10) / 10) + " GB"
        var mib = n / 1048576
        return Math.max(1, Math.round(mib)) + " MB"
    }

    function partFs(p) {
        return String(p.fs || p.filesystem || p.fileSystem || "").toLowerCase()
    }
    function partMount(p) { return String(p.mountPoint || p.mountpoint || "") }
    function partDevice(p) { return String(p.device || p.path || "") }
    function partBytes(p) {
        var n = Number(p.size || p.estimatedSize || p.length || 0)
        return (isFinite(n) && n > 0) ? n : 0
    }
    function partLabel(p) {
        var mp = partMount(p)
        var fs = partFs(p)
        if (mp === "/" || mp === "/system") return "DevOS"
        if (mp === "/boot/efi" || mp === "/efi") return "EFI"
        if (mp === "/boot") return "Boot"
        if (mp === "swap" || fs === "linuxswap" || fs === "swap") return "Swap"
        if (mp) return mp
        if (fs) return fs.toUpperCase()
        return "Free"
    }
    function partColor(p) {
        var mp = partMount(p)
        var fs = partFs(p)
        if (mp === "/boot/efi" || fs.indexOf("fat") >= 0) return "#f59e0b"
        if (mp === "/" || mp === "/system") return "#22d3ee"
        if (mp === "/boot") return "#38bdf8"
        if (fs === "swap" || fs === "linuxswap") return "#a78bfa"
        if (fs === "ntfs" || fs === "bitlocker") return "#34d399"
        return "#64748b"
    }
    function parentDisk(device) {
        var d = String(device || "")
        if (!d) return ""
        if (d.indexOf("nvme") >= 0 || d.indexOf("mmcblk") >= 0 || d.indexOf("loop") >= 0)
            return d.replace(/p[0-9]+$/, "")
        return d.replace(/[0-9]+$/, "")
    }
    function rootDisk() {
        var parts = partitions()
        for (var i = 0; i < parts.length; i++) {
            if (partMount(parts[i]) === "/")
                return parentDisk(partDevice(parts[i]))
        }
        if (Core.Global.contains("bootLoader")) {
            try {
                var bl = Core.Global.value("bootLoader")
                if (bl && bl.installPath)
                    return parentDisk(bl.installPath)
            } catch (e) {}
        }
        return ""
    }
    function plannedParts() {
        var parts = partitions()
        var out = []
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i]
            if (partMount(p) || p.claimed || p.format || p.wipe)
                out.push(p)
        }
        return out.length ? out : parts
    }
    function localeLine() {
        var zone = g("locationZone")
        var region = g("locationRegion")
        var where = (region && zone) ? (region + "/" + zone) : (zone || "Local time")
        var lang = firstGlobal(["locale", "LANG"], "American English")
        return where + "\n" + lang
    }
    function keyboardLine() {
        var model = g("keyboardModel") || "Generic 105-key PC"
        var layout = g("keyboardLayout") || "us"
        var variant = g("keyboardVariant")
        var pretty = (layout === "us") ? "English (US)" : layout
        if (variant) pretty += " · " + variant
        return model + "\n" + pretty
    }
    function storageExtraLines() {
        var choice = firstGlobal(["packagechooser_storage", "storage"], "")
        if (choice.length)
            return choice.replace(/<br\/?>/gi, "\n").replace(/<[^>]+>/g, "")
        if (!Core.Global.contains("devos_storage_selected_json"))
            return "Leave additional drives as they are"
        try {
            var obj = JSON.parse(String(Core.Global.value("devos_storage_selected_json") || "{}"))
            if (!obj || !obj.confirmed || !obj.selected || !obj.selected.length)
                return "Leave additional drives as they are"
            return obj.selected.map(function (d) {
                var vols = (d.volumes || []).map(function (v) {
                    return (v.label || "A") + " " + (v.filesystem || "ext4")
                }).join(", ")
                return (d.device || "disk") + " → " + vols
            }).join("\n")
        } catch (e) {
            return "Leave additional drives as they are"
        }
    }
    function prettyChoice(raw, fallback) {
        var t = String(raw || "").replace(/<br\/?>/gi, "\n").replace(/<[^>]+>/g, "").replace(/^\s+|\s+$/g, "")
        if (!t.length)
            return fallback || "—"
        // Drop noisy "Install option:" prefixes from packagechooser legacy labels.
        t = t.replace(/^Install option:\s*/i, "")
        return t
    }
    function appsLine() {
        var raw = firstGlobal(["packagechooser_features", "features"], "")
        if (!raw.length)
            return "Recommended apps"
        return raw.split(",").map(function (x) { return x.replace(/^\s+|\s+$/g, "") }).filter(function (x) { return x.length }).join(" · ")
    }
    function refreshChoice() {
        var disk = rootDisk() || "selected disk"
        config.packageChoice = "Install DevOS on " + disk
    }

    Component.onCompleted: refreshChoice()
    onVisibleChanged: if (visible) refreshChoice()

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 72
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: form
            x: Math.max(24, (page.width - width) / 2)
            y: 24
            width: Math.min(page.width - 48, 740)
            spacing: 12

            PageIntro {
                Layout.fillWidth: true
                eyebrow: "INSTALL PREVIEW"
                title: "Looks good — ready to install"
                subtitle: "A clear check of disks and choices. Nothing is written until you confirm Install."
            }

            SummaryCard {
                Layout.fillWidth: true
                kicker: "LOCATION"
                title: "Where you are"
                body: localeLine()
            }
            SummaryCard {
                Layout.fillWidth: true
                kicker: "KEYBOARD"
                title: "How you type"
                body: keyboardLine()
            }

            // Disk plan
            Rectangle {
                Layout.fillWidth: true
                radius: 18
                color: "#d9080b14"
                border.color: "#1e3a5f"
                border.width: 1
                implicitHeight: diskCol.implicitHeight + 34
                ColumnLayout {
                    id: diskCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 16
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "DISK"
                            color: "#38bdf8"
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                            font.letterSpacing: 2.0
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: rootDisk() || "Selected drive"
                            color: "#94a3b8"
                            font.pixelSize: 12
                            elide: Text.ElideMiddle
                            Layout.maximumWidth: 300
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "After install"
                        color: "#f8fafc"
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 30
                        radius: 11
                        color: "#0f172a"
                        clip: true
                        Row {
                            id: afterRow
                            anchors.fill: parent
                            anchors.margins: 2
                            spacing: 2
                            property var parts: plannedParts()
                            property real total: {
                                var t = 0
                                for (var i = 0; i < parts.length; i++)
                                    t += Math.max(partBytes(parts[i]), 1)
                                return Math.max(t, 1)
                            }
                            Repeater {
                                model: afterRow.parts
                                Rectangle {
                                    height: afterRow.height
                                    width: Math.max(12, (afterRow.width - 4) * (Math.max(partBytes(modelData), 1) / afterRow.total) - 2)
                                    radius: 8
                                    color: partColor(modelData)
                                    SequentialAnimation on opacity {
                                        running: page.visible && InstallerAppearance.motionEnabled
                                        loops: Animation.Infinite
                                        NumberAnimation { from: 0.82; to: 1.0; duration: 2000; easing.type: Easing.InOutSine }
                                        NumberAnimation { to: 0.82; duration: 2000; easing.type: Easing.InOutSine }
                                    }
                                }
                            }
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: plannedParts()
                            Rectangle {
                                radius: 10
                                color: "#141b2d"
                                border.color: "#243247"
                                implicitHeight: 32
                                implicitWidth: legendTxt.implicitWidth + 26
                                Row {
                                    anchors.centerIn: parent
                                    spacing: 8
                                    Rectangle {
                                        width: 9; height: 9; radius: 3
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: partColor(modelData)
                                    }
                                    Text {
                                        id: legendTxt
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: "#e2e8f0"
                                        font.pixelSize: 12
                                        text: {
                                            var sz = humanSize(partBytes(modelData))
                                            return partLabel(modelData) + (sz ? " · " + sz : "")
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: "#94a3b8"
                        font.pixelSize: 13
                        lineHeight: 1.4
                        text: {
                            var disk = rootDisk()
                            var lines = []
                            if (disk)
                                lines.push("New GPT layout on " + disk + ".")
                            var parts = plannedParts()
                            for (var i = 0; i < parts.length; i++) {
                                var p = parts[i]
                                var mp = partMount(p)
                                var fs = partFs(p) || "ext4"
                                var sz = humanSize(partBytes(p))
                                var bit = "· " + partLabel(p)
                                if (mp) bit += " → " + mp
                                bit += " (" + fs + ")"
                                if (sz) bit += " · " + sz
                                lines.push(bit)
                            }
                            if (!lines.length)
                                lines.push("The Partitions step already chose how this disk will be written.")
                            return lines.join("\n")
                        }
                    }
                }
            }

            SummaryCard {
                Layout.fillWidth: true
                kicker: "DATA DRIVES"
                title: "Extra disks"
                body: storageExtraLines()
            }
            SummaryCard {
                Layout.fillWidth: true
                kicker: "DEVOS AI"
                title: "Assistant"
                body: prettyChoice(firstGlobal(["packagechooser_aimodel", "aimodel"], ""), "Default AI pack")
            }
            SummaryCard {
                Layout.fillWidth: true
                kicker: "VOICE"
                title: "Voice"
                body: prettyChoice(firstGlobal(["packagechooser_voice", "voice"], ""), "Default voice")
            }
            SummaryCard {
                Layout.fillWidth: true
                kicker: "YOU"
                title: "Profile"
                body: prettyChoice(firstGlobal(["packagechooser_usertype", "usertype"], ""), "Recommended")
            }
            SummaryCard {
                Layout.fillWidth: true
                kicker: "APPS"
                title: "Apps to include"
                body: appsLine()
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 14
                color: "#3314221f"
                border.color: "#334155"
                implicitHeight: warn.implicitHeight + 28
                Text {
                    id: warn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    wrapMode: Text.WordWrap
                    color: "#cbd5e1"
                    font.pixelSize: 13
                    text: "Press Install to start. Existing files on the system disk will be replaced."
                }
            }
        }
    }

    component SummaryCard: Rectangle {
        property string kicker: ""
        property string title: ""
        property string body: ""
        radius: 18
        color: "#d9080b14"
        border.color: "#1e3a5f"
        border.width: 1
        implicitHeight: cardCol.implicitHeight + 30
        ColumnLayout {
            id: cardCol
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 16
            spacing: 4
            Text {
                text: kicker
                color: "#38bdf8"
                font.pixelSize: 11
                font.weight: Font.DemiBold
                font.letterSpacing: 2.0
            }
            Text {
                Layout.fillWidth: true
                text: title
                color: "#f8fafc"
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                Layout.topMargin: 4
                text: body
                color: "#cbd5e1"
                font.pixelSize: 14
                wrapMode: Text.WordWrap
                lineHeight: 1.4
            }
        }
    }
}
