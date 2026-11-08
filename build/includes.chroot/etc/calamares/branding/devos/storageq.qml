/* Explicit, reviewed plans for additional data disks. Calamares owns OS disks. */
import io.calamares.core 1.0
import io.calamares.ui 1.0
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import "storage-devices.js" as Storage

Page {
    id: page
    background: InstallerBackground {}
    property var selected: []
    property bool confirmed: false
    readonly property var eligible: Storage.disks.filter(function(d) { return !d.is_live_media && !d.read_only && !d.in_use && d.size_bytes >= 1073741824; })

    function choice(device) {
        for (var i = 0; i < selected.length; i++) if (selected[i].device === device) return selected[i];
        return null;
    }
    function defaultChoice(d) {
        return {device:d.device, model:d.model, serial:d.serial, size_bytes:d.size_bytes,
                volumes:[{label:"A", filesystem:"ext4", size_gib:0}]};
    }
    function toggle(d, on) {
        var next = selected.filter(function(p) { return p.device !== d.device; });
        if (on) next.push(defaultChoice(d));
        selected = next;
    }
    function countVolumes(d, count) {
        var next = JSON.parse(JSON.stringify(selected));
        for (var i = 0; i < next.length; i++) if (next[i].device === d.device) {
            var parts = [];
            var size = Math.max(0.1, Math.floor(d.size_bytes / 1073741824 / count * 10) / 10);
            for (var j = 0; j < count; j++) parts.push({label:String.fromCharCode(65+j), filesystem:"ext4", size_gib:j === count-1 ? 0 : size});
            next[i].volumes = parts;
        }
        selected = next;
    }
    function editVolume(device, index, key, value) {
        var next = JSON.parse(JSON.stringify(selected));
        for (var i = 0; i < next.length; i++) if (next[i].device === device) next[i].volumes[index][key] = value;
        selected = next;
    }
    function valid() {
        for (var i = 0; i < selected.length; i++) {
            var p = selected[i]; var used = 1; var names = [];
            var limit = Math.floor(p.size_bytes / 1048576)-1;
            for (var j = 0; j < p.volumes.length; j++) {
                var v = p.volumes[j]; var name = v.label.trim();
                if (!/^[A-Za-z0-9][A-Za-z0-9 _.-]{0,15}$/.test(name) || names.indexOf(name.toLowerCase()) >= 0) return false;
                names.push(name.toLowerCase());
                var size = j === p.volumes.length-1 ? limit-used : Math.floor(Number(v.size_gib)*1024);
                if (!isFinite(size) || size < 64 || used+size > limit) return false;
                used += size;
            }
        }
        return true;
    }
    function save() {
        if (!confirmed || !valid() || selected.length === 0) {
            config.packageChoice = "Preserve all additional drives";
            return;
        }
        var lines = selected.map(function(d) {
            var volumes = d.volumes.map(function(v, i) {
                return v.label.trim() + " " + (i === d.volumes.length-1 ? "remaining" : String(Number(v.size_gib)) + " GiB");
            });
            return d.device + " → " + volumes.join(" · ");
        });
        config.packageChoice = "Erase selected additional drives (ext4):<br/>" + lines.join("<br/>") + "<br/>OS and manually configured disks are excluded.";
    }
    onSelectedChanged: { confirmed = false; save(); }
    onConfirmedChanged: save()
    Component.onCompleted: save()

    Flickable {
        anchors.fill: parent
        contentHeight: form.implicitHeight + 64
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: form
            x: 32; y: 32
            width: Math.max(240, page.width-64)
            spacing: 14
            PageIntro {
                Layout.fillWidth: true
                eyebrow: "STORAGE"
                title: "Make room for everything"
                titleSize: 30
                subtitle: "Keep other drives as they are, or choose additional SSDs/HDDs to erase and format as ext4. Nothing is selected by default."
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: guidance.implicitHeight+28; radius: 14
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#102238" }
                    GradientStop { position: 1.0; color: "#0c1a2e" }
                }
                border.color: "#1e4c71"
                Text {
                    id: guidance; anchors.fill: parent; anchors.margins: 14; color: "#bae6fd"; font.pixelSize: 14; wrapMode: Text.WordWrap
                    text: "Yes — you can format disks during install. On Partitions, DevOS defaults to Erase disk (like Windows Setup): the SSD/HDD you select is wiped and reformatted for DevOS. Other disks stay untouched. Use Manual partitioning for dual-boot. This page is only for optional extra data drives (A/B/C volumes)."
                }
            }
            RowLayout {
                Button { padding: 12; font.pixelSize: 14; palette.button: "#14243a"; palette.buttonText: "#f8fafc"; text: "Select all eligible drives"; onClicked: page.selected = page.eligible.map(function(d) { return page.defaultChoice(d); }) }
                Button { padding: 12; font.pixelSize: 14; palette.button: "#14243a"; palette.buttonText: "#f8fafc"; text: "Keep all other drives"; onClicked: page.selected = [] }
            }
            Text { visible: page.eligible.length === 0; text: "No additional writable drives detected."; color: "#94a3b8" }
            Repeater {
                model: page.eligible
                delegate: Rectangle {
                    id: card
                    readonly property var disk: modelData
                    readonly property var chosen: page.choice(disk.device)
                    Layout.fillWidth: true; implicitHeight: body.implicitHeight+28
                    radius: 14; color: chosen ? "#10263b" : "#0f172a"; border.color: chosen ? "#38bdf8" : "#25334b"
                    ColumnLayout {
                        id: body
                        anchors.fill: parent; anchors.margins: 14; spacing: 10
                        CheckBox {
                            spacing: 12; padding: 4
                            indicator: Rectangle { implicitWidth: 22; implicitHeight: 22; radius: 6; y: (parent.height-height)/2; color: parent.checked ? "#0284c7" : "#0b1322"; border.color: "#38bdf8"; Text { anchors.centerIn: parent; text: parent.parent.checked ? "✓" : ""; color: "white"; font.pixelSize: 16 } }
                            Layout.fillWidth: true
                            text: card.disk.model + " · " + card.disk.size_human + " · " + card.disk.device
                            checked: !!card.chosen
                            onToggled: page.toggle(card.disk, checked)
                            contentItem: Text { text: parent.text; leftPadding: parent.indicator.width+parent.spacing; color: "#f8fafc"; font.pixelSize: 14; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter }
                        }
                        RowLayout {
                            visible: !!card.chosen
                            Text { text: "Data volumes"; color: "#cbd5e1" }
                            ComboBox {
                                font.pixelSize: 14; padding: 10; palette.button: "#15233b"; palette.buttonText: "#f8fafc"
                                model: ["One volume", "A / B", "A / B / C"]
                                currentIndex: card.chosen ? card.chosen.volumes.length-1 : 0
                                onActivated: page.countVolumes(card.disk, currentIndex+1)
                            }
                            Text { text: "ext4 · Custom sizes in GiB"; color: "#7dd3fc"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                        Repeater {
                            model: card.chosen ? card.chosen.volumes : []
                            delegate: RowLayout {
                                readonly property int volumeIndex: index
                                Layout.fillWidth: true
                                TextField { padding: 10; font.pixelSize: 14; Layout.preferredWidth: 140; text: modelData.label; maximumLength: 16; placeholderText: "Volume label"; onEditingFinished: page.editVolume(card.disk.device, parent.volumeIndex, "label", text) }
                                TextField { padding: 10; font.pixelSize: 14; visible: card.chosen && parent.volumeIndex < card.chosen.volumes.length-1; Layout.preferredWidth: 140; text: String(modelData.size_gib); placeholderText: "Size (GiB)"; onEditingFinished: page.editVolume(card.disk.device, parent.volumeIndex, "size_gib", text) }
                                Text { visible: card.chosen && parent.volumeIndex === card.chosen.volumes.length-1; text: "Remaining space"; color: "#94a3b8" }
                            }
                        }
                    }
                }
            }
            Text { visible: !page.valid(); text: "Check volume labels and sizes. Each volume must fit on its disk."; color: "#fbbf24"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            CheckBox {
                spacing: 12; padding: 4
                indicator: Rectangle { implicitWidth: 22; implicitHeight: 22; radius: 6; y: (parent.height-height)/2; color: parent.checked ? "#0284c7" : "#0b1322"; border.color: "#fbbf24"; Text { anchors.centerIn: parent; text: parent.parent.checked ? "✓" : ""; color: "white"; font.pixelSize: 16 } }
                Layout.fillWidth: true
                visible: page.selected.length > 0
                enabled: page.valid()
                text: "Erase the selected additional drives and create the ext4 volumes shown above. I have backed up their data."
                checked: page.confirmed
                onToggled: page.confirmed = checked
                contentItem: Text { text: parent.text; leftPadding: parent.indicator.width+parent.spacing; color: "#fbbf24"; font.pixelSize: 14; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter }
            }
            Text {
                text: page.selected.length === 0 || !page.confirmed ? "Additional drive formatting is OFF. Other drives will be preserved." : "Additional drive formatting is ON. Changes will run only after you confirm Install."
                color: page.confirmed ? "#fbbf24" : "#2dd4bf"; wrapMode: Text.WordWrap; Layout.fillWidth: true; font.pixelSize: 14
            }
        }
    }
}
