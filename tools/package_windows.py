"""Build a versioned, standalone Windows x64 executable with Hamlib."""

import argparse
from importlib.util import find_spec
from pathlib import Path
import re
from shutil import copy2
from struct import calcsize
import subprocess
import sys

from cw_rig_desk import __version__
from cw_rig_desk.hamlib_runtime import BINARY_NAME, SOURCE_NAME, download_asset, install_binary_archive

ROOT = Path(__file__).resolve().parents[1]


def version_resource(path, name):
    parts = tuple(map(int, __version__.split("."))) + (0,)
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts}, prodvers={parts}, mask=0x3f,
                    flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904b0', [
      StringStruct('FileDescription', 'CW Rig Desk'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', 'CW Rig Desk'),
      StringStruct('ProductVersion', '{__version__}')
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def package(output, cache):
    if sys.platform != "win32" or calcsize("P") != 8:
        raise SystemExit("Build the Windows x64 executable on Windows using a 64-bit Python.")
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", __version__):
        raise SystemExit("Set a MAJOR.MINOR.PATCH version in cw_rig_desk/__init__.py.")

    name = f"CW_Rig_Desk-{__version__}-windows-x64"
    cache.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build" / "windows"
    work.mkdir(parents=True, exist_ok=True)
    binary = download_asset(BINARY_NAME, cache / BINARY_NAME)
    source = download_asset(SOURCE_NAME, cache / SOURCE_NAME)
    install_binary_archive(binary, work / "vendor")
    resource = work / "version-info.txt"
    version_resource(resource, name)

    sounddevice_dir = Path(find_spec("sounddevice").origin).parent
    portaudio_dir = sounddevice_dir / "_sounddevice_data" / "portaudio-binaries"
    portaudio_dlls = sorted(portaudio_dir.glob("libportaudio64bit*.dll"))
    if not portaudio_dlls:
        raise SystemExit("The Windows sounddevice wheel is missing its PortAudio x64 DLL.")
    portaudio_args = []
    for library in portaudio_dlls:
        portaudio_args.extend(("--add-binary", f"{library}:_sounddevice_data/portaudio-binaries"))

    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--noupx", "--name", name, "--paths", str(ROOT),
        "--distpath", str(output), "--workpath", str(work / "pyinstaller"),
        "--specpath", str(work), "--version-file", str(resource),
        "--add-data", f"{work / 'vendor'}:vendor",
        "--add-data", f"{source}:third_party",
        "--add-data", f"{Path(sys.base_prefix) / 'LICENSE.txt'}:third_party/python",
        "--copy-metadata", "numpy", "--copy-metadata", "pyserial",
        "--copy-metadata", "sounddevice", "--copy-metadata", "websocket-client",
        "--copy-metadata", "cffi",
        *portaudio_args,
        str(ROOT / "cw_rig_desk" / "__main__.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    copy2(source, output)
    copy2(ROOT / "docs" / "CW_Rig_Desk_User_Guide_RU.pdf", output)
    return output / f"{name}.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--cache", type=Path, default=ROOT / "dist" / "cache")
    args = parser.parse_args()
    print(package(args.output.resolve(), args.cache.resolve()))


if __name__ == "__main__":
    main()
