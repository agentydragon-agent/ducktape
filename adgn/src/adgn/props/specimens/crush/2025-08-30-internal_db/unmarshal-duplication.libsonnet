local I = import '../../lib.libsonnet';

// iss-016-unmarshal-dedup
// Deduplicate repeated Unmarshal+append patterns when decoding ContentPart wrappers.

I.issue(
  snapshot='crush/2025-08-30-internal_db',
  rationale='The unmarshalling switch in internal/message/message.go repeats the same pattern for each part type: allocate typed var, json.Unmarshal(wrapper.Data, &var), check err, append. This is noisy and error-prone; centralize using a map of constructors/decoders to reduce duplication and make adding new part types simpler.',
  filesToRanges={
    'internal/message/message.go': [[358, 406]],
  },
)
