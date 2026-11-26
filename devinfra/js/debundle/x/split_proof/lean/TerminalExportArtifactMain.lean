import EsmSplit.LowerSplit.TerminalExportArtifact
import EsmSplit.LowerSplit.TerminalConstInputBridge
import EsmSplit.LowerSplit.TerminalConstTyped

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
    if mode == "--check-source" || mode == "--probe-emission" || mode == "--probe-codec-staging" then
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
          if mode == "--probe-codec-staging" then
            let some declaration := admitted.nodes[0]? | throw (IO.userError "missing declaration")
            let some exportNode := admitted.nodes[1]? | throw (IO.userError "missing export")
            let source ← IO.ofExcept (TerminalConstTyped.admitSource declaration exportNode)
            unless (CoreJS.SyntaxMatch.programEq (CoreJS.TerminalConstConstruction.source source.value)
                (CoreJS.TerminalConstConstruction.source admitted.value)).isSome do
              throw (IO.userError "source decoders disagree")
            -- The exact encoder used by the typed theorem constructs the part.
            let programs := TerminalConstTyped.encode declaration exportNode
              (TerminalConstInputBridge.sourceHashbang input.source)
            let part : OutputPart := { programs, source := input.source, input := input.input, work }
            let observed ← IO.mkRef false
            -- This is a diagnostic: always refuse publication after the real
            -- printer and exact reread comparison have run.
            let _ ← certifyOutput (α := Unit) [part] (Json.mkObj []) (work / "probe-output") work false false fun files => do
              let actual ← IO.ofExcept (TerminalConstTyped.decode files)
              let target := CoreJS.TerminalConstConstruction.construct source.value
              if (CoreJS.SyntaxMatch.programEq actual target).isSome then
                observed.set true
              return .error { reason := "diagnostic never publishes output" }
            unless ← observed.get do throw (IO.userError "re-read output differs from the modeled candidate")
          pure ()
        IO.println (if mode == "--check-source" then "source admitted" else
          if mode == "--probe-emission" then "emitter example matched" else "codec staged and reread")
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
