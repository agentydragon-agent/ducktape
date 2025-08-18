import os
import typing

from _typeshed import Incomplete

from . import enums
from ._build import __version__ as __version__
from ._pygit2 import *
from .blame import Blame as Blame
from .blame import BlameHunk as BlameHunk
from .blob import BlobIO as BlobIO
from .callbacks import CheckoutCallbacks as CheckoutCallbacks
from .callbacks import Payload as Payload
from .callbacks import RemoteCallbacks
from .callbacks import StashApplyCallbacks as StashApplyCallbacks
from .callbacks import get_credentials as get_credentials
from .config import Config as Config
from .credentials import *
from .errors import Passthrough as Passthrough
from .filter import Filter as Filter
from .index import Index as Index
from .index import IndexEntry as IndexEntry
from .legacyenums import *
from .packbuilder import PackBuilder as PackBuilder
from .remotes import Remote as Remote
from .repository import Repository
from .submodules import Submodule as Submodule

features: Incomplete
LIBGIT2_VER: Incomplete

def init_repository(path: str | bytes | os.PathLike | None, bare: bool = False, flags: enums.RepositoryInitFlag = ..., mode: int | enums.RepositoryInitMode = ..., workdir_path: str | None = None, description: str | None = None, template_path: str | None = None, initial_head: str | None = None, origin_url: str | None = None) -> Repository: ...
def clone_repository(url: str, path: str, bare: bool = False, repository: typing.Callable | None = None, remote: typing.Callable | None = None, checkout_branch: str | None = None, callbacks: RemoteCallbacks | None = None, depth: int = 0, proxy: None | bool | str = None): ...

tree_entry_key: Incomplete
settings: Incomplete
