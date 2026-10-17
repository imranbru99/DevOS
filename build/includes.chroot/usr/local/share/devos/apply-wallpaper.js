// Kept for callers that only want the background. apply-ui.js does the same
// plus restores the taskbar when Plasma left it off.
var all = desktops();
for (var i = 0; i < all.length; ++i) {
    var desk = all[i];
    desk.wallpaperPlugin = "org.kde.image";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    desk.writeConfig("Image", "file:///usr/share/wallpapers/DevOS/DevOS-Default.png");
    desk.writeConfig("FillMode", 2);
}
