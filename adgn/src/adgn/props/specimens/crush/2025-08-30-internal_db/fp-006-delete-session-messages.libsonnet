local I = import '../../lib.libsonnet';

// fp-006-delete-session-messages
// False positive: DeleteSessionMessages early-bailout suggestion is unnecessary

I.falsePositive(
  rationale=|||
    A reviewer suggested converting a small loop that performs a conditional delete
    into an early-bailout (continue) style to save one indentation level:

      for _, message := range messages {
          if message.SessionID == sessionID {
              err = s.Delete(ctx, message.ID)
              if err != nil {
                  return err
              }
          }
      }

    Both forms are acceptable: using `if message.SessionID != sessionID { continue }` is valid, but the original form is equally clear and idiomatic. No change is necessary; retain whichever form reads better to maintainers.
  |||,
  filesToRanges={
    'internal/message/message.go': [[160, 172]],
  },
)
