# Append VALUE to a dconf array KEY.
#
# PARAMETERS
#   key    – dconf array key
#   value  – element to add if missing
#
# EXAMPLE
#   - dconf_array_append:
#       key:  /org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
#       value: "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/flameshot/"

from ansible.errors import AnsibleError
from gi.repository import GLib

from ansible.plugins.action import ActionBase


def _array_to_list(raw: str):
    if not raw:
        return []

    v = GLib.Variant.parse(None, raw, None, None)  # parses "@as []" OK
    if v.get_type_string() == "v":  # 'v' = variant wrapper
        v = v.get_child_value(0)  # unwrap once

    return list(v.unpack())  # → Python list


def _list_to_array(lst):
    return GLib.Variant("v", GLib.Variant("as", lst)).print(False)


class ActionModule(ActionBase):

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)

        if "key" not in self._task.args:
            raise AnsibleError("Parameter 'key' is required")

        if "value" not in self._task.args:
            raise AnsibleError("Parameter 'value' is required")

        key, value = self._task.args["key"], self._task.args["value"]

        def _dconf(**kwargs):
            return self._execute_module(
                module_name="ansible.builtin.dconf",
                module_args=kwargs,
                task_vars=task_vars,
                tmp=tmp,
            )

        # 1. read current array
        before_raw = _dconf(key=key, state="read").get("value")
        result["before"] = before_raw
        current = _array_to_list(before_raw)

        if value in current:
            return result | dict(changed=False, after=before_raw)

        # 2. merge + write
        current.append(value)
        after_raw = _list_to_array(current)

        if not self._play_context.check_mode:
            _dconf(key=key, value=after_raw)

        return result | dict(changed=True, after=after_raw)
