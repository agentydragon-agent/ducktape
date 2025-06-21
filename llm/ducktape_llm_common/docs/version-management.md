# Version Management System

## Overview

The ducktape-llm-common package includes a comprehensive version management system for tracking metadata structure changes across the codebase. This system ensures compatibility and provides migration paths when metadata structures evolve.

## Key Concepts

### Metadata Version

The metadata version is an integer that identifies the structure and format of metadata files throughout the codebase. When breaking changes are made to metadata formats, the version number is incremented.

Current version: **1** (defined as `METADATA_VERSION` in `ducktape_llm_common/__init__.py`)

### Version Files

Version information is stored in `.metadata-version` files placed in directories that contain versioned metadata. These files contain a single integer representing the metadata version used in that directory.

## File Format: .metadata-version

The `.metadata-version` file is a simple text file containing only the version number:

```
1
```

### Characteristics:
- Plain text file
- Contains only a single integer
- No additional whitespace or content
- Should be committed to version control
- Takes precedence over the default package version

## Basic Usage

### Checking Version

```python
from ducktape_llm_common.utils import get_metadata_version

# Get version for current directory
version = get_metadata_version()

# Get version for specific path
version = get_metadata_version("/path/to/project")
```

### Validating Version Compatibility

```python
from ducktape_llm_common.utils import validate_metadata_version

# Check if a version is compatible
is_compatible = validate_metadata_version(1)  # True if compatible

# Strict validation (raises exception if incompatible)
from ducktape_llm_common.utils import validate_version_strict

try:
    validate_version_strict("/path/to/project")
except IncompatibleVersionError as e:
    print(f"Version mismatch: {e}")
```

### Creating Version Files

```python
from ducktape_llm_common.utils import create_metadata_version_file, ensure_version_file

# Create a new version file
create_metadata_version_file("/path/to/project")

# Ensure version file exists (won't overwrite existing)
was_created = ensure_version_file("/path/to/project")
```

## Advanced Features

### Version Information

```python
from ducktape_llm_common.utils import get_version_info, VERSION_HISTORY

# Get detailed info about a version
info = get_version_info(1)
print(f"Version {info.version}: {info.description}")
print(f"Introduced: {info.introduced}")
print(f"Changes: {info.changes}")

# Access full version history
for version, info in VERSION_HISTORY.items():
    print(f"Version {version}: {info.description}")
```

### Finding Version Files

```python
from ducktape_llm_common.utils import find_version_files

# Find all version files in a directory tree
version_files = find_version_files("/path/to/project")
for path, version in version_files:
    print(f"{path}: version {version}")
```

### Version Reports

```python
from ducktape_llm_common.utils import get_version_report

# Generate comprehensive version report
report = get_version_report("/path/to/project")
print(f"Current version: {report['current_version']}")
print(f"Total versioned paths: {report['total_versioned_paths']}")
print(f"Version distribution: {report['version_distribution']}")

# Check for incompatibilities
if report['incompatible_paths']:
    print("Incompatible paths found:")
    for item in report['incompatible_paths']:
        print(f"  {item['path']}: v{item['version']} - {item['reason']}")
```

## Version Migration

### Registering Migrations

```python
from ducktape_llm_common.utils import migrator

def migrate_v1_to_v2(path):
    """Migrate metadata from version 1 to version 2."""
    # Implementation here
    pass

# Register the migration
migrator.register_migration(1, 2, migrate_v1_to_v2)
```

### Performing Migrations

```python
from ducktape_llm_common.utils import migrator

# Check if migration is possible
if migrator.can_migrate(1, 2):
    # Perform migration with backup
    migrator.migrate(path, from_version=1, to_version=2, backup=True)
```

## Error Handling

The version system defines specific exceptions:

- `VersionError`: Base exception for all version-related errors
- `IncompatibleVersionError`: Raised when versions are incompatible
- `VersionMigrationError`: Raised when migration fails

```python
from ducktape_llm_common.utils import (
    IncompatibleVersionError,
    VersionMigrationError,
)

try:
    validate_version_strict(path)
except IncompatibleVersionError as e:
    print(f"Found version {e.found_version}, expected {e.expected_version}")
    print(f"Path: {e.path}")
```

## Best Practices

### 1. Always Include Version Files

When creating new metadata structures, always include a `.metadata-version` file:

```python
# When initializing a new project area
ensure_version_file(project_path)
```

### 2. Check Versions Early

Validate versions at the start of operations to fail fast:

```python
def process_metadata(path):
    # Validate version first
    validate_version_strict(path)

    # Then proceed with processing
    # ...
```

### 3. Plan for Migration

When introducing breaking changes:

1. Increment `METADATA_VERSION` in the package
2. Document changes in `VERSION_HISTORY`
3. Implement migration function
4. Register migration with the migrator

### 4. Use Version Reports for Auditing

Regularly run version reports to identify outdated metadata:

```python
# In a maintenance script
report = get_version_report(project_root)
if report['incompatible_paths']:
    send_alert("Outdated metadata found!")
```

## Version History

### Version 1 (Current)
- **Introduced**: 2024-01-20
- **Description**: Initial metadata structure version
- **Changes**:
  - Basic URL validation support
  - Initial metadata structure for work tracking
  - Support for .metadata-version files

## Future Considerations

### Backward Compatibility

Future versions may support backward compatibility by:
- Reading older formats and auto-upgrading in memory
- Providing compatibility shims
- Supporting version ranges in compatibility checks

### Version Negotiation

For distributed systems, version negotiation might be needed:
- Clients and servers agreeing on compatible versions
- Automatic selection of highest compatible version
- Graceful degradation for older clients

### Schema Evolution

As the system grows, consider:
- Formal schema definitions (JSON Schema, etc.)
- Automated validation based on schemas
- Schema migration tools
- Version-specific documentation generation
