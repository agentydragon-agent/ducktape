import importlib
import pkgutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "wt"

CLIENT_PREFIX = "wt.client"
SERVER_PREFIX = "wt.server"
SHARED_PREFIX = "wt.shared"

ALLOWED_PREFIXES_FOR_CLIENT = {CLIENT_PREFIX, SHARED_PREFIX}
ALLOWED_PREFIXES_FOR_SERVER = {SERVER_PREFIX, SHARED_PREFIX}


def iter_modules(package_prefix: str):
    pkg = importlib.import_module(package_prefix)
    pkg_path = Path(pkg.__file__).parent
    for m in pkgutil.walk_packages([str(pkg_path)], prefix=package_prefix + "."):
        if not m.ispkg:
            yield m.name


def get_imports(module_name: str) -> set[str]:
    # Simple static scan: not a full parser, good enough to catch cross-package imports
    import inspect
    mod = importlib.import_module(module_name)
    source = inspect.getsource(mod)
    imports: set[str] = set()
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("from "):
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "from":
                pkg = parts[1]
                imports.add(pkg)
        elif line.startswith("import "):
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "import":
                # could be multiple imports separated by commas
                items = parts[1].split(",")
                for item in items:
                    imports.add(item.strip())
    return imports


def test_client_does_not_import_server():
    violations = []
    for mod in iter_modules(CLIENT_PREFIX):
        imports = get_imports(mod)
        for imp in imports:
            if imp.startswith(SERVER_PREFIX):
                violations.append((mod, imp))
    assert not violations, f"Client imports server: {violations}"


def test_server_does_not_import_client():
    violations = []
    for mod in iter_modules(SERVER_PREFIX):
        imports = get_imports(mod)
        for imp in imports:
            if imp.startswith(CLIENT_PREFIX):
                violations.append((mod, imp))
    assert not violations, f"Server imports client: {violations}"
