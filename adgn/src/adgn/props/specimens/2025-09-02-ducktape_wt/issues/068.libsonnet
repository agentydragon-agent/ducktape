local I = import '../../specimens/lib.libsonnet';

// iss-068: Use Path types for internal filesystem fields in StatusSnapshot
I.issueOneOccurrence(
  rationale='StatusSnapshot.dirty_files and StatusSnapshot.untracked_files are filesystem paths and should be typed as list[Path] (not list[str]) to keep internal code working with Path objects and avoid scattered conversions. Suggested change: update the StatusSnapshot model to use list[Path] and audit call sites to remove str conversions.',
  // properties=['pathlib'],
  gap_note="GAP: Code should be designed and written with clear wire/internal type layers; document conversion boundaries to avoid mixed types across layers. (this is an internal type specifically. if this were a wire type on protocol that doesn't accept Path - e.g. serializing them as json with pydantic - then str would be fine. but this is internal wiring, and app should speak the proper Path type internally)",
  filesToRanges={
    'wt/wt/server/wt_server.py': [[414, 416]],
  },
)
