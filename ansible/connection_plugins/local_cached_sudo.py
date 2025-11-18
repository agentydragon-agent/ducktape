import subprocess
import threading
import time

from ansible.plugins.connection.local import Connection as Local


class Connection(Local):
    _sudo_ready = False  # class-level, shared between instances

    def _prime_sudo(self):
        if Connection._sudo_ready:  # already primed
            return
        # Try non-interactive check; if it fails, ask once.
        if subprocess.call(["sudo", "-n", "true"]) != 0:
            subprocess.check_call(["sudo", "-v"])  # will prompt

        # Keep sudo cookie alive while playbook runs
        def _keep():
            while True:
                time.sleep(60)
                subprocess.call(["sudo", "-n", "true"])

        threading.Thread(target=_keep, daemon=True).start()
        Connection._sudo_ready = True

    # hook one level above exec of every task
    def exec_command(self, *args, **kwargs):
        self._prime_sudo()
        return super().exec_command(*args, **kwargs)
