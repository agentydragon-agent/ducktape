import EsmSplit.LowerSplit.TerminalConstInput

/-! Source-only admission for the numeric terminal-export construction.
No output plan, emitted program, linked placement or execution is checked here.
The real emitter-to-model equation and printer/reparse boundary remain separate. -/

namespace EsmSplit.LowerSplit.TerminalConstInputBridge

open Lean (Json)
open CoreJS CoreJS.LinkedBehavior CoreJS.TerminalConstConstruction
open EsmSplit.LowerSplit.SparseArtifact (classify sourceBundle)

deriving instance DecidableEq for EsmSplit.Selector
deriving instance DecidableEq for EsmSplit.Spec
deriving instance DecidableEq for EsmSplit.Stmt

/-- Authored JSON object keys are sorted by `parseAuthoredSpec`. This is the
actual order for the fixed entry/provider names, independent of written order. -/
def parsedRequest : EsmSplit.Spec := request

/-- Input facts for Q's model and the actual authored spec, with no check of
any candidate program, emitted AST, plan validity, placement or execution. -/
structure Admitted (original : Json) (sourceText specText : String) where
  specMatch : EsmSplit.parseAuthoredSpec specText = .ok parsedRequest
  nodes : Array Json
  nodesMatch : ESTreeUnits.checkedNodes original sourceText = .ok nodes
  metadata : classify [0] nodes = .ok [1]
  value : Float
  sourceMatch : LinkedInput.decodeSingletonSource original "entry.mjs" = .ok (source value)
  footprints : sourceBundle nodes = bundle

private def witness {α : Type} (result : Except String α) :
    Except String (Σ value : α, PLift (result = .ok value)) := do
  match h : result with
  | .ok value => return ⟨value, ⟨h⟩⟩
  | .error why => throw why

/-- All comparisons concern only parsed source and authored input. The Float
comes from the actual linked source decoder; no numeric value is assumed. -/
def admit (original : Json) (sourceText specText : String) :
    Except String (Admitted original sourceText specText) := do
  let ⟨spec, ⟨parsed⟩⟩ ← witness (EsmSplit.parseAuthoredSpec specText)
  if specEq : spec = parsedRequest then
    have specMatch : EsmSplit.parseAuthoredSpec specText = .ok parsedRequest := by
      rw [← specEq]
      exact parsed
    let ⟨nodes, ⟨nodesMatch⟩⟩ ← witness (ESTreeUnits.checkedNodes original sourceText)
    let ⟨metadata, ⟨metadataMatch⟩⟩ ← witness (classify [0] nodes)
    if metadataEq : metadata = [1] then
      have metadataExact : classify [0] nodes = .ok [1] := by
        rw [← metadataEq]
        exact metadataMatch
      let ⟨decoded, ⟨sourceMatch⟩⟩ ← witness (LinkedInput.decodeSingletonSource original "entry.mjs")
      let [m] := decoded.modules | throw "expected a single source module"
      let [(0, .decl .const "x" (.num value))] := m.body |
        throw "expected one numeric const declaration named x"
      let some ⟨same⟩ := SyntaxMatch.programEq decoded (source value) |
        throw "source differs from the numeric declaration and its local export"
      have exactSource : LinkedInput.decodeSingletonSource original "entry.mjs" = .ok (source value) := by
        rw [← same]
        exact sourceMatch
      if footprints : sourceBundle nodes = bundle then
        return ⟨specMatch, nodes, nodesMatch, metadataExact, value, exactSource, footprints⟩
      else throw "original source footprints differ from the numeric construction"
    else throw "expected the local export list at original ordinal 1"
  else throw "authored selectors or order differ from the supported request"

/-- The original decoder produces Q's X for the exact numeric value returned by
that decoder, and the actual source satisfies every premise of Q's model lemma. -/
theorem input_sound {original sourceText specText}
    (admitted : Admitted original sourceText specText) :
    EsmSplit.parseAuthoredSpec specText = .ok request ∧
    ESTreeUnits.checkedNodes original sourceText = .ok admitted.nodes ∧
    classify [0] admitted.nodes = .ok [1] ∧
    LinkedInput.decodeSingletonSource original "entry.mjs" = .ok (source admitted.value) ∧
    sourceBundle admitted.nodes = bundle :=
  ⟨by simpa [parsedRequest] using admitted.specMatch, admitted.nodesMatch, admitted.metadata,
    admitted.sourceMatch, admitted.footprints⟩

/-- Q's semantic theorem applies to the original parsed source and its computed
footprints. The authored request has the same entry-first order as the model. -/
theorem modeled_sound {original sourceText specText}
    (admitted : Admitted original sourceText specText) :
    Places [(0, "provider.mjs")] (source admitted.value)
        (TerminalConstInput.modeledCandidate admitted.nodes admitted.value) ∧
    SameExports (source admitted.value) (TerminalConstInput.modeledCandidate admitted.nodes admitted.value) ∧
    (∀ w fuel, runProgram w fuel (source admitted.value) =
      runProgram w fuel (TerminalConstInput.modeledCandidate admitted.nodes admitted.value)) := by
  have modeled := TerminalConstInput.input_model_sound original sourceText admitted.nodes admitted.value
    admitted.nodesMatch admitted.metadata admitted.sourceMatch admitted.footprints
  exact ⟨modeled.2.2.2.1, modeled.2.2.2.2.1, modeled.2.2.2.2.2.1⟩

/-- The remaining AST boundary, stated without assuming or checking it. A
proof must derive this from `Admitted`; printer/reparse identity is separate. -/
def EmissionCorrect {original sourceText specText}
    (admitted : Admitted original sourceText specText) : Prop :=
  let plan := EsmSplit.mkPlan (sourceBundle admitted.nodes) request
  ∃ programs decoded,
    EsmSplit.ESTreeEmit.programs admitted.nodes (sourceBundle admitted.nodes) plan sourceText = .ok programs ∧
    LinkedInput.decodeSingleton original (Json.mkObj []) programs plan = .ok decoded ∧
    decoded.before = source admitted.value ∧
    decoded.after = TerminalConstInput.modeledCandidate admitted.nodes admitted.value

/-! Missing lemma: prove `EmissionCorrect admitted` for every admitted input.
No theorem above assumes this proposition or compares a candidate program. -/

#print axioms admit
#print axioms input_sound
#print axioms modeled_sound

end EsmSplit.LowerSplit.TerminalConstInputBridge
