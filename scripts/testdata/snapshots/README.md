# Formatter Output Snapshots

This directory contains example outputs from different Python formatters to demonstrate their behavior with multi-line code.

## Input

See `input_multiline.py` - multi-line code with trailing commas.

## Outputs by Formatter

### Ruff

- **`ruff/default_respects_trailing_comma.py`** - Default config (respects trailing comma signal)
  - Config: `line-length = 120` only
  - Result: ❌ Keeps multi-line

- **`ruff/skip_magic_trailing_comma.py`** - ✅ **RECOMMENDED**
  - Config: `skip-magic-trailing-comma = true`
  - Result: ✅ **Collapses to one line, removes trailing commas**

### yapf

- **`yapf/default_google_style.py`** - Default Google style
  - Config: `based_on_style = google`
  - Result: ❌ Keeps multi-line

- **`yapf/disable_ending_comma_heuristic.py`** - Alternative solution
  - Config: `disable_ending_comma_heuristic = True`
  - Result: ✅ Collapses to one line (but keeps trailing commas)

### autopep8

- **`autopep8/aggressive.py`** - Even with --aggressive
  - Config: `--aggressive --aggressive --max-line-length=120`
  - Result: ❌ Never collapses multi-line

## Recommended Solution

Use **Ruff with `skip-magic-trailing-comma = true`**:

```toml
# ruff.toml
line-length = 120

[format]
skip-magic-trailing-comma = true

[lint.isort]
split-on-trailing-comma = false  # for compatibility
```

This provides Google-style compact formatting with no custom scripts needed.
