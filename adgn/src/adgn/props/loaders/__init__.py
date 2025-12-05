"""Filesystem loaders for snapshots and issues.

This module provides loaders that read from the filesystem and return Pydantic objects.
Loaders do NOT interact with the database - they only parse YAML/Jsonnet files.
"""

from .filesystem import FilesystemLoader

__all__ = ["FilesystemLoader"]
