local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The --document-id CLI help text (lines 358, 372) states "Notebook path relative to workspace;
    if missing, a new timestamped notebook is created", implying that when a document ID is
    provided, the wrapper should open that existing notebook if it exists, and only create a new
    one if missing. However, _ensure_document_id unconditionally raises FileExistsError when the
    target path already exists (lines 42-43), making it impossible to reopen existing notebooks.
    Both run_seatbelt and run_docker call _ensure_document_id with user-provided document IDs,
    so any attempt to use --document-id with an existing notebook crashes before Jupyter starts.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [[42, 43], [358, 358], [372, 372]],
  },
)
