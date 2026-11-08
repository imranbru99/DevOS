"""Plasma discovers packages by previews but resolves images by WxH filenames."""
import importlib.util
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = ROOT / 'tools/wallpapers/premium-collection'


def test_every_shipped_package_has_a_resolution_named_original():
    manifest = json.loads((COLLECTION/'manifest.json').read_text())
    assert len(manifest) == 20
    for item in manifest:
        package = ROOT/'build/includes.chroot/usr/share/wallpapers'/item['package']
        legacy = package/'contents/images/wallpaper.png'
        with Image.open(legacy) as image:
            expected = package/f'contents/images/{image.width}x{image.height}.png'
        assert expected.is_file(), f'Plasma cannot resolve {package.name}'
        assert expected.read_bytes() == legacy.read_bytes()


def test_packager_uses_actual_dimensions_and_keeps_old_direct_links(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('premium_package', COLLECTION/'package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    image = tmp_path/'source.png'
    Image.new('RGB', (64, 36), '#b56c22').save(image)
    (tmp_path/'manifest.json').write_text(json.dumps([{'id':'16','name':'Quiet Mesh','package':'TestWallpaper','source':'source.png'}]))
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'HERE', tmp_path)
    monkeypatch.setattr(module, 'DEST', tmp_path/'packages')
    module.main()
    images = tmp_path/'packages/TestWallpaper/contents/images'
    assert (images/'64x36.png').read_bytes() == image.read_bytes()
    assert (images/'wallpaper.png').read_bytes() == image.read_bytes()
    assert 'contents/images/64x36.png' in (tmp_path/'gallery.html').read_text()
    module.main()  # Repackaging remains safe and reproducible.


def test_installer_refreshes_failed_selection_then_uses_package_url(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('premium_install', COLLECTION/'install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((COLLECTION/'manifest.json').read_text())
    selected = next(item for item in manifest if item['id'] == '16')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.setattr('sys.argv', ['install.py', '--select', '16'])
    monkeypatch.setattr(module.shutil, 'copytree', lambda *a, **kw: None)
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/usr/bin/qdbus6')
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    calls = []
    monkeypatch.setattr(module.subprocess, 'run', lambda args, **kwargs: calls.append(args))
    module.main()
    assert len(calls) == 2
    sized = f"{selected['width']}x{selected['height']}.png"
    assert sized in calls[0][-1]
    target = (tmp_path/'wallpapers'/selected['package']).as_uri() + '/'
    assert f'd.writeConfig("Image",{json.dumps(target)})' in calls[1][-1]
