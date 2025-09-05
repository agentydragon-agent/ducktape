// Jsonnet helpers for concise, DRY specimen issue definitions.
// Produces data compatible with adgn_llm.properties.specimen_issues.SpecimenIssues
// Usage (example):
//   local I = import 'specimen_issues.libsonnet';
//   I.root([
//     I.issueMultiFromLines(
//       id='iss-001',
//       rationale='Inline imports inside functions; move to module top.',
//       properties=['imports-top'],
//       linesByFile={
//         'wt/wt/cli.py': [101, 158, 193, 198, 206, 253],
//         'wt/wt/client/handlers.py': [10, 16, 50, 75, 86, 89, 94, 97, 104, 120, 127, 134, 136, 142, 152, [164,168], 194, 196, 201, 214, 220, 226, 238, 240, [242,243], 249, 254, 263, 277, 298, [301,302], 310, 342],
//       }
//     ),
//     I.issueSingle(id='iss-009', should_flag=false, rationale='shlex.quote requires str', files={ 'wt/wt/client/worktree_utils.py': [ 98 ] }),
//   ])


// Normalize a line spec into a LineRange object.
// Accepts either an int (single line) or a [start,end] array; also accepts objects that already have start_line/end_line.
local toRange(x) =
  if std.type(x) == 'number' then { start_line: x }
  else if std.type(x) == 'array' && std.length(x) == 2 then { start_line: x[0], end_line: x[1] }
  else if std.type(x) == 'object' && std.objectHas(x, 'start_line') then x
  else error 'Invalid line spec: ' + std.manifestJson(x);

// Normalize an array of mixed line specs to LineRange[]
local normRanges(arr) = [ toRange(x) for x in arr ];

// Build a files mapping entry: file -> [LineRange...]
local fileEntry(file, ranges) = { [file]: normRanges(ranges) };

// Expand shorthand mapping {file: [lineSpec,...]} into a list of Occurrence objects
// Each occurrence has exactly one file with a single LineRange (single line per occ is common; ranges also supported)
local instancesFromLinesByFile(linesByFile) = std.flattenArrays([
  [ { files: fileEntry(file, [ln]) } for ln in linesByFile[file] ]
  for file in std.objectFields(linesByFile)
]);

// Issue constructors

// Single cross-cutting issue (cardinality = 'single')
local issueSingle(id, rationale, files, properties=[], gap_note=null, should_flag=true) = {
  id: id,
  should_flag: should_flag,
  rationale: rationale,
  properties: properties,
  gap_note: gap_note,
  cardinality: 'single',
  // files value accepts: { file: [int|[start,end]|{start_line,...}], ... } or null for unspecified
  files: {
    [f]: if files[f] == null then null else normRanges(files[f])
    for f in std.objectFields(files)
  },
};

// Multi-occurrence issue with explicit instances
local issueMulti(id, rationale, instances, properties=[], gap_note=null, should_flag=true) = {
  id: id,
  should_flag: should_flag,
  rationale: rationale,
  properties: properties,
  gap_note: gap_note,
  cardinality: 'multi_instances',
  instances: [
    // Each instance.files may be a {file: [ranges]|null} map; normalize arrays to LineRange
    { files: {
        [f]: if inst.files[f] == null then null else normRanges(inst.files[f])
        for f in std.objectFields(inst.files)
      } }
    for inst in instances
  ],
};

// Multi-occurrence issue built from shorthand mapping file -> [lineSpec,...]
local issueMultiFromLines(id, rationale, linesByFile, properties=[], gap_note=null, should_flag=true) =
  issueMulti(id=id, rationale=rationale, instances=instancesFromLinesByFile(linesByFile), properties=properties, gap_note=gap_note, should_flag=should_flag);

// Root wrapper for SpecimenIssues
local root(items) = { items: items };

{
  // exported symbols
  issueSingle: issueSingle,
  issueMulti: issueMulti,
  issueMultiFromLines: issueMultiFromLines,
  root: root,
}