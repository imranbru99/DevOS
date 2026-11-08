var panel = new Panel
panel.location = "bottom"
panel.height = 48
panel.hiding = "none"
// Full-width bar. The logo is centred by the spacers below, like Windows 11.
panel.alignment = "left"

var desktopList = desktops()
for (var i = 0; i < desktopList.length; i++) {
    var desk = desktopList[i]
    desk.wallpaperPlugin = "org.kde.image"
    desk.currentConfigGroup = new Array("Wallpaper", "org.kde.image", "General")
    desk.writeConfig("Image", "file:///usr/share/wallpapers/DevOS/DevOS-Default.png")
    desk.writeConfig("FillMode", 2)
}

// Equal flexible gaps put the logo and the app icons in the centre.
// The tray and the clock stay on the right.
var leftSpace = panel.addWidget("org.kde.plasma.panelspacer")
leftSpace.currentConfigGroup = ["General"]
leftSpace.writeConfig("expanding", true)

var menu = panel.addWidget("org.kde.plasma.kickoff")
menu.currentConfigGroup = ["General"]
menu.writeConfig("icon", "devos-logo")
menu.writeConfig("favorites", "applications:google-chrome.desktop,applications:devos-thispc.desktop,applications:devos-notepad.desktop,applications:devos-code.desktop,applications:devos-chat.desktop,applications:devos-dashboard.desktop,applications:devos-apps.desktop,applications:systemsettings.desktop")
menu.writeConfig("favoritesDisplay", 0)
menu.writeConfig("favoritesPortedToKAstats", false)
menu.writeConfig("systemFavorites", "hibernate,reboot,shutdown")

var tasks = panel.addWidget("org.kde.plasma.icontasks")
tasks.currentConfigGroup = ["General"]
tasks.writeConfig("launchers", "applications:devos-search.desktop,applications:devos-taskman.desktop,applications:devos-windows.desktop,applications:google-chrome.desktop,applications:devos-thispc.desktop,applications:devos-chat.desktop,applications:devos-code.desktop,applications:systemsettings.desktop")
// Group by application so Antigravity/Chrome do not spam one icon per window.
// Status icons belong under system tray (^), not as duplicate taskbar entries.
tasks.writeConfig("groupingStrategy", 1)
tasks.writeConfig("groupInline", false)
tasks.writeConfig("iconSpacing", 1)
tasks.writeConfig("groupPopups", true)
tasks.writeConfig("onlyGroupWhenFull", false)
tasks.writeConfig("showOnlyCurrentDesktop", false)
tasks.writeConfig("showOnlyCurrentActivity", false)
tasks.writeConfig("showOnlyCurrentScreen", false)
tasks.writeConfig("showToolTips", true)
tasks.writeConfig("highlightWindows", true)
tasks.writeConfig("sortingStrategy", 1)
tasks.writeConfig("maxStripes", 1)
// Stay as wide as the icons. If this fills the bar, the logo is pushed left.
tasks.writeConfig("fill", false)

var rightSpace = panel.addWidget("org.kde.plasma.panelspacer")
rightSpace.currentConfigGroup = ["General"]
rightSpace.writeConfig("expanding", true)

panel.addWidget("org.kde.plasma.systemtray")
var clock = panel.addWidget("org.kde.plasma.digitalclock")
clock.currentConfigGroup = ["Appearance"]
// 0 is 12-hour (8:12 PM). 1 would follow a language that uses 20:12.
clock.writeConfig("use24hFormat", 0)
