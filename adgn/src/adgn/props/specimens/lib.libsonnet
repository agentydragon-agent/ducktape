// Jsonnet helpers for concise, DRY specimen issue definitions.
// Produces data compatible with adgn.props models (Issue, FalsePositive).
//
// Note: `snapshot` is auto-derived from file path at Python loader level.
//
// Usage example:
//   local I = import '../../lib.libsonnet';
//   I.issue(
//     rationale='Dead code should be removed',
//     filesToRanges={'src/cli.py': [[145, 167]]},
//     // expect_caught_from auto-inferred: [['src/cli.py']] (single file)
//   )

// ============================================================================
// Internal Helper Functions (not exported)
// ============================================================================

// Normalize a line spec into a LineRange object.
// Accepts either an int (single line) or a [start,end] array; also accepts objects that already have start_line/end_line.
// NOTE: end_line must always be present (even if null) for OpenAI strict mode compatibility
// TODO: Support per-range notes/context: [[10, 20, 'note about this range'], [30, 40, 'note about that range']]
//       Currently only occurrence-level notes are supported; inline comments are for human readers only.
//       Per-range notes would help explain why specific line ranges matter within one occurrence.
local toRange(x) =
  if std.type(x) == 'number' then { start_line: x, end_line: null }
  else if std.type(x) == 'array' && std.length(x) == 2 then { start_line: x[0], end_line: x[1] }
  else if std.type(x) == 'object' && std.objectHas(x, 'start_line') then (
    // Ensure end_line is present for objects too
    if std.objectHas(x, 'end_line') then x
    else x + { end_line: null }
  )
  else error 'Invalid line spec: ' + std.manifestJson(x);

// Normalize an array of mixed line specs to LineRange[]
local normRanges(arr) = [toRange(x) for x in arr];

// Build a files mapping entry: file -> [LineRange...]
local fileEntry(file, ranges) = { [file]: normRanges(ranges) };

// Normalize a {file: [rangeSpec]|null} mapping into canonical {file: LineRange[]|null}
local normFiles(files) = {
  [f]: if files[f] == null then null else normRanges(files[f])
  for f in std.objectFields(files)
};

// ============================================================================
// True Positive Helpers
// ============================================================================

// Single occurrence true positive issue.
//
// Parameters:
//   rationale: Full explanation of what's wrong and recommended fix
//   filesToRanges: Dict of file paths → array of line ranges
//   expect_caught_from: (optional) List of alternative file sets for detection
//                       Format: [['file1.py'], ['file2.py', 'file3.py']]
//                       Semantics: Issue detectable from ANY of these file sets (OR logic)
//                       Each inner list is files required together (AND logic)
//
// Detection standard for expect_caught_from:
//   "If I gave a high-quality critic this file set to review, and they failed to
//   find this issue, would that be a failure on their part?"
//
//   A thorough code review starting from these files naturally includes:
//   - Following imports/calls to check APIs
//   - Searching for existing helpers/patterns
//   - Looking for duplication in the codebase
//   - All normal code review activities
//
//   NOT: "Can you detect this reading only these files in isolation?"
//
// Auto-inference:
//   - If filesToRanges has 1 file AND expect_caught_from not provided:
//     Auto-infers expect_caught_from = [[that_single_file]]
//   - If filesToRanges has >1 file AND expect_caught_from not provided:
//     Raises error (author must specify minimal detection sets)
//
// Returns: {rationale, occurrences: [{files, expect_caught_from}]}
local issue(rationale, filesToRanges, expect_caught_from=null) =
  local files_list = std.objectFields(filesToRanges);
  local inferred_expect_caught_from =
    if expect_caught_from != null then expect_caught_from
    else if std.length(files_list) == 1 then [[files_list[0]]]
    else error 'Multi-file issue requires explicit expect_caught_from. Specify minimal file sets required to detect this issue (AND/OR semantics). Files: ' + std.manifestJson(files_list);
  {
    rationale: rationale,
    should_flag: true,
    occurrences: [{
      files: normFiles(filesToRanges),
      expect_caught_from: inferred_expect_caught_from,
    }],
  };

