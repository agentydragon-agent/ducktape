#!/usr/bin/env python3
"""
Requires:
    sudo apt install libglib2.0-dev-bin gir1.2-glib-2.0
"""

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import List

from gi.repository import Gio, GLib

SCHEMA_LIST = "org.gnome.Terminal.ProfilesList"
PROFILE_BASE = "/org/gnome/terminal/legacy/profiles:/"

logger = logging.getLogger(__name__)


class GnomeTerminalProfile:
    def __init__(self, uuid_: str):
        self.uuid = uuid_
        self.settings = Gio.Settings.new_with_path(
            "org.gnome.Terminal.Legacy.Profile", f"{PROFILE_BASE}:{uuid_}/"
        )

    def set_str(self, key: str, value: str) -> bool:
        old = self.settings.get_string(key)
        log_header = f"{self.uuid=} str {key=}: "
        if old != value:
            logger.debug(f"{log_header}{old=} -> change to {value}")
            self.settings.set_string(key, value)
            return True
        logger.debug(f"{log_header}already set to {old}")
        return False

    def set_bool(self, key: str, value: bool) -> bool:
        old = self.settings.get_boolean(key)
        log_header = f"{self.uuid=} bool {key=}: "
        if old != value:
            logger.debug(f"{log_header}{old=} -> change to {value}")
            self.settings.set_value(key, GLib.Variant("b", value))
            return True
        logger.debug(f"{log_header}already set to {old}")
        return False

    def set_str_list(self, key: str, values: List[str]) -> bool:
        assert all(isinstance(i, str) for i in values)
        old = self.settings.get_value(key).unpack()
        log_header = f"{self.uuid=} str_list {key=}: "
        if old != values:
            logger.debug(f"{log_header}{old=} -> change to {values}")
            self.settings.set_value(key, GLib.Variant("as", values))
            return True
        logger.debug(f"{log_header}already set to {old}")
        return False

    def apply_updates(self, values: dict[str, str | bool | list[str]]) -> bool:
        changed = False
        for key, value in values.items():
            match value:
                case str():
                    changed |= self.set_str(key, value)
                case bool():
                    changed |= self.set_bool(key, value)
                case list():
                    changed |= self.set_str_list(key, value)
                case _:
                    raise ValueError(f"Unexpected type: {type(value)}")
            Gio.Settings.sync()
        return changed

    def apply_color_scheme(self, color_dir: Path, font: str | None = None) -> bool:
        values = {
            "background-color": (color_dir / "bg_color").read_text().strip(),
            "foreground-color": (color_dir / "fg_color").read_text().strip(),
            "bold-color": (color_dir / "bd_color").read_text().strip(),
            "cursor-colors-set": False,
            "use-theme-colors": False,
            "bold-color-same-as-fg": False,
            "palette": (color_dir / "palette").read_text().splitlines(),
        }
        if font:
            values["font"] = font
            values["use-system-font"] = False
        else:
            values["use-system-font"] = True
        return self.apply_updates(values)


def profile_list_setting():
    return Gio.Settings.new_with_path(SCHEMA_LIST, PROFILE_BASE)


def get_all_profiles() -> list[GnomeTerminalProfile]:
    uuids = profile_list_setting().get_value("list").unpack()
    return [GnomeTerminalProfile(u) for u in uuids]


def find_profile_by_name(name: str) -> GnomeTerminalProfile | None:
    matches = [
        p for p in get_all_profiles() if p.settings.get_string("visible-name") == name
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple '{name}' profiles exist: {', '.join(p.uuid for p in matches)}"
        )
    return matches[0] if matches else None


def create_profile(
    name: str, color_dir: Path, font: str | None
) -> GnomeTerminalProfile:
    setting = profile_list_setting()
    uuids = setting.get_value("list").unpack()

    new_uuid = str(uuid.uuid4())
    setting.set_value("list", GLib.Variant("as", uuids + [new_uuid]))
    Gio.Settings.sync()

    logger.debug(f"Existing uuids: {uuids!r}, add new uuid {new_uuid}")
    profile = GnomeTerminalProfile(new_uuid)
    profile.settings.set_string("visible-name", name)
    Gio.Settings.sync()

    logger.debug(f"Profile {name} ({new_uuid}) created, applying settings on it")
    profile.apply_color_scheme(color_dir, font=font)

    return profile


def cmd_apply(name: str, color_dir: Path, font: str | None):
    logger.debug(f"cmd_apply: {name=}, {color_dir=}, {font=}")
    profile = find_profile_by_name(name)
    if not profile:
        logger.debug(f"Creating new profile '{name}'")
        profile = create_profile(name, color_dir, font=font)
        changed = True
    else:
        logger.debug(f"Updating existing profile '{name}'")
        changed = profile.apply_color_scheme(color_dir, font=font)
    return {"changed": changed, "uuid": profile.uuid}


def cmd_set_default(name: str):
    profile = find_profile_by_name(name)
    if not profile:
        raise RuntimeError(f"No profile named '{name}' found.")

    setting = profile_list_setting()
    current = setting.get_string("default")

    if current != profile.uuid:
        setting.set_string("default", profile.uuid)
        Gio.Settings.sync()
        return {"changed": True}
    return {"changed": False}


def main():
    # Define a parent parser with global options
    global_opts = argparse.ArgumentParser(add_help=False)
    global_opts.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # Subcommand: apply
    apply_parser = subparsers.add_parser("apply", parents=[global_opts])
    apply_parser.add_argument("name")
    apply_parser.add_argument("color_dir", type=Path)
    apply_parser.add_argument(
        "--font", help="Set custom terminal font (e.g. 'MesloLGS NF 12')"
    )

    # Subcommand: set-default
    set_default_parser = subparsers.add_parser("set-default", parents=[global_opts])
    set_default_parser.add_argument("name")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            stream=sys.stderr,
            format="%(message)s",
        )

    if args.mode == "apply":
        output = cmd_apply(args.name, args.color_dir, font=args.font)
    elif args.mode == "set-default":
        output = cmd_set_default(args.name)
    else:
        raise RuntimeError(f"Unknown {args.mode = }")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
