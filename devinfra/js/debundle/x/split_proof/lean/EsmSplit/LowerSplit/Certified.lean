import EsmSplit.CoreJS.LinkedInput
import EsmSplit.CoreJS.NamedDeclarationSplit
import EsmSplit.CoreJS.TerminalConstructor
import EsmSplit.ESTreeEmit
import EsmSplit.LowerSplit.Input

/-! The public splitter publishes only the output of a proved CoreJS constructor. -/

namespace EsmSplit.LowerSplit

open Lean EsmSplit.SplitFiles
open CoreJS (Guarantee)

private def emitVerdict (requested : String) (outcome : Except String Guarantee)
    (scope : Option String := none) (extra : List (String × Json) := []) : IO UInt32 := do
  let everyEndingMatches := match outcome with
    | .ok .allOutcomes => true
    | _ => false
  let fields := match outcome with
    | .error why => [("status", toJson "rejected"), ("guarantee", Json.null), ("reason", toJson why)]
    | .ok level => [("status", toJson "certified"), ("guarantee", toJson level.label)]
  IO.println (Json.mkObj ([("requested", toJson requested), ("scope", toJson scope),
    ("every_ending_matches", toJson everyEndingMatches)] ++ fields ++ extra)).compress
  return if outcome.isOk then 0 else 1

private def emitRefusal (requested : String) (refusal : CertificationRefusal)
    (scope : Option String := none) : IO UInt32 := do
  let reasonCodeFields := refusal.reasonCode.toList.map fun code => ("reason_code", toJson code)
  let observationFields := refusal.observation.toList.map fun observation => ("observation", observation)
  emitVerdict requested (.error (IO.userError refusal.reason).toString) scope (reasonCodeFields ++ observationFields)

private def noConstructedRule (requested : String) : IO UInt32 :=
  emitRefusal requested ({ reason := "no compiled constructor supports this split; no JavaScript was written", reasonCode := some "no_constructed_rule" } : CertificationRefusal)

/-- A decline tries the next constructor; a constructed result is final,
including any printing or staged readback failure. -/
private def tryNamedDeclarations (requested : String) (chunk : DeploymentChunk) (src : BundleInput)
    (out work : System.FilePath) (checkOnly timings : Bool) : IO (Option UInt32) := do
  let .authored spec := chunk.placement | return none
  unless spec.sequential do return none
  let .ok source := CoreJS.LinkedInput.decodeSingletonSource src.program spec.entry | return none
  let [original] := source.modules | return none
  unless !original.body.isEmpty && original.body.all (fun (_, stmt) =>
      match stmt with | .decl .const _ _ => true | _ => false) do return none
  unless spec.modules.all (fun row => row.1.endsWith ".mjs") do return none
  let .ok constructed := CoreJS.NamedDeclarationSplit.construct source spec | return none
  try
    let programs ← IO.ofExcept (ESTreeEmit.corePrograms constructed.split.program src.source)
    let part : OutputPart := { programs, source := src.source, input := src.input, work }
    let checked ← certifyOutput (α := Unit) [part] (Json.mkObj []) out work checkOnly timings fun _ =>
      pure (.ok ())
    match checked with
    | .ok _ => return some (← emitVerdict requested (.ok .allOutcomes) "named-declarations"
        [("strategy", toJson "compiled-constructor")])
    | .error refusal => return some (← emitRefusal requested refusal "named-declarations")
  catch e => return some (← emitVerdict requested (.error e.toString) "named-declarations")

/-- Construct the terminal-export family from the original nodes, decoded
source and unchanged authored placement. -/
private def tryTerminalDeclarations (requested : String) (chunk : DeploymentChunk) (src : BundleInput)
    (out work : System.FilePath) (checkOnly timings : Bool) : IO (Option UInt32) := do
  let .authored spec := chunk.placement | return none
  unless spec.sequential && spec.modules.all (fun row => row.1.endsWith ".mjs") do return none
  let .ok nodes := ESTreeUnits.checkedNodes src.program src.source | return none
  let .ok input := CoreJS.LinkedInput.decodeSingletonSourceWithLocalExports src.program spec.entry | return none
  let bundle := linkedLayoutBundle nodes (Effects.footprintUnits nodes)
  let .ok built := CoreJS.TerminalConstructor.construct input bundle spec | return none
  try
    let programs ← IO.ofExcept (ESTreeEmit.corePrograms built.program src.source)
    let part : OutputPart := { programs, source := src.source, input := src.input, work }
    let checked ← certifyOutput (α := Unit) [part] (Json.mkObj []) out work checkOnly timings fun _ =>
      pure (.ok ())
    match checked with
    | .ok _ => return some (← emitVerdict requested (.ok .allOutcomes) "terminal-declarations"
        [("strategy", toJson "compiled-constructor")])
    | .error refusal => return some (← emitRefusal requested refusal "terminal-declarations")
  catch e => return some (← emitVerdict requested (.error e.toString) "terminal-declarations")

/-- Unsupported requests refuse; supported requests use the compiled constructor. -/
def certified (args : List String) : IO UInt32 := do
  let (level?, args) := EsmSplit.takeFlag "--require" args
  let requested := level?.getD "all-outcomes"
  unless ["all-outcomes", "normal-completion"].contains requested do
    return ← noConstructedRule requested
  let checkOnly := args.contains "--check-output"
  let args := args.filter (· != "--check-output")
  let [manifestPath, out] := args | return ← noConstructedRule requested
  if args.any (·.startsWith "--") then return ← noConstructedRule requested
  try
    let out ← IO.ofExcept (outputDirectory out)
    let manifest ← readDeploymentManifest manifestPath
    let [chunk] := manifest.chunks | return ← noConstructedRule requested
    let timings := (← IO.getEnv "SPLIT_PROOF_TIMINGS") == some "1"
    IO.FS.withTempDir fun work => do
      let src ← readBundle chunk.source work true timings (← IO.ofExcept chunk.sourceHash)
      if let some verdict ← tryTerminalDeclarations requested chunk src out work checkOnly timings then
        return verdict
      if let some verdict ← tryNamedDeclarations requested chunk src out work checkOnly timings then
        return verdict
      noConstructedRule requested
  catch e => emitVerdict requested (.error e.toString)

end EsmSplit.LowerSplit
