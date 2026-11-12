/* DevOS "Choose your apps" page (packagechooserq@features).
   First visit ticks the apps that match the PC type (Normal includes Chrome).
   Unticked apps stay available later in DevOS Features.
   Preset chips (Normal, Premium, …) tick a set; "Choose later" ticks nothing.
   aimodel-hw.js holds the RAM and disk measured at live boot by devos-ai-hwprobe.
   Ticked ids go to global storage; devospreserve copies them into the new system
   and installer-plan enables only those builtins, then downloads the rest on
   the first online boot. */
import io.calamares.core 1.0 as Core
import io.calamares.ui 1.0

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3

import "features-catalog.js" as Cat
import "aimodel-hw.js" as HW

Page {
    id: page
    background: InstallerBackground {}

    readonly property real ramGb: HW.hw.ram_gb
    readonly property real diskGb: HW.hw.disk_gb
    // Start empty; applyUserType() seeds PC-type defaults or restores saved picks.
    // Do not seed with recommended() here — that overwrote Global storage on revisit.
    property var picked: []
    property string preset: ""
    property string appliedKind: ""
    readonly property var categoryOptions: [{ id: "", name: "All categories" }].concat(Cat.data.categories)
    readonly property var visibleGroups: appGroups(
        categoryBox.currentIndex, appSearch.text, hardwareFilter.checked)

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
            // Nothing optional now — user can add apps later in DevOS Features.
            picked = [];
        } else if (p === "minimal") {
            // Base system only — optional apps are added later in DevOS Features.
            picked = [];
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
    function loadSavedPicks() {
        if (!Core.Global.contains("devos_selected_features"))
            return null;
        var raw = Core.Global.value("devos_selected_features");
        return String(raw || "").split(",").filter(function (id) { return page.feature(id) !== null; });
    }
    function featuresKindKey() { return "devos_features_usertype"; }
    function rememberFeaturesKind(kind) {
        try { Core.Global.insert(featuresKindKey(), kind); } catch (e) {}
    }
    function rememberedFeaturesKind() {
        try {
            if (Core.Global.contains(featuresKindKey()))
                return String(Core.Global.value(featuresKindKey()) || "");
        } catch (e) {}
        return "";
    }
    function applyUserType() {
        var kind = userKind();

        // Same PC type on this page instance: never wipe custom ticks on Back/Next.
        if (kind === appliedKind)
            return;

        var saved = loadSavedPicks();
        var savedFor = rememberedFeaturesKind();

        // Page was recreated after Back: restore the exact apps left for this PC type.
        if (saved !== null && savedFor === kind) {
            appliedKind = kind;
            picked = saved;
            save();
            return;
        }

        // First visit for this PC type: tick the apps that match it (Normal
        // includes Chrome, etc.). The user can still untick any app.
        picked = Cat.userTypeIds(kind, ramGb, diskGb);
        preset = (kind === "normal") ? "recommended" : kind;
        appliedKind = kind;
        save();
    }
    function onActivate() { applyUserType(); }
    function appGroups(categoryIndex, query, fittedOnly) {
        var words = query.toLowerCase().trim().split(/\s+/);
        var category = page.categoryOptions[categoryIndex];
        var groups = [];
        Cat.data.categories.forEach(function (cat) {
            if (category && category.id && category.id !== cat.id) return;
            var apps = Cat.data.features.filter(function (f) {
                if (f.category !== cat.id) return false;
                if (fittedOnly && (page.tooHeavy(f) || Cat.largeForDisk(f, page.diskGb))) return false;
                var searchable = [f.name, f.windows, f.about, cat.name].join(" ").toLowerCase();
                return words.every(function (word) { return searchable.indexOf(word) >= 0; });
            });
            if (apps.length) groups.push({ id: cat.id, name: cat.name, apps: apps });
        });
        return groups;
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
    function save() {
        var choices = picked.join(",");
        config.packageChoice = choices;
        Core.Global.insert("devos_selected_features", choices);
        if (appliedKind)
            rememberFeaturesKind(appliedKind);
    }

    onPickedChanged: { if (appliedKind) save(); }
    Component.onCompleted: applyUserType()

    Flickable {
        id: flick
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: footer.top }
        contentHeight: form.implicitHeight + 64
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: form
            x: Math.max(InstallerAppearance.pageMargin, (flick.width - width) / 2)
            y: InstallerAppearance.pageMargin
            width: Math.min(flick.width - InstallerAppearance.pageMargin * 2, InstallerAppearance.pageMaxWidth)
            spacing: 8

            PageIntro {
                Layout.fillWidth: true
                eyebrow: "APPS & FEATURES"
                title: "Choose your apps"
                subtitle: "Choose from " + Cat.data.features.length + " apps and features. "
                    + "Only the optional apps you tick are installed. You can add more later in DevOS Features."
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

            GridLayout {
                Layout.fillWidth: true
                Layout.topMargin: 8
                columns: form.width < 420 ? 1 : 2
                columnSpacing: 8
                rowSpacing: 6
                TextField {
                    id: appSearch
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    placeholderText: "Search apps or Windows equivalents"
                    Accessible.name: placeholderText
                    selectByMouse: true
                    color: "#f8fafc"
                    placeholderTextColor: "#94a3b8"
                    background: Rectangle {
                        radius: 8
                        color: "#0f172a"
                        border.color: appSearch.activeFocus ? "#38bdf8" : "#334155"
                    }
                }
                ComboBox {
                    id: categoryBox
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    model: page.categoryOptions
                    textRole: "name"
                    Accessible.name: "App category"
                }
            }

            CheckBox {
                id: hardwareFilter
                Layout.fillWidth: true
                text: "Hide apps with higher RAM or storage needs"
                palette.windowText: "#e2e8f0"
            }

            Text {
                Layout.fillWidth: true
                visible: page.visibleGroups.length === 0
                wrapMode: Text.WordWrap
                color: "#94a3b8"
                text: "No apps match. Try another search or change the filters."
            }

            Repeater {
                model: page.visibleGroups
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
                        model: cat.apps
                        delegate: Rectangle {
                            id: rowCard
                            readonly property var f: modelData
                            readonly property bool on: page.has(f.id)
                            readonly property bool heavy: page.tooHeavy(f)
                            readonly property bool largeDownload: Cat.largeForDisk(f, page.diskGb)
                            Layout.fillWidth: true
                            implicitHeight: row.implicitHeight + 18
                            radius: 12
                            color: on ? "#0c1a2e" : (rowMouse.containsMouse ? "#111c31" : "#0f172a")
                            border.color: activeFocus ? "#38bdf8" : on ? "#2563eb" : "#1e293b"
                            activeFocusOnTab: true
                            Accessible.role: Accessible.CheckBox
                            Accessible.name: f.name
                            Accessible.checked: on
                            Accessible.onPressAction: page.toggle(f.id, !on)
                            Keys.onSpacePressed: page.toggle(f.id, !on)
                            onActiveFocusChanged: {
                                if (!activeFocus) return;
                                var top = mapToItem(flick.contentItem, 0, 0).y;
                                if (top < flick.contentY)
                                    flick.contentY = top;
                                else if (top + height > flick.contentY + flick.height)
                                    flick.contentY = top + height - flick.height;
                            }
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
                                        Rectangle {
                                            visible: rowCard.largeDownload
                                            radius: 6
                                            color: "#3b2506"
                                            implicitWidth: diskWarn.implicitWidth + 12
                                            implicitHeight: diskWarn.implicitHeight + 4
                                            Text { id: diskWarn; anchors.centerIn: parent; text: "Large download"; color: "#fbbf24"; font.pixelSize: 11 }
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
                                    text: rowCard.f.optin ? (rowCard.on ? "Turns on" : "Off — install later")
                                          : rowCard.f.preinstalled ? (rowCard.on ? "Included" : "Skipped — install later")
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
        // Grow with wrapped summary text on narrow / short screens.
        height: Math.max(InstallerAppearance.tiny ? 48 : 58, footerFlow.implicitHeight + 16)
        color: "#0d1424"
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: 1; color: "#1e293b" }
        Flow {
            id: footerFlow
            anchors {
                left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                leftMargin: InstallerAppearance.narrow ? 16 : 32
                rightMargin: InstallerAppearance.narrow ? 16 : 32
            }
            spacing: 14
            Text {
                text: page.picked.length + " apps & features"
                color: "#f8fafc"; font.pixelSize: 13; font.weight: Font.DemiBold
            }
            Text {
                text: "Download after install: " + (page.downloadMb() > 0 ? page.human(page.downloadMb()) : "nothing")
                color: "#cbd5e1"; font.pixelSize: 12
            }
            Text {
                visible: page.freeAfterGb() >= 0
                text: "≈ " + Math.max(0, Math.round(page.freeAfterGb())) + " GB free afterwards"
                color: page.freeAfterGb() < 10 ? "#fbbf24" : "#86efac"
                font.pixelSize: 12
            }
            Text {
                visible: page.removedCount() > 0
                text: page.removedCount() + " skipped (install later in Features)"
                color: "#94a3b8"; font.pixelSize: 12
            }
        }
    }
}
