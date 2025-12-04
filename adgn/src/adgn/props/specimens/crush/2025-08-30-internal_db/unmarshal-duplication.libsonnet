local I = import '../../lib.libsonnet';


I.issue(
  rationale='The unmarshalling switch in internal/message/message.go repeats the same pattern for each part type: allocate typed var, json.Unmarshal(wrapper.Data, &var), check err, append. This is noisy and error-prone; centralize using a map of constructors/decoders to reduce duplication and make adding new part types simpler.',
  filesToRanges={
    'internal/message/message.go': [[358, 406]],
  },
)
