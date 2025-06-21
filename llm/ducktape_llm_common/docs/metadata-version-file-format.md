# .metadata-version File Format Specification

## Overview

The `.metadata-version` file is a simple text file that indicates which version of the metadata structure is used in a directory. This allows the ducktape-llm-common tools to handle different metadata formats appropriately and provide migration paths when needed.

## File Format

### Basic Structure

```
1
```

The file contains:
- A single integer representing the metadata version
- A newline character at the end (optional but recommended)
- No other content

### Examples

**Version 1 (current):**
```
1
```

**Version 2 (future):**
```
2
```

### Rules

1. **Content**: Must contain exactly one integer
2. **Encoding**: UTF-8 text file
3. **Line endings**: Unix-style (LF) preferred, but CRLF accepted
4. **Whitespace**: Leading/trailing whitespace is trimmed when reading
5. **Comments**: Not supported - file must contain only the version number

## File Location

The `.metadata-version` file should be placed in the root directory of any project or module that uses versioned metadata structures.

```
project/
├── .metadata-version    # Version for this project
├── src/
├── tests/
└── docs/
```

### Inheritance

Version files do NOT inherit from parent directories. Each directory that contains versioned metadata must have its own `.metadata-version` file.

## Usage

### Creating a Version File

**Command line:**
```bash
echo "1" > .metadata-version
```

**Python:**
```python
from ducktape_llm_common.utils import create_metadata_version_file

create_metadata_version_file("/path/to/project")
```

### Reading Version

**Command line:**
```bash
cat .metadata-version
```

**Python:**
```python
from ducktape_llm_common.utils import get_metadata_version

version = get_metadata_version("/path/to/project")
```

## Version Control

`.metadata-version` files SHOULD be committed to version control. They are an integral part of the project structure and ensure consistent behavior across different environments.

**Example .gitignore (what NOT to do):**
```gitignore
# DON'T ignore version files!
# .metadata-version  ❌ Wrong
```

## Error Handling

### Missing File

If no `.metadata-version` file is found, the system falls back to the current package default (`METADATA_VERSION`).

### Invalid Content

If the file exists but contains invalid content:
- Non-integer content → Falls back to default version
- Multiple lines → Only first line is read
- Empty file → Falls back to default version

### Corrupted File

If the file cannot be read (permissions, corruption):
- System logs a warning
- Falls back to default version
- Does not halt operations

## Migration

When metadata structure changes require a new version:

1. The old version file remains unchanged
2. Migration tools update the content after successful migration
3. Backup of the old version is recommended

**Example migration:**
```bash
# Before migration
$ cat .metadata-version
1

# Run migration
$ python -m ducktape_llm_common.migrate --to-version 2

# After migration
$ cat .metadata-version
2
```

## Best Practices

### DO:
- ✅ Create `.metadata-version` when initializing a new project
- ✅ Commit the file to version control
- ✅ Check version compatibility at the start of operations
- ✅ Update the file only through migration tools

### DON'T:
- ❌ Edit the file manually (except during initial creation)
- ❌ Add comments or extra content to the file
- ❌ Use the file for any purpose other than version tracking
- ❌ Create nested version files unless explicitly needed

## Future Considerations

### Potential Enhancements

1. **Version Ranges**: Support for compatible version ranges (e.g., "1-3")
2. **Metadata**: Additional metadata in JSON format
3. **Checksums**: Include integrity checks for critical files
4. **Migration History**: Track migration path taken

### Current Limitations

1. Only single integer versions supported
2. No built-in rollback mechanism
3. No automatic version discovery from file content
4. No cross-version compatibility matrix

## Examples

### Example 1: New Project Setup

```bash
$ mkdir my-project
$ cd my-project
$ echo "1" > .metadata-version
$ git add .metadata-version
$ git commit -m "Initialize project with metadata version 1"
```

### Example 2: Checking Version in CI

```yaml
# .github/workflows/check-version.yml
- name: Check metadata version
  run: |
    VERSION=$(cat .metadata-version)
    if [ "$VERSION" != "1" ]; then
      echo "Unsupported metadata version: $VERSION"
      exit 1
    fi
```

### Example 3: Python Project Integration

```python
# setup.py or pyproject.toml hook
from ducktape_llm_common.utils import ensure_version_file

def setup_project():
    """Initialize project with correct metadata version."""
    ensure_version_file(".")
    print("Project initialized with metadata version support")
```
