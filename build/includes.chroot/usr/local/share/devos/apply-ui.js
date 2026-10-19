// Paint the DevOS background and put the taskbar back if it is missing.
// Plasma can finish the first login with only the desktop icons; this
// repairs that without wiping the user's layout when a panel is already there.

var desktopList = desktops();
for (var i = 0; i < desktopList.length; i++) {
    var desk = desktopList[i];
    desk.wallpaperPlugin = "org.kde.image";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    desk.writeConfig("Image", "file:///usr/share/wallpapers/DevOS/DevOS-Default.png");
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
    menu.currentConfigGroup = ["General"];
    menu.writeConfig("icon", "/usr/share/pixmaps/devos-logo.png");

    var tasks = panel.addWidget("org.kde.plasma.icontasks");
    tasks.currentConfigGroup = ["General"];
    tasks.writeConfig("launchers", "applications:devos-search.desktop,applications:devos-taskman.desktop,applications:devos-windows.desktop,applications:devos-browser.desktop,applications:devos-thispc.desktop,applications:devos-chat.desktop,applications:devos-code.desktop,applications:systemsettings.desktop");
    tasks.writeConfig("groupingStrategy", 0);
    tasks.writeConfig("iconSpacing", 1);
    tasks.writeConfig("groupPopups", true);
    tasks.writeConfig("onlyGroupWhenFull", false);
    tasks.writeConfig("showOnlyCurrentDesktop", false);
    tasks.writeConfig("showOnlyCurrentActivity", false);
    tasks.writeConfig("showOnlyCurrentScreen", false);
    tasks.writeConfig("showToolTips", true);
    tasks.writeConfig("highlightWindows", true);
    tasks.writeConfig("sortingStrategy", 0);
    tasks.writeConfig("maxStripes", 1);
    tasks.writeConfig("fill", false);

    var rightSpace = panel.addWidget("org.kde.plasma.panelspacer");
    rightSpace.currentConfigGroup = ["General"];
    rightSpace.writeConfig("expanding", true);

    panel.addWidget("org.kde.plasma.systemtray");
    var clock = panel.addWidget("org.kde.plasma.digitalclock");
    clock.currentConfigGroup = ["Appearance"];
    clock.writeConfig("use24hFormat", 0);
}
