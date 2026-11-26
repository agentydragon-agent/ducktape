import EsmSplit.LowerSplit.TerminalConstInputBridge
import EsmSplit.LowerSplit.TerminalConstTyped

/-! Composition of the independently defined source shape and typed raw-AST
codec. The real emitter and JavaScript printer/reparse boundary remain open. -/

namespace EsmSplit.LowerSplit.TerminalConstCompose

open Lean (Json)
open CoreJS CoreJS.TerminalConstConstruction
open EsmSplit.LowerSplit.TerminalConstInputBridge
open EsmSplit.LowerSplit.TerminalConstTyped

/-- The two proof branches describe the very same raw AST constructor. -/
theorem encode_eq_emittedAST (declaration exportNode : Json) (hashbang : Option String) :
    encode declaration exportNode hashbang = emittedAST declaration exportNode hashbang := by
  rfl

/-- Under source-only decoding facts, K's shared raw AST decodes to the
existing modeled construction. The premises say nothing about a candidate. -/
theorem emitted_decodes (declaration exportNode : Json) (hashbang : Option String)
    (typed : TerminalConstTyped.Source declaration exportNode) :
    TerminalConstTyped.decode (emittedAST declaration exportNode hashbang) = .ok (construct typed.value) := by
  rw [← encode_eq_emittedAST]
  exact admitted_decode declaration exportNode hashbang typed

/-- Explicitly retain the original nodes and the source-value agreement needed
for composition with source admission. These are input facts, not output checks. -/
theorem emitted_sound {original sourceText specText}
    (input : Admitted original sourceText specText) (declaration exportNode : Json)
    (typed : TerminalConstTyped.Source declaration exportNode)
    (nodesMatch : input.nodes = #[declaration, exportNode])
    (valueMatch : typed.value = input.value) :
    input.nodes = #[declaration, exportNode] ∧
    TerminalConstTyped.decode (emittedAST declaration exportNode (sourceHashbang sourceText)) =
      .ok (TerminalConstInput.modeledCandidate input.nodes input.value) ∧
    CoreJS.Places [(0, "provider.mjs")] (source input.value)
      (TerminalConstInput.modeledCandidate input.nodes input.value) ∧
    CoreJS.LinkedBehavior.SameExports (source input.value)
      (TerminalConstInput.modeledCandidate input.nodes input.value) ∧
    (∀ w fuel, CoreJS.runProgram w fuel (source input.value) =
      CoreJS.runProgram w fuel (TerminalConstInput.modeledCandidate input.nodes input.value)) ∧
    (TerminalConstInput.modeledCandidate input.nodes input.value).evalOrder = request.order ++ [request.entry] := by
  have modelEq : TerminalConstInput.modeledCandidate input.nodes input.value = construct input.value := by
    unfold TerminalConstInput.modeledCandidate
    rw [input.footprints]
    exact planned_eq_construct input.value
  have staged := staged_sound declaration exportNode (sourceHashbang sourceText) typed
  rw [valueMatch, ← modelEq] at staged
  rw [← encode_eq_emittedAST]
  exact ⟨nodesMatch, staged⟩

#print axioms encode_eq_emittedAST
#print axioms emitted_decodes
#print axioms emitted_sound

end EsmSplit.LowerSplit.TerminalConstCompose
