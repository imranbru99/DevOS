# Modern DevOS workspace

The dashboard now uses sapphire surfaces, softer elevation, responsive spacing,
visible keyboard focus, and reduced-motion support. Open **Search DevOS** or press
**Ctrl+K** (Command+K also works) to find installed-app launch actions and dashboard
sections. Use arrow keys and Enter, or click a result. Escape closes the launcher.
App launches continue through the existing server allowlist.

The overview includes a 25-minute focus timer with pause, resume and reset. The
timer uses elapsed wall time so background-tab throttling does not slow it down.
It is local to the current page; reloading resets it. Completion is announced to
assistive technology. It does not change system notifications or power settings.

First-party Qt applications using the shared appearance manager receive common
control spacing, rounded inputs, menu spacing and keyboard-focus outlines.
Application-specific styles retain priority. Dark/light adaptation remains live.
The design token files share the updated corner sizes and dark sapphire palette.

These are source changes, not an installed desktop update or a rebuilt ISO.
Third-party applications and independent Plasma themes retain their own styles.
