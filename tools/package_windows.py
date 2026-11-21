"""Assemble an x64 Windows distribution with the official Hamlib runtime."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from cw_rig_desk.hamlib_runtime import (
    BINARY_NAME, SOURCE_NAME, VERSION, download_asset, install_binary_archive,
)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = Path("CW_Rig_Desk")


def package(output, cache):
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    binary = download_asset(BINARY_NAME, cache / BINARY_NAME)
    source = download_asset(SOURCE_NAME, cache / SOURCE_NAME)
    project_files = [ROOT / name for name in ("README.md", "README.ru.md", "requirements.txt", "start_windows.bat")]
    project_files.extend((ROOT / "cw_rig_desk").glob("*.py"))
    project_files.extend(path for path in (ROOT / "docs").iterdir() if path.is_file())

    with TemporaryDirectory(dir=output.parent) as scratch:
        vendor = Path(scratch) / "vendor"
        install_binary_archive(binary, vendor)
        stage = Path(scratch) / output.name
        with ZipFile(stage, "w", compression=ZIP_DEFLATED) as z:
            for file in sorted(project_files):
                z.write(file, ARCHIVE_ROOT / file.relative_to(ROOT))
            for file in sorted(vendor.rglob("*")):
                if file.is_file():
                    z.write(file, ARCHIVE_ROOT / "vendor" / file.relative_to(vendor))
            z.write(source, ARCHIVE_ROOT / "third_party" / SOURCE_NAME)
            z.writestr(str(ARCHIVE_ROOT / "third_party" / "Hamlib.txt"), (
                f"Hamlib {VERSION} is bundled as a separate, unmodified upstream Windows distribution.\n"
                "License and copyright notices are in vendor/hamlib-w64-*/.\n"
                f"The corresponding upstream Hamlib source is provided here as {SOURCE_NAME}.\n"
                f"Release: https://github.com/Hamlib/Hamlib/releases/tag/{VERSION}\n"
            ))
        stage.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "CW_Rig_Desk_Windows_x64.zip")
    parser.add_argument("--cache", type=Path, default=ROOT / "dist" / "cache")
    args = parser.parse_args()
    package(args.output.resolve(), args.cache.resolve())


if __name__ == "__main__":
    main()
