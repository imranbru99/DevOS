// Paint the DevOS background and keep Start + taskbar on DevOS apps.
// If a panel already exists (skel appletsrc), still rewrite Kickoff favorites
// and scrub dead pins — otherwise Plasma keeps Dolphin/Kate/Konsole defaults.

var DESKTOP_WALLPAPER = "file:///usr/share/wallpapers/DevOS/DevOS-Default.png";
var TASKBAR_LAUNCHERS = "applications:devos-search.desktop,applications:devos-taskman.desktop,applications:devos-windows.desktop,applications:google-chrome.desktop,applications:devos-thispc.desktop,applications:devos-chat.desktop,applications:devos-code.desktop,applications:devos-settings.desktop";
var KICKOFF_FAVORITES = "applications:google-chrome.desktop,applications:devos-thispc.desktop,applications:devos-notepad.desktop,applications:devos-code.desktop,applications:devos-chat.desktop,applications:devos-dashboard.desktop,applications:devos-apps.desktop,applications:devos-settings.desktop";

function scrubLaunchers(raw) {
    if (!raw) {
        return TASKBAR_LAUNCHERS;
    }
    var parts = raw.split(",");
    var keep = [];
    for (var i = 0; i < parts.length; i++) {
        var entry = parts[i].trim();
        if (!entry) {
            continue;
        }
        // Installer pin is removed after disk install — leave it and icons go blank.
        if (entry.indexOf("devos-install.desktop") !== -1) {
            continue;
        }
        if (entry.indexOf("org.kde.dolphin.desktop") !== -1
                || entry.indexOf("org.kde.kate.desktop") !== -1
                || entry.indexOf("org.kde.konsole.desktop") !== -1
                || entry.indexOf("preferred://filemanager") !== -1) {
            continue;
        }
        keep.push(entry);
    }
    return keep.length ? keep.join(",") : TASKBAR_LAUNCHERS;
}

function configureKickoff(menu) {
    menu.currentConfigGroup = ["General"];
    menu.writeConfig("icon", "devos-logo");
    menu.writeConfig("favorites", KICKOFF_FAVORITES);
    menu.writeConfig("favoritesDisplay", 0);
    menu.writeConfig("favoritesPortedToKAstats", false);
    menu.writeConfig("systemFavorites", "hibernate,reboot,shutdown");
}

function configureTasks(tasks) {
    tasks.currentConfigGroup = ["General"];
    var current = "";
    try {
        current = tasks.readConfig("launchers", "");
    } catch (e) {
        current = "";
    }
    tasks.writeConfig("launchers", scrubLaunchers(current));
    tasks.writeConfig("groupingStrategy", 1);
    tasks.writeConfig("groupInline", false);
    tasks.writeConfig("iconSpacing", 1);
    tasks.writeConfig("groupPopups", true);
    tasks.writeConfig("onlyGroupWhenFull", false);
    tasks.writeConfig("showOnlyCurrentDesktop", false);
    tasks.writeConfig("showOnlyCurrentActivity", false);
    tasks.writeConfig("showOnlyCurrentScreen", false);
    tasks.writeConfig("showToolTips", true);
    tasks.writeConfig("highlightWindows", true);
    tasks.writeConfig("sortingStrategy", 1);
    tasks.writeConfig("maxStripes", 1);
    tasks.writeConfig("fill", false);
}

var desktopList = desktops();
for (var i = 0; i < desktopList.length; i++) {
    var desk = desktopList[i];
    desk.wallpaperPlugin = "org.kde.image";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    desk.writeConfig("Image", DESKTOP_WALLPAPER);
    desk.writeConfig("FillMode", 2);
}

var panelList = panels();
if (panelList.length === 0) {
    var panel = new Panel;
    panel.location = "bottom";
    panel.height = 40;
    panel.hiding = "none";
    panel.alignment = "left";

    var leftSpace = panel.addWidget("org.kde.plasma.panelspacer");
    leftSpace.currentConfigGroup = ["General"];
    leftSpace.writeConfig("expanding", true);

    var menu = panel.addWidget("org.kde.plasma.kickoff");
    configureKickoff(menu);

    var tasks = panel.addWidget("org.kde.plasma.icontasks");
    configureTasks(tasks);

    var rightSpace = panel.addWidget("org.kde.plasma.panelspacer");
    rightSpace.currentConfigGroup = ["General"];
    rightSpace.writeConfig("expanding", true);

    panel.addWidget("org.kde.plasma.systemtray");
    var clock = panel.addWidget("org.kde.plasma.digitalclock");
    clock.currentConfigGroup = ["Appearance"];
    clock.writeConfig("use24hFormat", 0);
    clock.writeConfig("dateFormat", "shortDate");
    clock.writeConfig("showSeconds", false);
} else {
    for (var p = 0; p < panelList.length; p++) {
        var widgets = panelList[p].widgets();
        for (var w = 0; w < widgets.length; w++) {
            var widget = widgets[w];
            if (widget.type === "org.kde.plasma.kickoff") {
                configureKickoff(widget);
            } else if (widget.type === "org.kde.plasma.icontasks") {
                configureTasks(widget);
            } else if (widget.type === "org.kde.plasma.digitalclock") {
                widget.currentConfigGroup = ["Appearance"];
                widget.writeConfig("use24hFormat", 0);
                widget.writeConfig("dateFormat", "shortDate");
            }
        }
    }
}
