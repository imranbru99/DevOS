"""Live light-mode adaptation for legacy first-party Qt stylesheets."""
import colorsys
import json
import os
from pathlib import Path
import re
from PyQt5 import QtCore, QtGui, QtWidgets

COLOR = re.compile(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|\b(?:white|black)\b')


def light_stylesheet(sheet):
    """Translate explicit chrome colors by role, preserving colored action buttons."""
    def block(match):
        body = match.group(1)
        background = re.search(r'(?:^|;)\s*background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6})', body)
        strong = False
        if background:
            c = QtGui.QColor(background.group(1))
            strong = c.hsvSaturationF() > .55 and c.valueF() > .4
        def declaration(m):
            prop, value = m.group(1), m.group(2)
            def color(cm):
                c = QtGui.QColor(cm.group())
                h, sat, val, _ = c.getHsvF()
                if prop.startswith('background') or prop == 'selection-background-color':
                    if sat > .55 and val > .4:
                        return cm.group()
                    return '#ffffff' if val < .13 else '#f1f5f9' if val < .25 else '#e2e8f0' if val < .5 else cm.group()
                if prop == 'color' or prop == 'selection-color':
                    if strong: return '#ffffff'
                    if sat > .5 and val > .55:
                        r,g,b=colorsys.hsv_to_rgb(max(0,h),max(.6,sat),.62)
                        return QtGui.QColor.fromRgbF(r,g,b).name()
                    return '#172438' if val > .75 else '#475569' if val > .35 else '#172438'
                if prop.startswith('border'):
                    return '#2563eb' if sat > .55 and val > .55 else '#cbd5e1'
                return cm.group()
            return prop + ': ' + COLOR.sub(color,value) + ';'
        return '{' + re.sub(r'([\w-]+)\s*:\s*([^;{}]+);?', declaration, body) + '}'
    # Inline widget styles have no selector; process them as one declaration block.
    if '{' not in sheet:
        return light_stylesheet('QWidget {'+sheet+'}').split('{',1)[1].rsplit('}',1)[0]
    return re.sub(r'\{([^{}]*)\}', block, sheet)


def current_mode():
    base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))
    # Honor changes made in KDE Settings as well as the DevOS theme command.
    try:
        text=(base/'kdeglobals').read_text().lower()
        match=re.search(r'^colorscheme\s*=\s*(.+)$',text,re.M)
        if match:
            scheme=match.group(1).strip()
            if 'light' in scheme or scheme=='breeze':return 'light'
            if 'dark' in scheme or scheme=='devos':return 'dark'
    except OSError:pass
    try:
        mode=json.loads((base/'devos/settings.json').read_text()).get('appearance',{}).get('theme')
        if mode in ('dark','light','mac','mac-light'):return mode
    except (OSError,ValueError,TypeError):pass
    return 'dark'


class Appearance(QtCore.QObject):
    def __init__(self,app):
        super().__init__(app)
        self.app=app;self.busy=False;self.mode=current_mode();self.app_source=None;self.app_rendered=None
        self.watcher=QtCore.QFileSystemWatcher(self)
        self.debounce=QtCore.QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(100)
        self.debounce.timeout.connect(self.refresh)
        self.watcher.fileChanged.connect(lambda _:self.debounce.start())
        self.watcher.directoryChanged.connect(lambda _:self.debounce.start())
        self.watch()

    def watch(self):
        base=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
        for p in (base,base/'devos',base/'devos/settings.json',base/'kdeglobals'):
            if p.exists() and str(p) not in self.watcher.files()+self.watcher.directories():self.watcher.addPath(str(p))

    def style(self,widget):
        current=widget.styleSheet()
        rendered=widget.property('_devosRenderedStyle')
        source=widget.property('_devosSourceStyle')
        if source is None or current != rendered:source=current
        result=light_stylesheet(source) if self.mode in ('light','mac-light') and source else source
        widget.setProperty('_devosSourceStyle',source);widget.setProperty('_devosRenderedStyle',result)
        if current!=result:widget.setStyleSheet(result)

    def sync_app(self):
        current=self.app.styleSheet()
        if self.app_source is None or current!=self.app_rendered:self.app_source=current
        result=light_stylesheet(self.app_source) if self.mode in ('light','mac-light') and self.app_source else self.app_source
        self.app_rendered=result
        if current!=result:self.app.setStyleSheet(result)

    def refresh(self):
        self.watch();mode=current_mode()
        if mode==self.mode:return
        self.mode=mode;self.busy=True
        try:
            self.sync_app()
            for widget in self.app.allWidgets():self.style(widget)
        finally:self.busy=False

    def eventFilter(self,widget,event):
        if not self.busy and isinstance(widget,QtWidgets.QWidget) and (event.type() == QtCore.QEvent.Show or (event.type() == QtCore.QEvent.StyleChange and widget.isVisible())):
            self.busy=True
            try:
                self.sync_app();self.style(widget)
            finally:self.busy=False
        return False


def install(app):
    if not hasattr(app,'_devos_appearance'):
        app._devos_appearance=Appearance(app)
        app.installEventFilter(app._devos_appearance)
