import argparse
import os
import subprocess
import sys
from pathlib import Path

import mpy_cross

RUNTIME_MODULES = {
    "app",
    "EEPROM/hexdrive",
    "EEPROM/gps",
    "EEPROM/caffeine",
    "settings_mgr",
    "hexpansion_mgr",
}

files_to_mpy = {Path(f"{module}.py") for module in RUNTIME_MODULES}

files_to_keep = {
    Path("app.py"),
    Path("tildagon.toml"),
    Path("metadata.json"),
    Path("hexpansions.json"),
}
files_to_keep.update({Path(f"{module}.mpy") for module in RUNTIME_MODULES})

def _construct_filepaths(dirname, filenames):
    return [Path(dirname, filename) for filename in filenames]

def find_files(top_level_dir):
    walkerator = iter(os.walk(top_level_dir))
    dirname, _, filenames = next(walkerator)

    all_files = _construct_filepaths(dirname, filenames)

    for dirname, _, filenames  in walkerator:
        # if dirname not in dirs_to_keep:
        if dirname != "./.git" and ".git/" not in dirname:
            all_files.extend(_construct_filepaths(dirname, filenames))

    return all_files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build release artifacts by compiling runtime modules to .mpy and pruning non-release files."
    )
    parser.add_argument("-f", "--force", action="store_true", help="Skip confirmation prompt before file removal.")
    options = parser.parse_args()
    force_mode = options.force
    found_files = set(find_files("."))

    for file in files_to_mpy:
        print(f"Mpy-ing file: {file}")
        mpy_cross.run(file, "-v")

    if not files_to_keep.issubset(found_files):
        raise FileNotFoundError(f"Some of {files_to_keep} are not found so assuming wrong directory. "
                                "Please run this script from HexManager dir.")

    files_to_remove = found_files.difference(files_to_keep)
    if not force_mode:
        if input(f"About to remove {len(files_to_remove)} files from {os.getcwd()}, continue? y/n") != "y":
            print("Aborting file removal")
            exit(0)

    for file in files_to_remove:
        print(f"Removing file: {file}")
        os.remove(file)
