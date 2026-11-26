import EsmSplit.LowerSplit.TerminalExportArtifact
import EsmSplit.LowerSplit.TerminalConstInputBridge

/-! Test-only staging harness for the terminal export artifact proof. -/

open Lean (Json toJson)
open EsmSplit EsmSplit.SplitFiles EsmSplit.LowerSplit

private def run (manifestPath out : System.FilePath) (checkOnly : Bool) : IO Unit := do
  let manifest ← readDeploymentManifest manifestPath
  let [chunk] := manifest.chunks | throw (IO.userError "expected one original module")
  let .authored spec := chunk.placement | throw (IO.userError "expected an authored spec")
  unless javascriptSource chunk.source && (spec.modules.map Prod.fst).all (·.endsWith ".mjs") do
    throw (IO.userError "expected JavaScript input and .mjs output modules")
  let out ← IO.ofExcept (outputDirectory out)
  IO.FS.withTempDir fun work => do
    let input ← readBundle chunk.source work true false
    let prepared ← match TerminalExportArtifact.attempt input.program input.source spec with
      | .notApplicable => throw (IO.userError "terminal-export-not-applicable")
      | .refused reason => throw (IO.userError reason)
      | .prepared prepared => pure prepared
    let part : OutputPart := { programs := prepared.programs, source := input.source, input := input.input, work }
    let verified ← certifyOutput (α := Unit) [part] (Json.mkObj []) out work checkOnly false fun files =>
      match TerminalExportArtifact.verify input.program files prepared with
      | .ok _ => pure (.ok ())
      | .error reason => pure (.error { reason })
    IO.ofExcept (verified.mapError (·.reason))

def main (args : List String) : IO UInt32 := do
  if let [mode, manifestPath] := args then
    if mode == "--check-source" || mode == "--probe-emission" then
      try
        let manifest ← readDeploymentManifest manifestPath
        let [chunk] := manifest.chunks | throw (IO.userError "expected one original module")
        let .authored _ := chunk.placement | throw (IO.userError "expected an authored spec")
        let manifestJson ← readJson manifestPath
        let [chunkJson] ← IO.ofExcept (manifestJson.getObjValAs? (List Json) "chunks") |
          throw (IO.userError "expected one manifest chunk")
        let specPath ← IO.ofExcept (chunkJson.getObjValAs? String "spec")
        let specText ← IO.FS.readFile specPath
        IO.FS.withTempDir fun work => do
          let input ← readBundle chunk.source work true false
          let admitted ← IO.ofExcept (TerminalConstInputBridge.admit input.program input.source specText)
          if mode == "--probe-emission" then
            -- A diagnostic example only. This equality is not an admission
            -- premise or a proof of the quantified emitter correspondence.
            let plan := EsmSplit.mkPlan (SparseArtifact.sourceBundle admitted.nodes)
              CoreJS.TerminalConstConstruction.request
            let programs ← IO.ofExcept (ESTreeEmit.programs admitted.nodes
              (SparseArtifact.sourceBundle admitted.nodes) plan input.source)
            let decoded ← IO.ofExcept (CoreJS.LinkedInput.decodeSingleton input.program (Json.mkObj []) programs plan)
            let target := TerminalConstInput.modeledCandidate admitted.nodes admitted.value
            unless (CoreJS.SyntaxMatch.programEq decoded.after target).isSome do
              throw (IO.userError "emitter example differs from the modeled candidate")
          pure ()
        IO.println (if mode == "--check-source" then "source admitted" else "emitter example matched")
        return 0
      catch error =>
        IO.eprintln error.toString
        return 1
  let (level, args) := takeFlag "--require" args
  let requested := level.getD "normal-completion"
  let checkOnly := args.contains "--check-output"
  let fields := [("requested", toJson requested)]
  try
    unless requested == "all-outcomes" || requested == "normal-completion" do
      throw (IO.userError "unsupported guarantee")
    let [manifestPath, out] := args.filter (· != "--check-output") |
      throw (IO.userError "expected <deployment.json> <outdir>")
    run manifestPath out checkOnly
    IO.println (Json.mkObj (fields ++ [("status", toJson "certified"), ("guarantee", toJson "all-outcomes")])).compress
    return 0
  catch e =>
    IO.println (Json.mkObj (fields ++ [("status", toJson "rejected"), ("guarantee", .null),
      ("reason", toJson e.toString)])).compress
    return 1