// Multiple occurrences true positive issue.
//
// Parameters:
//   rationale: Full explanation of what's wrong and recommended fix
//   occurrences: List of occurrence objects, each with:
//     - files: {file: [ranges]|null} dict
//     - note: string (REQUIRED - explains this specific occurrence)
//     - expect_caught_from: [[files...], ...] (REQUIRED if total files > 1)
//
// Detection standard for expect_caught_from (same as issue()):
//   "If I gave a high-quality critic this file set to review, and they failed to
//   find this issue, would that be a failure on their part?"
//
//   A thorough code review starting from these files naturally includes:
//   - Following imports/calls to check APIs
//   - Searching for existing helpers/patterns
//   - Looking for duplication in the codebase
//   - All normal code review activities
//
//   NOT: "Can you detect this reading only these files in isolation?"
//
// Validation:
//   - ALL occurrences must have 'note' field
//   - If total unique files across ALL occurrences > 1:
//     EVERY occurrence must have explicit 'expect_caught_from'
//     (Even single-file occurrences need it when total > 1)
//
// Returns: {rationale, occurrences}
local issueMulti(rationale, occurrences) =
  // Validate all occurrences have notes
  local missing_notes = [
    i
    for i in std.range(0, std.length(occurrences) - 1)
    if !std.objectHas(occurrences[i], 'note') || occurrences[i].note == null
  ];
  local notes_valid = if std.length(missing_notes) > 0
    then error 'All occurrences in issueMulti must have a note field. Missing in occurrences at indices: ' + std.manifestJson(missing_notes)
    else true;

  // Compute total unique files across all occurrences
  local all_files = std.foldl(
    function(acc, occ) acc + std.objectFields(occ.files),
    occurrences,
    []
  );
  local unique_files = std.set(all_files);
  local total_files = std.length(unique_files);

  // If total files > 1, validate ALL occurrences have expect_caught_from
  local missing_expect = if total_files > 1 then [
    i
    for i in std.range(0, std.length(occurrences) - 1)
    if !std.objectHas(occurrences[i], 'expect_caught_from')
  ] else [];
  local expect_valid = if std.length(missing_expect) > 0
    then error 'Multi-file issue (total files: %d) requires expect_caught_from on ALL occurrences. Missing in occurrences at indices: %s. Files: %s' % [total_files, std.manifestJson(missing_expect), std.manifestJson(unique_files)]
    else true;

  {
    rationale: rationale,
    should_flag: true,
    occurrences: [
      {
        files: normFiles(occ.files),
        note: occ.note,
        expect_caught_from: occ.expect_caught_from,
      }
      for occ in occurrences
    ],
  };

// ============================================================================
// False Positive Helpers
// ============================================================================

// Single occurrence false positive.
//
// Parameters:
//   rationale: Explanation of why this looks like an issue but isn't
//   filesToRanges: Dict of file paths → array of line ranges
//   relevant_files: (optional) List of files to show this FP for
//                   Auto-inferred from filesToRanges keys if not provided
//
// Semantics: Show this FP to grader if critic reviewed ANY of relevant_files
//
// Returns: {rationale, occurrences: [{files, relevant_files}]}
local falsePositive(rationale, filesToRanges, relevant_files=null) =
  local inferred_relevant_files =
    if relevant_files != null then relevant_files
    else std.objectFields(filesToRanges);
  {
    rationale: rationale,
    should_flag: false,
    occurrences: [{
      files: normFiles(filesToRanges),
      relevant_files: inferred_relevant_files,
    }],
  };

// Multiple occurrences false positive.
//
// Parameters:
//   rationale: Explanation of why this looks like an issue but isn't
//   occurrences: List of occurrence objects, each with:
//     - files: {file: [ranges]|null} dict
//     - note: string (REQUIRED - explains this specific occurrence)
//     - relevant_files: [files...] (list of files to show this FP for)
//
// Validation:
//   - ALL occurrences must have 'note' field
//
// Returns: {rationale, occurrences}
local falsePositiveMulti(rationale, occurrences) =
  // Validate all occurrences have notes
  local missing_notes = [
    i
    for i in std.range(0, std.length(occurrences) - 1)
    if !std.objectHas(occurrences[i], 'note') || occurrences[i].note == null
  ];
  local notes_valid = if std.length(missing_notes) > 0
    then error 'All occurrences in falsePositiveMulti must have a note field. Missing in occurrences at indices: ' + std.manifestJson(missing_notes)
    else true;

  {
    rationale: rationale,
    should_flag: false,
    occurrences: [
      {
        files: normFiles(occ.files),
        note: occ.note,
        relevant_files: occ.relevant_files,
      }
      for occ in occurrences
    ],
  };

// ============================================================================
// Exported API
// ============================================================================

{
  // True Positive helpers
  issue: issue,
  issueMulti: issueMulti,

  // False Positive helpers
  falsePositive: falsePositive,
  falsePositiveMulti: falsePositiveMulti,
}
