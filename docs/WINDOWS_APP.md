# Windows App on DevOS

Windows App uses Microsoft's official web portal at https://windows.cloud.microsoft/.
The launcher prefers installed Microsoft Edge, otherwise Chrome/Chromium, with a
separate persistent user-data directory under
`~/.local/share/devos/windows-app/<browser>`. This prevents reuse of the everyday
browser process and profile. It does not eliminate system memory pressure, GPU
driver failures, network failures, or remote Cloud PC problems.

Cloud PC uses `window.open()` inside the portal. That stays in the Windows App
window only when launch uses an installed PWA (`--app-id`) plus Chrome's
`PwaNavigationCapturing` flag. A plain `--app=URL` window sends Cloud PC into a
normal Chrome tab — DevOS therefore prefers the everyday Chrome/Edge PWA (same
path as other Features web apps via `devos-pwa`), and only falls back to the
isolated profile when `DEVOS_WINDOWS_APP_ISOLATED=1`. Set `DEVOS_WINDOWS_APP_ID`
to pin an id.

The first launch of the isolated profile requires signing in. Existing browser
profiles and active Cloud PC sessions are left intact; no cookies or credentials
are copied. Browser startup errors are written to
`~/.local/state/devos/windows-app-browser.log`. Existing Windows App shortcuts are
routed through the same launcher. The DevOS reminder remains a local timer, not a
live measurement of the remote connection.

The DevOS companion follows the DevOS theme. Microsoft's web portal has its own
setting: Settings (cog) → Dark Mode off for light mode. The portal does not pass
that preference to the Cloud PC. Inside remote Windows, use Settings →
Personalization → Colors → Choose your mode → Light.

Microsoft reference: https://learn.microsoft.com/en-us/windows-app/display-settings

Remmina is an alternative for an administrator-provided compatible RDP connection;
it is not assumed to be a drop-in replacement for a Windows 365 web sign-in.

The normal shortcut opens only the Microsoft web app. Run
`devos-windows-app --reminder` for the optional reminder companion. Opening a
login page does not start its countdown; start reminders after connecting.

Taskbar identity: Chromium URL app windows on Wayland use
`chrome-windows.cloud.microsoft__-Default`, independently of `--class`.
The Windows App desktop entry matches that identity; the X11 launch class uses
the same value. Historical hidden Chrome shortcuts must not claim this class.
After an update, close and reopen Windows App to refresh its taskbar association.
The persistent isolated profile is retained, including its existing sign-in data.
