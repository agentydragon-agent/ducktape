# TODO / Future Enhancements

## Rendering Improvements

- [ ] Format large numbers more compactly (e.g., "+123456" as "+123k")

- [ ] Adaptive tree indentation
  - Balance compact display with information density
  - Dynamically adjust indent size (1-4 spaces) based on terminal width
  - Maintain preferred minimum progress bar size
  - Ensure progress bars remain useful and visible

- [ ] Add flex in tree indent based on available width
  - Dynamically adjust tree indent from +1 to +3 spaces (current: fixed at +3)
  - Also vary number of "──" horizontal connector chars (1-2 currently, could be 1-3)
  - Reduce indent at narrow widths to save horizontal space
  - Use full +3 indent when width allows for better readability
  - Example:
    ```
    # Wide terminal (indent=3, connectors=2):
    root
    ├── src/module
    │   ├── file1.py
    │   └── file2.py
    └── test.py

    # Narrow terminal (indent=1, connectors=1):
    root
    ├─ src/module
    │ ├─ file1.py
    │ └─ file2.py
    └─ test.py
    ```
  - Challenge: must coordinate with multiple flexible elements:
    - Path collapsing (single-child directory merging creates variable path lengths)
    - Bar width constraints (bars already have max_width flexibility)
    - Tree column ellipsis behavior
    - Tree decoration characters (both vertical spacing and horizontal connectors)
  - Need to balance all flexibilities to avoid conflicts
  - Note: Rich's Tree class controls tree decoration - may need custom rendering

## Features

- [ ] Color scheme customization
- [ ] Different tree styles (ascii, unicode, etc.)

### Interactive Mode
- [ ] Add interactive mode that lets you expand/collapse tree nodes interactively
  - Use rich's Live display for real-time updates
  - Keyboard navigation (arrow keys, enter to expand/collapse)
  - Vi-style keybindings (j/k for navigation, space/enter for toggle)
  - Search functionality (/ to search, n/N for next/prev)
  - Toggle between different column views on the fly

### Box-shaped Hierarchical View
- [ ] Add box-shaped directory hierarchy view (like ncdu, WinDirStat)
  - Boxes sized proportionally to diff size (additions + deletions)
  - Nested boxes respect directory hierarchy
  - Use Rich's Box drawing or custom rendering
  - Color-coded by change type (green for additions, red for deletions, mixed for both)
  - Mouse support for navigation
  - Optional: treemap-style layout

### Filtering and Cutoff Options
- [ ] Add cutoff by top N items
  - `--top N` flag to show only top N files by change count
  - Show "... and N more files" summary at bottom
- [ ] Add percentage-based cutoff
  - `--min-percent PERCENT` to filter out files with <X% of total changes
  - Default could be 1% to hide noise
  - Show total changes hidden in summary
- [ ] Combine filters (e.g., top 10 OR >=1%)

### Other Enhancements
- [ ] Support for renamed files (currently shown as separate add/delete)
- [ ] Colored diff pass-through mode (like delta)
  - Show tree summary at top
  - Then pass through syntax-highlighted diff below
- [ ] Configuration file support (~/.config/difftree/config.toml)
- [ ] Git alias setup helper (`difftree --install-alias`)
- [ ] Performance optimization for large diffs (>1000 files)
