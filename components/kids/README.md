# Kids Mode

Press **Win+K** or run `devos kids`. Move the mouse to create glowing trails in
Little Cosmos. Mouse buttons, scrolling, touch and ordinary keyboard input are
consumed by the overlay. The pointer stays visible.

**Exit:** **Ctrl+Shift+K** or **Win+Shift+K**. When a parent PIN is set, that
chord alone is not enough — DevOS asks for the PIN first.

```sh
devos parental set-pin      # 4–12 digits
devos parental status
devos parental clear-pin
```

Family Safety → **Set Kids Mode PIN…** does the same from the GUI.

This is a separate display overlay. It does not stop, suspend, freeze, restart or
change the priority of other apps. Code generation, downloads, terminals and
services continue normally. Animation runs at 30 frames per second with a bounded
trail; it uses no AI model and makes no network requests.

All monitors are covered. X11 captures the pointer and keyboard with a seat grab;
Plasma Wayland uses GTK layer shell with an exclusive keyboard overlay. Unsupported
desktops or failed input capture refuse activation.

With a parent PIN it is a stronger child gate than before, but it is still not a
full locked child OS account — pair it with Family Safety and a non-admin child
login for best results.
