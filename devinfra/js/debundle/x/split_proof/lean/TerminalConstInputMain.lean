import EsmSplit.LowerSplit.TerminalConstInput

/-! Test-only witness that a parsed public fixture satisfies the input premises. -/

open Lean CoreJS CoreJS.TerminalConstConstruction EsmSplit.LowerSplit

deriving instance DecidableEq for EsmSplit.Stmt

private def check (original : Json) : Except String Unit := do
  let sourceText ← original.getObjValAs? String "sourceText"
  match nodesMatch : ESTreeUnits.checkedNodes original sourceText with
  | .error why => throw why
  | .ok nodes =>
    match metadata : SparseArtifact.classify [0] nodes with
    | .ok [1] =>
      match sourceMatch : LinkedInput.decodeSingletonSource original "entry.mjs" with
      | .error why => throw why
      | .ok decoded =>
        let some ⟨same⟩ := SyntaxMatch.programEq decoded (source 1) |
          throw "fixture source did not decode as the fixed numeric declaration"
        have exactSource : LinkedInput.decodeSingletonSource original "entry.mjs" = .ok (source 1) := by
          rw [← same]
          exact sourceMatch
        if footprints : SparseArtifact.sourceBundle nodes = bundle then
          have sound := TerminalConstInput.input_model_sound original sourceText nodes 1
            nodesMatch metadata exactSource footprints
          let _ := sound
          pure ()
        else throw "fixture footprints differ from the fixed input bundle"
    | _ => throw "fixture does not have terminal metadata at ordinal 1"

def main : IO UInt32 := do
  let input ← IO.ofExcept (Json.parse (← (← IO.getStdin).getLine))
  match check input with
  | .ok _ => IO.println "input premises hold"; return 0
  | .error why => IO.eprintln why; return 1
