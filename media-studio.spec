# Build with: python -m PyInstaller media-studio.spec
from pathlib import Path

project = Path(SPECPATH)
bundled = project / "bin"
data = [(str(project / "media_studio" / "gui" / "assets"), "media_studio/gui/assets")]
if bundled.is_dir():
    data.append((str(bundled), "bin"))

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Media Studio",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Media Studio")
if __import__("sys").platform == "darwin":
    app = BUNDLE(collection, name="Media Studio.app", bundle_identifier="org.mediastudio.desktop",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "0.1.0"})
