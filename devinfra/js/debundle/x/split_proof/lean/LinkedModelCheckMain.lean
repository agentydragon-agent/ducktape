import EsmSplit.LowerSplit.Certified

/-! Test-only check of CoreJS initialization from Acorn-parsed source and candidate modules. -/

open Lean EsmSplit EsmSplit.LowerSplit EsmSplit.SplitFiles

private def check (input : Json) : IO (Except CertificationRefusal Json) := do
  let source ← IO.ofExcept (input.getObjVal? "source")
  let files ← IO.ofExcept (input.getObjVal? "files")
  let spec ← IO.ofExcept (input.getObjValAs? String "spec" >>= parseAuthoredSpec)
  let exportName ← IO.ofExcept (input.getObjValAs? String "export")
  let asts ← IO.ofExcept (source.getObjValAs? String "sourceText" >>= ESTreeUnits.checkedNodes source)
  let bundle := linkedLayoutBundle asts (Effects.footprintUnits asts)
  let plan ← planSplit bundle spec false
  unless ← checkLayout bundle plan (some spec) false do
    throw (IO.userError "invalid linked layout")
  let providers := Json.mkObj []
  match ← prepareSliceEligibility .empty source providers files plan false with
  | .error refusal => return .error refusal.toCertificationRefusal
  | .ok eligibility =>
    let { before, after, .. } := eligibility.deployment
    let ⟨level, _, _⟩ ← IO.ofExcept <|
      (CoreJS.LinkedBehavior.checkStructuralSchedule [] before after {}).mapError
        CoreJS.LinkedBehavior.StructuralRefusal.reason
    let probe := eligibility.probe
    let world := probe.premises.specialize CoreJS.World.probe
    let observe (program : CoreJS.Program) (state : CoreJS.State world) : IO Json := do
      let cell := (CoreJS.LinkedBehavior.exports world program).bind (·.lookup exportName)
      match (cell.bind state.cellAt).bind (·.value) with
      | some (.bool value) => return toJson value
      | some (.num value) => return Json.mkObj [("number", toJson (CoreJS.Num.toString value)), ("bits", toJson (toString value.toBits))]
      | _ => throw (IO.userError s!"expected a Boolean or numeric export: {exportName}")
    return .ok (Json.mkObj [
      ("guarantee", toJson s!"modeled-{level.label}"),
      ("original", ← observe before probe.sourceState),
      ("split", ← observe after probe.candidateState)
    ])

def main : IO UInt32 := do
  let input ← IO.ofExcept (Json.parse (← (← IO.getStdin).getLine))
  match ← check input with
  | .ok result => IO.println result.compress; return 0
  | .error refusal =>
    IO.println (Json.mkObj [
      ("reason_code", toJson refusal.reasonCode),
      ("observation", toJson refusal.observation)
    ]).compress
    return 1
