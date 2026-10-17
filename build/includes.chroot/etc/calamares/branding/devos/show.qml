/* DevOS install slideshow (slideshowAPI 2).
   Calamares does not give the slideshow the install progress, so this page
   shows no steps or bar of its own: the real progress bar and the current
   task are directly below it. While files copy, it walks the apps ticked on
   "Choose your apps" (global storage packagechooser_features) and shows each
   one's best feature. If that list is missing, it falls back to the general tour. */
import QtQuick 2.15
import calamares.slideshow 1.0
import io.calamares.core 1.0 as Core

import "aimodel-hw.js" as HW
import "features-catalog.js" as Cat

Presentation {
    id: presentation

    property int current: 0

    readonly property var style: ({
        office:     { icon: "✎",  a: "#60a5fa", b: "#2563eb" },
        internet:   { icon: "◎",  a: "#38bdf8", b: "#0ea5e9" },
        chat:       { icon: "✉",  a: "#34d399", b: "#0d9488" },
        media:      { icon: "♫",  a: "#f472b6", b: "#db2777" },
        creative:   { icon: "✦",  a: "#c084fc", b: "#7c3aed" },
        games:      { icon: "♞",  a: "#fbbf24", b: "#ea580c" },
        developer:  { icon: "</>", a: "#22d3ee", b: "#2563eb" },
        utilities:  { icon: "⚙",  a: "#94a3b8", b: "#475569" },
        security:   { icon: "◈",  a: "#f87171", b: "#a855f7" },
        language:   { icon: "অ",  a: "#fb7185", b: "#f59e0b" },
        compat:     { icon: "⊞",  a: "#0ea5e9", b: "#1d4ed8" },
        devos:      { icon: "✦",  a: "#a78bfa", b: "#38bdf8" },
        family:     { icon: "☪",  a: "#34d399", b: "#0f766e" }
    })
    readonly property var tagOf: ({
        office: "OFFICE", internet: "INTERNET", chat: "CALLS & CHAT",
        media: "MUSIC & VIDEO", creative: "CREATE", games: "GAMES",
        developer: "DEVELOPER", utilities: "EVERYDAY", security: "SECURITY",
        language: "LANGUAGE", compat: "WINDOWS & ANDROID", devos: "DEVOS",
        family: "ISLAMIC & FAMILY"
    })

    function shortName(name) {
        var cut = name.indexOf(" (")
        return cut > 0 ? name.substring(0, cut) : name
    }
    function aside(name) {
        var cut = name.indexOf(" (")
        if (cut < 0 || name.charAt(name.length - 1) !== ")") return ""
        return name.substring(cut + 2, name.length - 1)
    }
    // Ids ticked on the Apps page. Written when that page is left.
    function chosenIds() {
        var keys = ["packagechooser_features", "features"]
        var raw = ""
        for (var i = 0; i < keys.length; i++) {
            if (Core.Global.contains(keys[i])) {
                raw = Core.Global.value(keys[i])
                break
            }
        }
        if (raw === undefined || raw === null) return []
        var text = (typeof raw === "string") ? raw : String(raw)
        if (!text || text === "undefined") return []
        var parts = text.split(",")
        var ids = []
        for (var j = 0; j < parts.length; j++) {
            var id = parts[j].replace(/^\s+|\s+$/g, "")
            if (id.length) ids.push(id)
        }
        return ids
    }
    function slideFor(f) {
        var look = presentation.style[f.category] || { icon: "✦", a: "#38bdf8", b: "#818cf8" }
        var points = []
        var extra = aside(f.name)
        if (extra) points.push(extra)
        if (f.windows) points.push("Works like " + f.windows)
        points.push(f.preinstalled ? "Already in DevOS" : "Downloads after install")
        return {
            tag: presentation.tagOf[f.category] || "APP",
            icon: look.icon, a: look.a, b: look.b,
            title: shortName(f.name),
            body: f.about,
            points: points
        }
    }
    // One slide per ticked app, in the same order as the Apps page, plus an opener.
    function slidesForPicks() {
        var want = {}
        var ids = chosenIds()
        for (var i = 0; i < ids.length; i++) want[ids[i]] = true
        var chosen = []
        for (var j = 0; j < Cat.data.features.length; j++)
            if (want[Cat.data.features[j].id]) chosen.push(Cat.data.features[j])
        if (!chosen.length) return []
        var slides = [{
            tag: "YOUR APPS", icon: "★", a: "#38bdf8", b: "#818cf8",
            title: "Installing what you chose",
            body: "These are the apps you ticked. Each next screen is that app, and the one thing it does best.",
            points: [chosen.length + (chosen.length === 1 ? " app" : " apps"),
                     "Change any of them later in DevOS Features"]
        }]
        for (var k = 0; k < chosen.length; k++) slides.push(slideFor(chosen[k]))
        return slides
    }

    property var cards: [
        { tag: "WELCOME TO DEVOS", icon: "★", a: "#38bdf8", b: "#818cf8",
          title: "Set up for this PC",
          body: "DevOS measured " + HW.hw.ram_gb + " GB of RAM and " + HW.hw.threads
                + " processor threads, and picked the AI model and apps that stay fast here.",
          points: ["Apps fitted to your RAM and disk", "AI model sized for this PC", "Change anything later"] },
        { tag: "DEVOS AI", icon: "✦", a: "#a78bfa", b: "#38bdf8",
          title: "A private AI that lives on your PC",
          body: "Ask about your PC, read PDFs and photos, take voice commands in Bangla and English. Nothing is sent to the cloud.",
          points: ["Works offline", "Reads PDFs & text in images", "Hey DevOS · Win+H voice"] },
        { tag: "AI FOR EVERY APP", icon: "⇄", a: "#22d3ee", b: "#6366f1",
          title: "Many AI agents at once",
          body: "A built-in OpenAI-compatible API at 127.0.0.1:11434 serves VS Code, scripts and agents side by side without hanging.",
          points: ["Parallel answers on strong PCs", "Share on Wi-Fi with a key", "devos-ai, -code, -embed"] },
        { tag: "DEVOS CODE AGENT", icon: "⌘", a: "#38bdf8", b: "#a78bfa",
          title: "An AI coding agent on your own PC",
          body: "Plans the change, reads your code, shows every edit as a diff and asks before running anything. Appears on PCs with a coding-capable model.",
          points: ["Like Cursor, fully local", "Accept or reject each change", "Works inside VS Code too"] },
        { tag: "WRITE FASTER", icon: "✎", a: "#f472b6", b: "#fb923c",
          title: "Notes, voice typing and AI on any text",
          body: "Sticky notes and notebooks with AI summaries, speak instead of typing with Win+Alt+H, and select any text then press Win+Alt+A to rewrite or translate it.",
          points: ["Bangla + English dictation", "Rewrite · Translate · Summarize", "Notes backed up with your files"] },
        { tag: "ISLAMIC DEVOS", icon: "☪", a: "#34d399", b: "#0d9488",
          title: "Prayer times, Quran and Hadith",
          body: "Optional: prayer reminders, Qibla and Hijri date, a daily ayah and hadith from verified sources, and Family Safety to keep adult content away.",
          points: ["Karachi / Hanafi by default", "বাংলা + English + Arabic", "Turn on in DevOS Features"] },
        { tag: "OFFICE", icon: "✎", a: "#60a5fa", b: "#2563eb",
          title: "Word, Excel and PowerPoint files just open",
          body: "ONLYOFFICE or LibreOffice open .docx, .xlsx and .pptx with a double-click and save them back in the same format.",
          points: ["Microsoft-compatible fonts", "Merge, split & sign PDFs", "Thunderbird email"] },
        { tag: "PHONE LINK", icon: "☏", a: "#34d399", b: "#0ea5e9",
          title: "Control your PC from your phone",
          body: "Scan a QR code: send files, use the clipboard, change volume, open apps, see the screen or ask DevOS AI. No app needed.",
          points: ["Pair with a one-time code", "Files both ways", "Phone companion included"] },
        { tag: "DEVOS SHARE", icon: "◎", a: "#f472b6", b: "#8b5cf6",
          title: "Show your local app to the world",
          body: "Running a website on your PC? Click Make public and get an https link anyone can open. No domain, no router setup.",
          points: ["Works behind shared ISP IPs", "QR code for phones", "Stop with one click"] },
        { tag: "CLOUD BACKUP", icon: "☁", a: "#38bdf8", b: "#22c55e",
          title: "Your files, safe in your own cloud",
          body: "Optional. Back up Documents, Desktop, Pictures and Downloads to Google Drive or OneDrive, and restore them on any PC.",
          points: ["Off until you turn it on", "New downloads backed up", "Deleting never wipes the cloud"] },
        { tag: "WINDOWS APPS", icon: "⊞", a: "#0ea5e9", b: "#2563eb",
          title: "Run .exe and .msi programs",
          body: "Double-click a Windows installer and DevOS opens it in its own safe space. Popular apps get their faster native version.",
          points: ["32- and 64-bit programs", "Native AnyDesk, Zoom, Discord…", "No Windows licence"] },
        { tag: "ANDROID APPS", icon: "▤", a: "#4ade80", b: "#16a34a",
          title: "Install .apk files",
          body: "Android apps open in their own window next to your desktop apps, and WhatsApp or Telegram come as native apps.",
          points: ["One-time Android download", "Windows next to desktop apps", "Uninstall from Apps"] },
        { tag: "APPS & FEATURES", icon: "⚙", a: "#fbbf24", b: "#f97316",
          title: "Add or remove anything",
          body: "DevOS Features works like Windows' optional features: Office, browsers, games, creative and developer apps in one place.",
          points: ["60+ apps, verified", "Set your default apps", "Your picks download after install"] },
        { tag: "ALWAYS FAST", icon: "⚡", a: "#facc15", b: "#f59e0b",
          title: "Optimizer keeps it quick",
          body: "Apps you have not used for a while are pointed out before they slow you down, and leftover files are cleaned in one click.",
          points: ["Compressed memory", "Idle AI gives RAM back", "Memory-hog protection"] },
        { tag: "SAFE BY DEFAULT", icon: "◈", a: "#f87171", b: "#a855f7",
          title: "Restore points, firewall, antivirus",
          body: "Roll back a bad change in one click, keep strangers out with the firewall, and scan downloads for Windows viruses.",
          points: ["Timeshift restore points", "Firewall on", "No telemetry"] },
        { tag: "বাংলা", icon: "অ", a: "#fb7185", b: "#f59e0b",
          title: "Type and talk in Bangla",
          body: "Avro phonetic typing with Ctrl+Space, Bangla fonts everywhere, and DevOS AI understands Bangla voice commands.",
          points: ["ami → আমি", "Bangla OCR in images", "Bangla + English voice"] },
        { tag: "FOR BUILDERS", icon: "⟨⟩", a: "#38bdf8", b: "#10b981",
          title: "Ready to code",
          body: "Git, Node.js, Python, PHP, databases, Podman and VS Code with DevOS AI built in are ready the moment you sign in.",
          points: ["Local servers like Laragon", "AI code model optional", "Public links for demos"] }
    ]

    function onActivate() {
        var picked = slidesForPicks()
        if (picked.length > 0) {
            cards = picked
            current = 0
        }
        rotator.running = true
    }
    function onLeave() { rotator.running = false }

    // Slides keep a 16:9 box in the middle; paint the area around it too,
    // otherwise the slideshow sat in a white frame.
    Rectangle {
        anchors.fill: parent
        z: -1
        color: "#0b0f1a"
    }

    Timer {
        id: rotator
        interval: 6500
        repeat: true
        running: false
        onTriggered: fade.restart()
    }

    SequentialAnimation {
        id: fade
        ParallelAnimation {
            NumberAnimation { target: content; property: "opacity"; to: 0; duration: 260 }
            NumberAnimation { target: content; property: "x"; to: -24; duration: 260; easing.type: Easing.InQuad }
        }
        ScriptAction { script: presentation.current = (presentation.current + 1) % presentation.cards.length }
        PropertyAction { target: content; property: "x"; value: 24 }
        ParallelAnimation {
            NumberAnimation { target: content; property: "opacity"; to: 1; duration: 420 }
            NumberAnimation { target: content; property: "x"; to: 0; duration: 420; easing.type: Easing.OutCubic }
        }
    }

    Slide {
        Rectangle {
            id: stage
            readonly property var c: presentation.cards[presentation.current]
            anchors.fill: parent
            clip: true
            radius: 18
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0a1020" }
                GradientStop { position: 1.0; color: "#120d24" }
            }

            // Accent glows that follow the slide colours
            Rectangle {
                width: parent.width * 0.75; height: width; radius: width / 2
                x: parent.width * 0.45; y: -height * 0.45
                color: stage.c.a; opacity: 0.10
                Behavior on color { ColorAnimation { duration: 600 } }
            }
            Rectangle {
                width: parent.width * 0.5; height: width; radius: width / 2
                x: -width * 0.3; y: parent.height * 0.55
                color: stage.c.b; opacity: 0.08
                Behavior on color { ColorAnimation { duration: 600 } }
            }

            Item {
                id: content
                width: parent.width
                height: parent.height

                // ---- text column
                Column {
                    id: textCol
                    // below the progress row at the top, centred in the rest
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: 14
                    anchors.left: parent.left
                    anchors.leftMargin: Math.max(36, parent.width * 0.06)
                    width: parent.width * 0.54
                    spacing: 10

                    Text {
                        text: stage.c.tag
                        color: stage.c.a
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        font.letterSpacing: 3
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: stage.c.title
                        color: "#f8fafc"
                        font.pixelSize: Math.max(24, Math.min(34, stage.width / 28))
                        font.weight: Font.Bold
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: stage.c.body
                        color: "#cbd5e1"
                        font.pixelSize: Math.max(14, Math.min(16, stage.width / 58))
                        lineHeight: 1.2
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        topPadding: 4
                        Repeater {
                            model: stage.c.points
                            Rectangle {
                                radius: 13
                                height: 26
                                width: chip.implicitWidth + 24
                                color: "#141c30"
                                border.color: "#26324a"
                                Text {
                                    id: chip
                                    anchors.centerIn: parent
                                    text: "✓  " + modelData
                                    color: "#e2e8f0"
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }
                }

                // ---- feature tile
                Rectangle {
                    id: tile
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: Math.max(36, parent.width * 0.07)
                    width: Math.min(parent.width * 0.3, parent.height * 0.62)
                    height: width
                    radius: width * 0.22
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: stage.c.a }
                        GradientStop { position: 1.0; color: stage.c.b }
                    }
                    // glass highlight
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 1
                        radius: parent.radius
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#40ffffff" }
                            GradientStop { position: 0.55; color: "#00ffffff" }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        text: stage.c.icon
                        color: "white"
                        font.pixelSize: tile.width * 0.42
                        font.weight: Font.Bold
                    }
                    // gentle float
                    SequentialAnimation on anchors.verticalCenterOffset {
                        loops: Animation.Infinite
                        NumberAnimation { to: -8; duration: 2200; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 8; duration: 2200; easing.type: Easing.InOutSine }
                    }
                }
            }

            // ---- progress through the tour
            Row {
                visible: presentation.cards.length <= 18
                anchors.top: parent.top
                anchors.topMargin: 22
                anchors.left: parent.left
                anchors.leftMargin: Math.max(36, parent.width * 0.06)
                spacing: 7
                Repeater {
                    model: presentation.cards.length
                    Rectangle {
                        width: index === presentation.current ? 26 : 7
                        height: 7
                        radius: 4
                        color: index === presentation.current ? stage.c.a : "#334155"
                        Behavior on width { NumberAnimation { duration: 250 } }
                    }
                }
            }
            Text {
                anchors.top: parent.top
                anchors.topMargin: 17
                anchors.right: parent.right
                anchors.rightMargin: Math.max(36, parent.width * 0.07)
                text: (presentation.current + 1) + " / " + presentation.cards.length
                color: "#64748b"
                font.pixelSize: 12
            }
        }
    }
}
