pragma Singleton
import QtQuick 2.15
import QtQuick.Window 2.15

QtObject {
    // Shared for this installer session, including pages loaded later.
    property bool motionEnabled: true

    // Prefer the usable desktop area (excludes panels/taskbars) so Next is never
    // sized against the full panel-covered Screen.height.
    readonly property int availHeight: {
        var h = Screen.desktopAvailableHeight
        return (h && h > 0) ? h : Screen.height
    }
    readonly property int availWidth: {
        var w = Screen.desktopAvailableWidth
        return (w && w > 0) ? w : Screen.width
    }

    // 1366x768 laptops, netbooks, and HiDPI panels with short usable height.
    readonly property bool compact: availHeight > 0 && availHeight < 820
    readonly property bool tiny: availHeight > 0 && availHeight < 680
    readonly property bool narrow: availWidth > 0 && availWidth < 1100

    readonly property int sidebarWidth: tiny ? 148 : (compact || narrow ? 188 : 248)
    readonly property int navBarHeight: tiny ? 52 : (compact ? 58 : 72)
    readonly property int navButtonHeight: tiny ? 32 : (compact ? 36 : 44)
    readonly property int pageTitleSize: tiny ? 24 : (compact ? 28 : 32)
    readonly property int pageMargin: tiny ? 20 : (compact ? 28 : 40)
}
