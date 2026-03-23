# Pop Shell tiling settings (gaps, tile-by-default).
# Keyboard shortcut overrides stripped — using schema defaults for now.
{ lib, ... }:
{
  dconf.settings = {
    "org/gnome/shell/extensions/pop-shell" = {
      gap-inner = lib.hm.gvariant.mkUint32 1;
      gap-outer = lib.hm.gvariant.mkUint32 1;
      tile-by-default = true;
    };
  };
}
