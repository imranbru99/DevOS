#!/usr/bin/env python3
"""An input-catching play surface. Never suspends or changes other processes."""
import fcntl
import math
import os
import random
import signal
import sys
import time


def exit_chord(key, shift, control, super_key, alt=False):
    return key.lower() == "k" and shift and (control or super_key) and not alt


def main():
    if '--help' in sys.argv:
        print('Kids mode: Win+K to start; Ctrl+Shift+K or Win+Shift+K to exit. Apps keep running.')
        return 0
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        print('Kids mode needs a desktop session.', file=sys.stderr)
        return 1
    lock = open(os.path.join(runtime, 'devos-kids-mode.lock'), 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    import cairo
    display = Gdk.Display.get_default()
    if display is None:
        print('No desktop display available.', file=sys.stderr)
        return 1
    wayland = 'Wayland' in type(display).__name__
    layer = None
    if wayland:
        gi.require_version('GtkLayerShell', '0.1')
        from gi.repository import GtkLayerShell as layer
        if not layer.is_supported():
            print('This desktop does not support the kids input overlay.', file=sys.stderr)
            return 1
    windows = []
    seat = display.get_default_seat()
    grabbed = False
    pending_exit = False
    pressed_buttons = set()
    start = time.monotonic()
    rng = random.Random(42)
    # 150 rich twinkling stars with distinct color temperatures (warm, cool, violet, amber)
    star_colors = [
        (1.0, 0.95, 0.8),   # warm gold
        (0.8, 0.92, 1.0),   # cyan crystal
        (0.95, 0.82, 1.0),  # soft magenta
        (0.7, 0.85, 1.0),   # deep sky blue
        (1.0, 1.0, 1.0),    # pure white
    ]
    stars = [(rng.random(), rng.random(), rng.uniform(1.0, 3.2), rng.choice(star_colors), rng.uniform(0.5, 3.0), rng.uniform(0, math.tau)) for _ in range(150)]
    # Floating ambient nebula clouds
    nebulae = [
        (0.22, 0.28, 0.42, (0.42, 0.18, 0.72)),   # rich violet
        (0.78, 0.35, 0.38, (0.08, 0.45, 0.75)),   # cyan azure
        (0.50, 0.72, 0.45, (0.75, 0.20, 0.48)),   # deep rose
        (0.85, 0.78, 0.35, (0.15, 0.55, 0.60)),   # teal aurora
    ]
    # Cosmic planetary companions with glowing rings & atmosphere
    planets = [
        # (rel_x, rel_y, radius, primary_rgb, ring_rgb, speed, float_amp, name)
        (0.18, 0.32, 54, (0.35, 0.72, 0.98), (0.70, 0.90, 1.00), 0.35, 14, "Aqua Nova"),
        (0.82, 0.28, 46, (0.98, 0.58, 0.42), (1.00, 0.82, 0.65), 0.42, 11, "Amber Sun"),
        (0.68, 0.76, 62, (0.64, 0.42, 0.95), (0.85, 0.65, 1.00), 0.28, 16, "Violet Mist"),
        (0.28, 0.78, 38, (0.22, 0.85, 0.68), (0.60, 1.00, 0.85), 0.48, 10, "Emerald Moon"),
    ]
    # Gentle background floating jelly-wisps/stardust bubbles
    ambient_orbs = [(rng.random(), rng.random(), rng.uniform(18, 38), rng.uniform(0.15, 0.4), rng.uniform(0, math.tau)) for _ in range(16)]

    def stop(*_):
        nonlocal grabbed
        if grabbed:
            seat.ungrab()
            grabbed = False
        for window in list(windows):
            window.destroy()
        windows.clear()
        Gtk.main_quit()
        return False

    def keypress(_window, event):
        nonlocal pending_exit
        state = event.state
        if exit_chord(Gdk.keyval_name(event.keyval) or '', bool(state & Gdk.ModifierType.SHIFT_MASK),
                      bool(state & Gdk.ModifierType.CONTROL_MASK),
                      bool(state & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK)),
                      bool(state & Gdk.ModifierType.MOD1_MASK)):
            # Finish a held gesture before exposing the desktop, so its release
            # cannot activate a control in an underlying application.
            if pressed_buttons or state & (Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON2_MASK | Gdk.ModifierType.BUTTON3_MASK):
                pending_exit = True
            else:
                stop()
        return True

    def button(_window, event):
        if event.type == Gdk.EventType.BUTTON_RELEASE:
            pressed_buttons.discard(event.button)
            if pending_exit and not pressed_buttons:
                GLib.idle_add(stop)
        else:
            pressed_buttons.add(event.button)
        return True

    def make_window(monitor):
        window = Gtk.Window(title='DevOS Kids Mode')
        window.set_decorated(False)
        window.set_keep_above(True)
        window.set_accept_focus(True)
        window.connect('delete-event', lambda *_: True)
        window.connect('key-press-event', keypress)
        window.connect('key-release-event', lambda *_: True)
        # Consume press AND release (including wheel, extra buttons and touch).
        window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                          Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK |
                          Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.TOUCH_MASK)
        for event in ('button-press-event', 'button-release-event'):
            window.connect(event, button)
        for event in ('scroll-event', 'touch-event'):
            window.connect(event, lambda *_: True)
        points = []
        window.kids_monitor = monitor
        window.kids_points = points
        def motion(_widget, event):
            target, x, y = window, event.x, event.y
            if not wayland:
                for candidate in windows:
                    rect = candidate.kids_monitor.get_geometry()
                    if rect.x <= event.x_root < rect.x+rect.width and rect.y <= event.y_root < rect.y+rect.height:
                        target, x, y = candidate, event.x_root-rect.x, event.y_root-rect.y
                        break
            now_m = time.monotonic()
            # Spawn rainbow sparkling burst when cursor moves
            target.kids_points.append((x, y, now_m, random.uniform(8, 20), (random.random(), random.random(), random.random())))
            del target.kids_points[:-70]
            return True
        window.connect('motion-notify-event', motion)
        area = Gtk.DrawingArea()
        window.add(area)
        def draw(widget, cr):
            width, height = widget.get_allocated_width(), widget.get_allocated_height()
            t = time.monotonic() - start
            now = time.monotonic()

            # 1. Luxurious Deep Aurora / Cosmic Gradient Background
            gradient = cairo.LinearGradient(0, 0, width, height)
            gradient.add_color_stop_rgb(0.00, 0.04, 0.06, 0.16)  # Midnight Abyssal
            gradient.add_color_stop_rgb(0.50, 0.10, 0.08, 0.24)  # Royal Deep Nebula
            gradient.add_color_stop_rgb(1.00, 0.16, 0.07, 0.28)  # Twilight Violet
            cr.set_source(gradient)
            cr.paint()

            # 2. Flowing Luminous Aurora Ribbons
            cr.save()
            for rib_idx, (r_col, base_y_pct, wave_spd) in enumerate([
                ((0.15, 0.65, 0.85), 0.38, 0.40),
                ((0.55, 0.22, 0.80), 0.52, 0.30),
                ((0.10, 0.80, 0.60), 0.65, 0.45)
            ]):
                cr.set_source_rgba(r_col[0], r_col[1], r_col[2], 0.08 + 0.04 * math.sin(t * 0.5 + rib_idx))
                cr.new_path()
                cr.move_to(0, height)
                step = 40
                for sx in range(0, int(width) + step, step):
                    sy = height * base_y_pct + math.sin(t * wave_spd + sx * 0.004 + rib_idx) * 60 + math.cos(t * wave_spd * 0.7 + sx * 0.002) * 35
                    cr.line_to(sx, sy)
                cr.line_to(width, height)
                cr.close_path()
                cr.fill()
            cr.restore()

            # 3. Soft Radial Ambient Nebula Glows
            for nx, ny, nrad, (nr, ng, nb) in nebulae:
                cx = width * nx + math.sin(t * 0.25 + nx * 10) * 30
                cy = height * ny + math.cos(t * 0.20 + ny * 10) * 25
                rad_px = min(width, height) * nrad
                rad_glow = cairo.RadialGradient(cx, cy, 0, cx, cy, rad_px)
                rad_glow.add_color_stop_rgba(0.0, nr, ng, nb, 0.24)
                rad_glow.add_color_stop_rgba(0.5, nr, ng, nb, 0.08)
                rad_glow.add_color_stop_rgba(1.0, nr, ng, nb, 0.00)
                cr.set_source(rad_glow)
                cr.paint()

            # 4. Floating Gentle Stardust Orbs (Foreground atmosphere)
            for ox, oy, orad, ospd, ophase in ambient_orbs:
                px = (width * ox + math.sin(t * ospd + ophase) * 60) % width
                py = (height * oy + math.cos(t * ospd * 0.8 + ophase) * 50) % height
                orb_grad = cairo.RadialGradient(px, py, 0, px, py, orad)
                orb_grad.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.25)
                orb_grad.add_color_stop_rgba(0.4, 0.6, 0.8, 1.0, 0.12)
                orb_grad.add_color_stop_rgba(1.0, 0.3, 0.5, 0.9, 0.00)
                cr.set_source(orb_grad)
                cr.arc(px, py, orad, 0, math.tau)
                cr.fill()

            # 5. Brilliant Twinkling 4-Point & Circular Diamond Stars
            for sx, sy, srad, (sr, sg, sb), spd, sphase in stars:
                twinkle = 0.35 + 0.55 * (0.5 + 0.5 * math.sin(t * spd + sphase))
                px, py = sx * width, sy * height
                cr.set_source_rgba(sr, sg, sb, twinkle)
                if srad > 2.4:
                    # Diamond 4-point sparkle for larger stars
                    cr.new_path()
                    cr.move_to(px, py - srad * 2.8)
                    cr.line_to(px + srad * 0.7, py)
                    cr.line_to(px, py + srad * 2.8)
                    cr.line_to(px - srad * 0.7, py)
                    cr.close_path()
                    cr.fill()
                    cr.new_path()
                    cr.move_to(px - srad * 2.8, py)
                    cr.line_to(px, py + srad * 0.7)
                    cr.line_to(px + srad * 2.8, py)
                    cr.line_to(px, py - srad * 0.7)
                    cr.close_path()
                    cr.fill()
                cr.arc(px, py, srad, 0, math.tau)
                cr.fill()

            # 6. Premium Cosmic Characters / Cute Floating Planets
            for i, (rel_x, rel_y, rad, (pr, pg, pb), (rr, rg, rb), pspd, pamp, pname) in enumerate(planets):
                px = width * rel_x + math.sin(t * 0.3 + i * 2.1) * 20
                py = height * rel_y + math.sin(t * pspd + i * 1.5) * pamp

                # Soft outer atmospheric halo
                halo = cairo.RadialGradient(px, py, rad * 0.8, px, py, rad * 1.55)
                halo.add_color_stop_rgba(0.0, pr, pg, pb, 0.40)
                halo.add_color_stop_rgba(1.0, pr, pg, pb, 0.00)
                cr.set_source(halo)
                cr.arc(px, py, rad * 1.55, 0, math.tau)
                cr.fill()

                # Tilted Planetary Ring (Back Half)
                cr.save()
                cr.translate(px, py)
                cr.rotate(-0.35 + math.sin(t * 0.2 + i) * 0.08)
                cr.scale(1.0, 0.32)
                cr.set_source_rgba(rr, rg, rb, 0.55)
                cr.set_line_width(rad * 0.28)
                cr.arc(0, 0, rad * 1.50, math.pi, math.tau)
                cr.stroke()
                cr.restore()

                # Spherical Lit Planet Body with Shading & Specular Highlights
                sphere = cairo.RadialGradient(px - rad * 0.35, py - rad * 0.35, rad * 0.1, px, py, rad)
                sphere.add_color_stop_rgb(0.0, min(1.0, pr * 1.35), min(1.0, pg * 1.35), min(1.0, pb * 1.35))
                sphere.add_color_stop_rgb(0.65, pr, pg, pb)
                sphere.add_color_stop_rgb(1.0, pr * 0.35, pg * 0.35, pb * 0.35)
                cr.set_source(sphere)
                cr.arc(px, py, rad, 0, math.tau)
                cr.fill()

                # Tilted Planetary Ring (Front Half)
                cr.save()
                cr.translate(px, py)
                cr.rotate(-0.35 + math.sin(t * 0.2 + i) * 0.08)
                cr.scale(1.0, 0.32)
                cr.set_source_rgba(rr, rg, rb, 0.85)
                cr.set_line_width(rad * 0.28)
                cr.arc(0, 0, rad * 1.50, 0, math.pi)
                cr.stroke()
                cr.restore()

                # Friendly Kawaii Face on Planet
                eye_dist = rad * 0.28
                eye_y = py - rad * 0.05
                # Eyes
                cr.set_source_rgb(0.08, 0.10, 0.18)
                for edx in (-eye_dist, eye_dist):
                    cr.arc(px + edx, eye_y, max(2.5, rad * 0.085), 0, math.tau)
                    cr.fill()
                    # Eye twinkle
                    cr.set_source_rgb(1.0, 1.0, 1.0)
                    cr.arc(px + edx - 1, eye_y - 1.5, max(1.0, rad * 0.035), 0, math.tau)
                    cr.fill()
                    cr.set_source_rgb(0.08, 0.10, 0.18)
                # Cheeks (Blushing)
                cr.set_source_rgba(1.0, 0.45, 0.55, 0.45)
                for edx in (-eye_dist * 1.45, eye_dist * 1.45):
                    cr.arc(px + edx, eye_y + rad * 0.12, rad * 0.09, 0, math.tau)
                    cr.fill()
                # Happy smile
                cr.set_source_rgb(0.08, 0.10, 0.18)
                cr.set_line_width(max(2.0, rad * 0.05))
                cr.arc(px, eye_y + rad * 0.08, rad * 0.18, 0.2, math.pi - 0.2)
                cr.stroke()

            # 7. Magical Mouse Particle Burst & Shooting Stars
            points[:] = [p for p in points if now - p[2] < 1.4]
            for i, pitem in enumerate(points):
                px, py, born = pitem[0], pitem[1], pitem[2]
                prad = pitem[3] if len(pitem) > 3 else 12
                pcol = pitem[4] if len(pitem) > 4 else (0.8, 0.9, 1.0)
                life = 1.0 - (now - born) / 1.4
                if life <= 0:
                    continue
                # Glow particle
                pglow = cairo.RadialGradient(px, py - (1.0 - life) * 40, 0, px, py - (1.0 - life) * 40, prad * life * 1.5)
                pglow.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, life * 0.95)
                pglow.add_color_stop_rgba(0.35, pcol[0], pcol[1], pcol[2], life * 0.70)
                pglow.add_color_stop_rgba(1.0, pcol[0], pcol[1], pcol[2], 0.00)
                cr.set_source(pglow)
                cr.arc(px, py - (1.0 - life) * 40, prad * life * 1.5, 0, math.tau)
                cr.fill()
                # Sparkling mini core star
                cr.set_source_rgba(1.0, 1.0, 1.0, life * 0.95)
                cr.arc(px, py - (1.0 - life) * 40, max(1.5, prad * life * 0.35), 0, math.tau)
                cr.fill()

            # 8. Premium Glassmorphic Central Title Badge
            center_w = min(560.0, width * 0.80)
            center_h = 130.0
            bx = (width - center_w) / 2
            by = height * 0.44

            # Glass card backdrop
            cr.save()
            # Shadow
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.35)
            cr.rectangle(bx + 4, by + 6, center_w, center_h)
            cr.fill()
            # Frosted glass pill
            b_grad = cairo.LinearGradient(bx, by, bx, by + center_h)
            b_grad.add_color_stop_rgba(0.0, 0.25, 0.30, 0.50, 0.42)
            b_grad.add_color_stop_rgba(1.0, 0.10, 0.12, 0.25, 0.58)
            cr.set_source(b_grad)
            cr.arc(bx + 24, by + 24, 24, math.pi, math.pi * 1.5)
            cr.arc(bx + center_w - 24, by + 24, 24, math.pi * 1.5, math.tau)
            cr.arc(bx + center_w - 24, by + center_h - 24, 24, 0, math.pi * 0.5)
            cr.arc(bx + 24, by + center_h - 24, 24, math.pi * 0.5, math.pi)
            cr.close_path()
            cr.fill()

            # Elegant Glowing Cyan-Violet Border
            border_grad = cairo.LinearGradient(bx, by, bx + center_w, by + center_h)
            border_grad.add_color_stop_rgba(0.0, 0.45, 0.85, 1.0, 0.65)
            border_grad.add_color_stop_rgba(0.5, 0.85, 0.50, 1.0, 0.45)
            border_grad.add_color_stop_rgba(1.0, 0.30, 0.60, 1.0, 0.65)
            cr.set_source(border_grad)
            cr.set_line_width(1.8)
            cr.arc(bx + 24, by + 24, 24, math.pi, math.pi * 1.5)
            cr.arc(bx + center_w - 24, by + 24, 24, math.pi * 1.5, math.tau)
            cr.arc(bx + center_w - 24, by + center_h - 24, 24, 0, math.pi * 0.5)
            cr.arc(bx + 24, by + center_h - 24, 24, math.pi * 0.5, math.pi)
            cr.close_path()
            cr.stroke()
            cr.restore()

            # Badge Typography
            cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(34)
            text1 = '✨ Little Cosmos'
            ext1 = cr.text_extents(text1)
            # Text glow
            cr.set_source_rgba(0.4, 0.75, 1.0, 0.45)
            cr.move_to((width - ext1.width) / 2 + 1, by + 53)
            cr.show_text(text1)
            # Text crisp
            cr.set_source_rgb(0.97, 0.98, 1.0)
            cr.move_to((width - ext1.width) / 2, by + 52)
            cr.show_text(text1)

            cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(16)
            cr.set_source_rgba(0.85, 0.92, 1.0, 0.85)
            text2 = 'Move the mouse • Create stardust and sparkling trails'
            ext2 = cr.text_extents(text2)
            cr.move_to((width - ext2.width) / 2, by + 94)
            cr.show_text(text2)

            # 9. Bottom Floating Helper Pill with DevOS Theme
            foot_w = min(620.0, width - 48)
            foot_h = 38.0
            fx = (width - foot_w) / 2
            fy = height - 52.0

            cr.save()
            cr.set_source_rgba(0.05, 0.08, 0.18, 0.70)
            cr.arc(fx + 19, fy + 19, 18, math.pi * 0.5, math.pi * 1.5)
            cr.arc(fx + foot_w - 19, fy + 19, 18, -math.pi * 0.5, math.pi * 0.5)
            cr.close_path()
            cr.fill()

            cr.set_source_rgba(0.35, 0.55, 0.90, 0.35)
            cr.set_line_width(1.2)
            cr.arc(fx + 19, fy + 19, 18, math.pi * 0.5, math.pi * 1.5)
            cr.arc(fx + foot_w - 19, fy + 19, 18, -math.pi * 0.5, math.pi * 0.5)
            cr.close_path()
            cr.stroke()

            cr.set_font_size(13)
            cr.set_source_rgba(0.88, 0.93, 1.0, 0.85)
            foot_txt = '🛡️ Kids mode active • Safe clicks locked • To exit: Ctrl+Shift+K or Win+Shift+K'
            fext = cr.text_extents(foot_txt)
            cr.move_to((width - fext.width) / 2, fy + 24)
            cr.show_text(foot_txt)
            cr.restore()

            return False
        area.connect('draw', draw)
        if layer:
            layer.init_for_window(window)
            layer.set_namespace(window, 'devos-kids-mode')
            layer.set_layer(window, layer.Layer.OVERLAY)
            layer.set_monitor(window, monitor)
            for edge in (layer.Edge.TOP, layer.Edge.BOTTOM, layer.Edge.LEFT, layer.Edge.RIGHT):
                layer.set_anchor(window, edge, True)
            layer.set_keyboard_mode(window, layer.KeyboardMode.EXCLUSIVE)
        else:
            geometry = monitor.get_geometry()
            window.move(geometry.x, geometry.y)
            window.set_default_size(geometry.width, geometry.height)
            window.fullscreen_on_monitor(display.get_default_screen(),
                                         next(i for i in range(display.get_n_monitors()) if display.get_monitor(i) == monitor))
        windows.append(window)
        window.show_all()
        window.get_window().set_cursor(Gdk.Cursor.new_from_name(display, 'default'))
        return window

    for i in range(display.get_n_monitors()):
        make_window(display.get_monitor(i))
    if not windows:
        return 1
    if not wayland:
        # Allow the X11 server to map and realize the window before acquiring the grab
        for _ in range(20):
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if windows[0].get_window() and windows[0].get_window().is_visible():
                break
            time.sleep(0.02)
        result = Gdk.GrabStatus.FAILED
        for attempt in range(10):
            result = seat.grab(windows[0].get_window(), Gdk.SeatCapabilities.ALL, False, None, None, None, None)
            if result == Gdk.GrabStatus.SUCCESS:
                break
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.05)
        if result != Gdk.GrabStatus.SUCCESS:
            for window in windows:
                window.destroy()
            print('Kids mode could not capture input; close any open menu and try again.', file=sys.stderr)
            return 1
        grabbed = True
    def monitor_added(_display, monitor):
        make_window(monitor)
    # Do not expose a newly attached screen while active.
    display.connect('monitor-added', monitor_added)
    def monitor_removed(_display, monitor):
        nonlocal grabbed
        removed = [w for w in windows if w.kids_monitor == monitor]
        remaining = [w for w in windows if w.kids_monitor != monitor]
        if not remaining:
            stop()
            return
        if grabbed:
            # Transfer the grab before destroying the removed monitor's window.
            result = seat.grab(remaining[0].get_window(), Gdk.SeatCapabilities.ALL, False, None, None, None, None)
            if result != Gdk.GrabStatus.SUCCESS:
                stop()
                return
        for window in removed:
            windows.remove(window)
            window.destroy()
    display.connect('monitor-removed', monitor_removed)
    def tick():
        for window in windows:
            window.queue_draw()
        return bool(windows)
    GLib.timeout_add(33, tick)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    try:
        Gtk.main()
    finally:
        if grabbed:
            seat.ungrab()
        for window in windows:
            window.destroy()
    return 0


if __name__ == '__main__':
    sys.exit(main())
