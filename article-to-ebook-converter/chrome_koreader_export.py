#!/usr/bin/env python3
"""
chrome_koreader_export.py
==========================

Finds every Chrome bookmark folder with a chosen name (default "koreader",
case-insensitive, any number of them, anywhere in the bookmark tree of a
chosen profile), combines all the bookmarks (websites) inside them into one
CSV file (urls.csv) in your Downloads folder, and optionally empties those
folders (the folders themselves stay - they just lose their bookmarks) so you
can keep dropping new ones in.

The CSV is written as "urls.csv" (no timestamp) so it can be picked up
directly by article_to_ebook_converter.py.

USAGE
-----
    python chrome_koreader_export.py
    (Windows: py chrome_koreader_export.py  or  python chrome_koreader_export.py)

This also works when packaged as a standalone executable, e.g.:
    pyinstaller --onefile --console --name "Chrome KOReader Export" chrome_koreader_export.py

BEFORE YOU RUN THIS
--------------------
  * Close Chrome completely first. Chrome periodically rewrites its
    "Bookmarks" file, so if Chrome is open while this script edits that
    file, your changes can be lost or overwritten.
  * A timestamped backup of the Bookmarks file is made automatically, right
    next to the original, before anything is changed.

SETTINGS
--------
Your choices (Chrome profile, bookmark folder name, whether to empty the
folder afterwards) are saved to a small config.json file so you aren't asked
every time. Before each run you'll get a chance to change any of them,
defaulting to whatever you used last time. The default folder name and the
number of example sites shown per profile can still be changed below.
"""

import csv
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------

DEFAULT_TARGET_FOLDER_NAME = "koreader"  # default folder name (case-insensitive)
SAMPLE_COUNT = 8                         # how many example sites to show per profile

CHROME_EPOCH = dt.datetime(1601, 1, 1)


# ---------------------------------------------------------------------
# Persistent settings (works for `python script.py` and a frozen exe)
# ---------------------------------------------------------------------

APP_CONFIG_NAME = "ChromeKOReaderExport"


