# Pre-commit Autofixer Hook Test Directory

This directory demonstrates the pre-commit autofixer hook in action.

```
test_hook_demo/               🧪 Test Files
├── .claude/
│   └── settings.json         # Tells Claude to run the autofixer hook
└── settings.yaml             # Hook configuration (overrides user config)
```

## 🚀 How to Test

```bash
# From this directory, run Claude with a prompt that creates messy code
claude \
  -p "write a really ugly messy badly formatted python file" \
  --allowedTools Write \
  --project-dir . \
  --debug \
  --output-format json
```

## ✨ What Happens

1. **Claude writes** an ugly, badly formatted Python file
2. **Hook triggers** automatically via `.claude/settings.json`  
3. **Loads config** from committed `settings.yaml` in this directory
4. **Detects Git repo with pre-commit** and uses root `.pre-commit-config.yaml`
5. **Runs autofix** (ruff format, import sorting, etc.)
6. **Shows feedback** like "🔧 Pre-commit autofix applied to ugly_file.py"
7. **Result**: The messy code is automatically cleaned up and properly formatted!

## 📝 Configuration Details

**`.claude/settings.json`** configures Claude to run the hook after file operations.

**`settings.yaml`** configures the hook behavior with settings like timeout and dry run mode.
