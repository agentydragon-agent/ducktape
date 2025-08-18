# Minimal watchdog.events stubs used by wt

class FileSystemEvent:
    is_directory: bool
    src_path: str

class FileSystemEventHandler:
    def on_modified(self, event: FileSystemEvent) -> None: ...
    def on_created(self, event: FileSystemEvent) -> None: ...
