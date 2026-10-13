var panel = new Panel
panel.location = "bottom"
panel.height = 48
panel.hiding = "none"
panel.alignment = "left"

var desktopList = desktops()
for (var i = 0; i < desktopList.length; i++) {
    var desk = desktopList[i]
    desk.wallpaperPlugin = "org.kde.image"
    desk.currentConfigGroup = new Array("Wallpaper", "org.kde.image", "General")
    desk.writeConfig("Image", "file:///usr/share/wallpapers/DevOS/DevOS-Default.png")
    desk.writeConfig("FillMode", 2)
}

var menu = panel.addWidget("org.kde.plasma.kickoff")
menu.currentConfigGroup = ["General"]
menu.writeConfig("icon", "/usr/share/pixmaps/devos-logo.png")

var tasks = panel.addWidget("org.kde.plasma.icontasks")
tasks.currentConfigGroup = ["General"]
tasks.writeConfig("launchers", "applications:devos-windows.desktop,applications:devos-browser.desktop,applications:devos-thispc.desktop,applications:devos-chat.desktop,applications:devos-code.desktop,applications:systemsettings.desktop,applications:devos-install.desktop")
// Icons only, grouped by app: many apps fit without the taskbar filling up.
tasks.writeConfig("groupingStrategy", 1)
tasks.writeConfig("iconSpacing", 1)
tasks.writeConfig("groupPopups", true)
tasks.writeConfig("onlyGroupWhenFull", false)
tasks.writeConfig("showOnlyCurrentDesktop", false)
tasks.writeConfig("showOnlyCurrentActivity", false)
tasks.writeConfig("showOnlyCurrentScreen", false)
tasks.writeConfig("showToolTips", true)
tasks.writeConfig("highlightWindows", true)
tasks.writeConfig("sortingStrategy", 0)
tasks.writeConfig("maxStripes", 1)

panel.addWidget("org.kde.plasma.systemtray")
panel.addWidget("org.kde.plasma.digitalclock")
