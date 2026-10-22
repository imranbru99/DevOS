# Kids Mode

Press **Win+K** or run `devos kids`. Move the mouse to create glowing trails in
Little Cosmos. Mouse buttons, scrolling, touch and ordinary keyboard input are
consumed by the overlay. The pointer stays visible. **Ctrl+Shift+K** or
**Win+Shift+K** closes it and returns to the desktop.

This is a separate display overlay. It does not stop, suspend, freeze, restart or
change the priority of other apps. Code generation, downloads, terminals and
services continue normally. Animation runs at 30 frames per second with a bounded
trail; it uses no AI model and makes no network requests.

All monitors are covered. X11 captures the pointer and keyboard with a seat grab;
Plasma Wayland uses GTK layer shell with an exclusive keyboard overlay. Unsupported
desktops or failed input capture refuse activation. This is a play surface, not an
OS security lock: system-level recovery shortcuts remain controlled by the desktop.
