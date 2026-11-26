import EsmSplit.CoreJS.TerminalConstConstruction
import EsmSplit.LowerSplit.SparseArtifact

/-! Input-side bridge to the fixed-name CoreJS construction. The AST emitter
and its independently reparsed output are not identified with this model. -/

namespace EsmSplit.LowerSplit.TerminalConstInput

open Lean (Json)
open CoreJS CoreJS.LinkedBehavior CoreJS.TerminalConstConstruction

/-- The model uses the actual planner on footprints derived from the input AST. -/
def modeledCandidate (nodes : Array Json) (value : Float) : Program :=
  splitProgram [(.decl .const "x" (.num value))] (SparseArtifact.sourceBundle nodes)
    (EsmSplit.mkPlan (SparseArtifact.sourceBundle nodes) request)

/-- Input-side grammar, lowering and footprint equalities suffice for the
fixed authored request. No check of the constructed model is assumed. -/
theorem input_model_sound (original : Json) (sourceText : String) (nodes : Array Json) (value : Float)
    (nodesMatch : ESTreeUnits.checkedNodes original sourceText = .ok nodes)
    (metadata : SparseArtifact.classify [0] nodes = .ok [1])
    (sourceMatch : LinkedInput.decodeSingletonSource original "entry.mjs" = .ok (source value))
    (footprints : SparseArtifact.sourceBundle nodes = bundle) :
    ESTreeUnits.checkedNodes original sourceText = .ok nodes ∧
    SparseArtifact.classify [0] nodes = .ok [1] ∧
    LinkedInput.decodeSingletonSource original "entry.mjs" = .ok (source value) ∧
    Places [(0, "provider.mjs")] (source value) (modeledCandidate nodes value) ∧
    SameExports (source value) (modeledCandidate nodes value) ∧
    (∀ w fuel, runProgram w fuel (source value) = runProgram w fuel (modeledCandidate nodes value)) ∧
    (modeledCandidate nodes value).evalOrder = request.order ++ [request.entry] := by
  refine ⟨nodesMatch, metadata, sourceMatch, ?_⟩
  unfold modeledCandidate
  rw [footprints]
  exact planned_sound value

/-! Missing production bridge: prove from the same input-side premises that
`ESTreeEmit.programs` for `mkPlan (sourceBundle nodes) request` succeeds and
that the ASTs it emits decode to `modeledCandidate nodes value`, without a
candidate-side `verify` or equality check. A separate printer/reparse result
is needed for claims about published JavaScript bytes. -/

#print axioms input_model_sound

end EsmSplit.LowerSplit.TerminalConstInput
