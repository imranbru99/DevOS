"""Run inside an isolated Xvfb display; never grabs the user's desktop."""
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]

if '--background' in sys.argv:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib, Gdk
    state = Path(sys.argv[-1])
    window = Gtk.Window(title='Background work')
    window.set_default_size(900, 650)
    window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.SCROLL_MASK)
    def event(_window, evt):
        with (state/'events').open('a') as stream:
            stream.write(str(evt.type)+'\n')
        return True
    for name in ('button-press-event','button-release-event','scroll-event','key-press-event'):
        window.connect(name, event)
    window.add(Gtk.Label(label='Background app stays alive'))
    window.show_all()
    def tick():
        with (state/'heartbeat').open('a') as stream:
            stream.write('.')
        return True
    GLib.timeout_add(100, tick)
    Gtk.main()
    sys.exit()

with tempfile.TemporaryDirectory(prefix='devos-kids-test-') as tmp:
    state = Path(tmp)
    readfd, writefd = os.pipe()
    server = subprocess.Popen(['Xvfb', '-displayfd', str(writefd), '-screen', '0', '1024x768x24', '-nolisten', 'tcp'], pass_fds=[writefd])
    os.close(writefd)
    number = os.read(readfd, 32).decode().strip(); os.close(readfd)
    os.environ['DISPLAY'] = ':'+number
    os.environ['XDG_RUNTIME_DIR'] = tmp
    os.environ['GDK_BACKEND'] = 'x11'
    children = []
    use_wayland = os.environ.get('KIDS_TEST_WAYLAND') == '1'
    if use_wayland:
        compositor = subprocess.Popen(['dbus-run-session', '--', 'kwin_wayland',
            '--x11-display', os.environ['DISPLAY'], '--width', '1024', '--height', '768',
            '--socket', 'kids-wayland', '--no-lockscreen', '--no-kactivities'],
            stdout=open('/tmp/devos-kids-wayland.log', 'w'), stderr=subprocess.STDOUT, start_new_session=True)
        children.append(compositor)
        for _ in range(100):
            if (state/'kids-wayland').exists():
                break
            if compositor.poll() is not None:
                raise RuntimeError('Wayland compositor failed; see /tmp/devos-kids-wayland.log')
            time.sleep(.1)
        os.environ['WAYLAND_DISPLAY'] = 'kids-wayland'
        os.environ['GDK_BACKEND'] = 'wayland'
    def mouse(*args):
        subprocess.run(['xdotool', *args], check=True)
    def events():
        return (state/'events').read_text() if (state/'events').exists() else ''
    def launch():
        p = subprocess.Popen([sys.executable, str(ROOT/'components/kids/kids_mode.py')])
        children.append(p)
        time.sleep(.8)
        assert p.poll() is None, 'Overlay failed to start'
        return p
    try:
        background = subprocess.Popen([sys.executable, __file__, '--background', tmp]); children.append(background)
        time.sleep(.6)
        mouse('mousemove', '200', '200'); mouse('click', '1'); time.sleep(.2)
        assert events(), 'Background click detector is not receiving events'
        before = events()
        overlay = launch()
        count = len((state/'heartbeat').read_text())
        mouse('mousemove', '510', '390')
        for button in ('1', '2', '3', '4', '5', '8', '9'):
            mouse('click', button)
        mouse('key', 'a', 'Return', 'Escape', 'alt+F4')
        time.sleep(.5)
        assert overlay.poll() is None, 'Ordinary keys closed kids mode'
        assert events() == before, 'Input leaked into background app'
        assert len((state/'heartbeat').read_text()) > count+5, 'Background work stopped'
        mouse('mousemove', '620', '460')
        time.sleep(.1)
        # Real rendered screenshot, including mouse trail.
        if not use_wayland:
            import gi
            gi.require_version('Gdk', '3.0')
            from gi.repository import Gdk
            shot = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), 0, 0, 1024, 768)
            import cairo
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1024, 768)
            cr = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(cr, shot, 0, 0); cr.paint()
            surface.write_to_png('/tmp/devos-kids-preview.png')
        mouse('key', 'ctrl+shift+k'); overlay.wait(timeout=3)
        mouse('click', '1'); time.sleep(.2)
        assert len(events()) > len(before), 'Clicks did not return after exit'
        overlay = launch()
        mouse('mousedown', '1'); mouse('key', 'super+shift+k'); time.sleep(.2)
        assert overlay.poll() is None, 'Exited while a mouse gesture was held'
        before = events()
        mouse('mouseup', '1'); overlay.wait(timeout=3)
        assert events() == before, 'Mouse release leaked on exit'
        print('PASS: all clicks/scroll/keys blocked, movement renders, background work continues, both exit shortcuts restore input')
    finally:
        if use_wayland:
            try: os.killpg(compositor.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
        server.terminate(); server.wait(timeout=3)
