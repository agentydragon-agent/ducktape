local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    run_seatbelt calls _ensure_document_id twice on the same document path, causing a crash
    on the second call. At line 449, run_seatbelt calls _ensure_document_id(ws, document_id),
    which either generates a unique timestamped path (if document_id is None) or uses the
    provided path, creates the notebook file, and returns the path. Then at line 460,
    run_seatbelt calls _seatbelt(..., document_id=doc_id), which calls _ensure_document_id
    again at line 291 with the same path. Since _ensure_document_id raises FileExistsError
    when the target file already exists (line 42), the second call always crashes.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [[42, 43], [291, 291], [449, 449]],
  },
)