def get_config_dir() -> Path:
    """Return the per-user application config directory (created if needed).

    Uses the same native locations as article_to_ebook_converter.py
    (%APPDATA% on Windows, ~/Library/Application Support on macOS,
    $XDG_CONFIG_HOME or ~/.config on Linux), so it works identically
    whether this is run with `python chrome_koreader_export.py` or as a
    PyInstaller --onefile executable.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        config_dir = Path(base) / APP_CONFIG_NAME
    elif sys.platform == "darwin":
        config_dir = Path.home() / "Library" / "Application Support" / APP_CONFIG_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
        config_dir = Path(base) / APP_CONFIG_NAME

    return config_dir


def get_config_path() -> Path:
    """Return the full path to the config.json file."""
    return get_config_dir() / "config.json"


def load_config() -> dict:
    """Load saved settings, or return {} if missing/unreadable."""
    config_path = get_config_path()
    try:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        # Corrupt or unreadable config should never crash the app.
        pass
    return {}


def save_config(config: dict) -> None:
    """Persist settings to disk."""
    try:
        config_dir = get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save settings: {e}")


# ---------------------------------------------------------------------
# Locating Chrome's data
# ---------------------------------------------------------------------

def get_chrome_user_data_dir() -> Path:
    """Return Chrome's 'User Data' folder for this OS.

    Set the CHROME_USER_DATA_DIR environment variable to override this if
    Chrome is installed somewhere non-standard (portable install, custom
    --user-data-dir, etc.).
    """
    override = os.environ.get("CHROME_USER_DATA_DIR")
    if override:
        return Path(override)

    home = Path.home()
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        return Path(base) / "Google" / "Chrome" / "User Data"
    elif system == "Darwin":
        return home / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        return home / ".config" / "google-chrome"


def get_downloads_dir() -> Path:
    """Return the OS's default Downloads directory (created if needed).

    Mirrors get_downloads_folder() in article_to_ebook_converter.py so the
    urls.csv this script writes ends up exactly where that script looks for
    it.
    """
    if sys.platform == "win32":
        try:
            import winreg
            sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                downloads_path = winreg.QueryValueEx(
                    key, "{374DE290-123F-4565-9164-39C4925E467B}"
                )[0]
                return Path(downloads_path)
        except Exception:
            return Path.home() / "Downloads"
    elif sys.platform == "darwin":
        return Path.home() / "Downloads"
    else:
        try:
            xdg_config = Path.home() / ".config" / "user-dirs.dirs"
            if xdg_config.exists():
                with open(xdg_config, "r") as f:
                    for line in f:
                        if "XDG_DOWNLOAD_DIR" in line:
                            path = line.split("=")[1].strip().strip('"')
                            path = path.replace("$HOME", str(Path.home()))
                            return Path(path)
        except Exception:
            pass
        return Path.home() / "Downloads"


def is_chrome_running() -> bool:
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.check_output(["tasklist"], stderr=subprocess.DEVNULL, text=True)
            return "chrome.exe" in out.lower()
        elif system == "Darwin":
            out = subprocess.check_output(["pgrep", "-x", "Google Chrome"],
                                           stderr=subprocess.DEVNULL, text=True)
            return bool(out.strip())
        else:
            # Match against process name only (not -f / full command line) so
            # this check doesn't match its own "pgrep ... chrome" invocation.
            out = subprocess.check_output(["pgrep", "-i", "chrome"],
                                           stderr=subprocess.DEVNULL, text=True)
            return bool(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------
# Reading profiles & bookmark trees
# ---------------------------------------------------------------------

def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_profiles(user_data_dir: Path):
    if not user_data_dir.exists():
        return []
    return [p for p in sorted(user_data_dir.iterdir())
            if p.is_dir() and (p / "Bookmarks").exists()]


def get_profile_display_names(user_data_dir: Path) -> dict:
    """folder name -> 'Display Name - email' from Local State, if available."""
    names = {}
    local_state_path = user_data_dir / "Local State"
    if not local_state_path.exists():
        return names
    try:
        data = load_json(local_state_path)
        for folder, info in data.get("profile", {}).get("info_cache", {}).items():
            parts = [p for p in (info.get("name"), info.get("user_name")) if p]
            if parts:
                names[folder] = " - ".join(parts)
    except Exception:
        pass
    return names


def iter_nodes(node):
    yield node
    for child in node.get("children", []):
        yield from iter_nodes(child)


def extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else (netloc or url)
    except Exception:
        return url


def collect_sample_domains(bookmarks_data, limit=SAMPLE_COUNT):
    samples, seen = [], set()
    for root_key in ("bookmark_bar", "other", "synced"):
        root = bookmarks_data.get("roots", {}).get(root_key)
        if not root:
            continue
        for node in iter_nodes(root):
            if node.get("type") == "url":
                domain = extract_domain(node.get("url", ""))
                if domain and domain not in seen:
                    seen.add(domain)
                    samples.append(domain)
                    if len(samples) >= limit:
                        return samples
    return samples


# ---------------------------------------------------------------------
# Finding / exporting / clearing target folders
# ---------------------------------------------------------------------

def find_target_folders(node, path, target_name):
    """Find every descendant folder named target_name (case-insensitive).

    Once a folder matches, its subtree is not searched further for
    additional matches (it's treated as one unit - see collect_urls).
    """
    results = []
    target_lower = target_name.lower()
    for child in node.get("children", []):
        if child.get("type") != "folder":
            continue
        child_path = f"{path}/{child.get('name', '')}"
        if child.get("name", "").strip().lower() == target_lower:
            results.append((child, child_path))
        else:
            results.extend(find_target_folders(child, child_path, target_name))
    return results


def collect_urls(folder_node, folder_path):
    """Recursively collect (url_node, containing_folder_path) for every
    bookmark inside folder_node, including any nested sub-folders."""
    urls = []
    for child in folder_node.get("children", []):
        if child.get("type") == "url":
            urls.append((child, folder_path))
        elif child.get("type") == "folder":
            urls.extend(collect_urls(child, f"{folder_path}/{child.get('name', '')}"))
    return urls


def strip_urls(folder_node):
    """Remove all bookmark (url) entries recursively; keep folder entries
    (which may now be empty), so the folder structure stays intact."""
    kept = []
    for child in folder_node.get("children", []):
        if child.get("type") == "url":
            continue
        if child.get("type") == "folder":
            strip_urls(child)
        kept.append(child)
    folder_node["children"] = kept


# ---------------------------------------------------------------------
# Checksum - Chrome stores an MD5 of the bookmark tree to detect
# externally-modified files.
# ---------------------------------------------------------------------

def _checksum_node(node, md5):
    md5.update(str(node.get("id", "")).encode("utf-8"))
    md5.update(node.get("name", "").encode("utf-8"))
    if node.get("type") == "url":
        md5.update(b"url")
        md5.update(node.get("url", "").encode("utf-8"))
    else:
        md5.update(b"folder")
        for child in node.get("children", []):
            _checksum_node(child, md5)


def compute_checksum(data) -> str:
    md5 = hashlib.md5()
    roots = data.get("roots", {})
    for key in ("bookmark_bar", "other", "synced"):
        root = roots.get(key)
        if root:
            _checksum_node(root, md5)
    return md5.hexdigest()


def chrome_time_to_str(value) -> str:
    try:
        micros = int(value)
        if micros <= 0:
            return ""
        return (CHROME_EPOCH + dt.timedelta(microseconds=micros)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError):
        return ""


def resolve_saved_profile(listed, saved_profile_name):
    """Return the index (1-based) of a previously-saved profile folder name
    within `listed`, or None if not found / not saved."""
    if not saved_profile_name:
        return None
    for i, profile_dir in enumerate(listed, 1):
        if profile_dir.name == saved_profile_name:
            return i
    return None


def prompt_settings(config, listed, display_names):
    """Show current settings (from config / defaults) and let the user
    change them, defaulting to previously saved values.

    Returns a tuple: (chosen_dir, target_folder_name, empty_after_export)
    """
    # --- Determine current defaults -----------------------------------
    saved_profile_index = resolve_saved_profile(listed, config.get("chrome_profile"))
    default_profile_index = saved_profile_index or 1

    default_folder_name = config.get("bookmark_folder_name", DEFAULT_TARGET_FOLDER_NAME)
    default_empty = config.get("empty_folder_after_export", False)

    print("\nCurrent settings:")
    default_dir = listed[default_profile_index - 1]
    default_label = display_names.get(default_dir.name, "")
    default_title = (f"{default_dir.name} ({default_label})"
                      if default_label else default_dir.name)
    print(f"  Chrome profile : [{default_profile_index}] {default_title}")
    print(f"  Folder name    : {default_folder_name}")
    print(f"  Empty folder after export? {'Yes' if default_empty else 'No'}")

    change = input("\nChange these settings? [y/N]: ").strip().lower()

    if change != "y":
        chosen_dir = default_dir
        target_folder_name = default_folder_name
        empty_after_export = default_empty
    else:
        # --- Chrome profile --------------------------------------------
        while True:
            choice = input(
                f"Select a Chrome profile (1-{len(listed)}) "
                f"[{default_profile_index}]: "
            ).strip()
            if choice == "":
                chosen_dir = listed[default_profile_index - 1]
                break
            if choice.isdigit() and 1 <= int(choice) <= len(listed):
                chosen_dir = listed[int(choice) - 1]
                break
            print("Please enter a valid number.")

        # --- Bookmark folder name ----------------------------------------
        folder_input = input(
            f"Bookmark folder name to export [{default_folder_name}]: "
        ).strip()
        target_folder_name = folder_input or default_folder_name

        # --- Empty folder afterwards? -------------------------------------
        default_hint = "Y/n" if default_empty else "y/N"
        empty_input = input(
            f"Empty this folder in Chrome after export? [{default_hint}]: "
        ).strip().lower()
        if empty_input == "":
            empty_after_export = default_empty
        else:
            empty_after_export = empty_input == "y"

    # --- Persist whatever we ended up with ------------------------------
    config["chrome_profile"] = chosen_dir.name
    config["bookmark_folder_name"] = target_folder_name
    config["empty_folder_after_export"] = empty_after_export
    save_config(config)

    return chosen_dir, target_folder_name, empty_after_export


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    print("=" * 64)
    print(" Chrome KOReader bookmarks -> CSV exporter")
    print("=" * 64)

    if is_chrome_running():
        print("\n[!] Chrome appears to be running.")
        print("    Close it completely before continuing - otherwise it may")
        print("    overwrite the changes this script makes to your bookmarks.")
        if input("    Continue anyway? (y/N): ").strip().lower() != "y":
            print("Exiting - close Chrome and run this again.")
            return

    user_data_dir = get_chrome_user_data_dir()
    if not user_data_dir.exists():
        print(f"\nCould not find Chrome's data folder:\n  {user_data_dir}")
        print("If Chrome is installed in a non-default location, set the")
        print("CHROME_USER_DATA_DIR environment variable to the correct path")
        print("and run this script again.")
        return

    profiles = find_profiles(user_data_dir)
    if not profiles:
        print(f"\nNo Chrome profiles with bookmarks were found in:\n  {user_data_dir}")
        return

    display_names = get_profile_display_names(user_data_dir)

    print(f"\nFound {len(profiles)} profile(s) in:\n  {user_data_dir}\n")

    listed = []
    for profile_dir in profiles:
        try:
            data = load_json(profile_dir / "Bookmarks")
        except Exception as e:
            print(f"  (skipping {profile_dir.name}: could not read Bookmarks - {e})")
            continue
        samples = collect_sample_domains(data)
        listed.append(profile_dir)
        label = display_names.get(profile_dir.name, "")
        title = f"{profile_dir.name}  ({label})" if label else profile_dir.name
        print(f"[{len(listed)}] {title}")
        if samples:
            print(f"     e.g. {{ {', '.join(samples)}, ... }}")
        else:
            print("     e.g. (no bookmarks found)")
        print()

    if not listed:
        print("No readable profiles found.")
        return

    config = load_config()
    chosen_dir, target_folder_name, empty_after_export = prompt_settings(
        config, listed, display_names
    )

    bookmarks_path = chosen_dir / "Bookmarks"
    print(f"\nUsing profile: {chosen_dir.name}")
    print(f"Bookmarks file: {bookmarks_path}")
    print(f"Folder name: {target_folder_name}")

    data = load_json(bookmarks_path)  # fresh read, in case anything changed

    root_labels = {
        "bookmark_bar": "Bookmarks bar",
        "other": "Other bookmarks",
        "synced": "Mobile bookmarks",
    }
    matches = []
    for root_key, label in root_labels.items():
        root = data.get("roots", {}).get(root_key)
        if not root:
            continue
        if root.get("name", "").strip().lower() == target_folder_name.lower():
            matches.append((root, label))
        matches.extend(find_target_folders(root, label, target_folder_name))

    if not matches:
        print(f"\nNo folder named '{target_folder_name}' was found in this profile.")
        return

    print(f"\nFound {len(matches)} folder(s) named '{target_folder_name}':")
    all_urls = []
    for folder_node, path in matches:
        urls = collect_urls(folder_node, path)
        print(f"  - {path}  ({len(urls)} bookmark(s))")
        all_urls.extend(urls)

    if not all_urls:
        print("\nThose folder(s) don't contain any bookmarks - nothing to export.")
        return

    print(f"\nTotal bookmarks to export: {len(all_urls)}")

    downloads = get_downloads_dir()
    downloads.mkdir(parents=True, exist_ok=True)
    csv_path = downloads / "urls.csv"

    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Title", "URL", "Date Added", "Source Folder"])
            for node, folder_path in all_urls:
                writer.writerow([
                    node.get("name", ""),
                    node.get("url", ""),
                    chrome_time_to_str(node.get("date_added")),
                    folder_path,
                ])
    except Exception as e:
        print(f"\nFailed to write CSV: {e}")
        print("Nothing in Chrome was changed.")
        return

    print(f"\nCSV created: {csv_path}")

    if not empty_after_export:
        print("\nDone. CSV was created; your Chrome bookmarks were left untouched.")
        print("(Set 'Empty folder after export' to Yes next time, or change "
              "settings now, to remove these bookmarks automatically.)")
        return

    timestamp2 = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = bookmarks_path.with_name(f"Bookmarks.backup_{timestamp2}")
    try:
        shutil.copy2(bookmarks_path, backup_path)
    except Exception as e:
        print(f"\nCould not create a backup ({e}). Aborting - Chrome was not modified.")
        return
    print(f"Backup saved: {backup_path}")

    for folder_node, _ in matches:
        strip_urls(folder_node)

    data["checksum"] = compute_checksum(data)

    try:
        with open(bookmarks_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=3)
    except Exception as e:
        print(f"\nFailed to write updated Bookmarks file: {e}")
        print(f"Your original is safe at:\n  {backup_path}")
        return

    print(f"\nRemoved {len(all_urls)} bookmark(s) from the "
          f"'{target_folder_name}' folder(s) (folders kept, now empty).")
    print("Start Chrome to see the change take effect.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
