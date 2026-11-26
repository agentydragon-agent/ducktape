import EsmSplit.CoreJS.LinkedBehavior
import EsmSplit.CoreJS.DeploymentPlacement
import EsmSplit.CoreJS.Split
import EsmSplit.Split

/-! Model-only construction for a single numeric const and its local export.
The AST emitter/decoder correspondence is a separate obligation. -/

namespace CoreJS.TerminalConstConstruction

open LinkedBehavior

set_option maxRecDepth 16000
set_option maxHeartbeats 4000000

def declaration (value : Float) : Nat × Stmt := (0, .decl .const "x" (.num value))
def sourceModule (value : Float) : Module := ⟨"entry.mjs", [], [declaration value], [("x", "x")]⟩
def provider (value : Float) : Module := ⟨"provider.mjs", [], [declaration value], [("x", "x")]⟩
def entry : Module := ⟨"entry.mjs", [⟨"provider.mjs", [("x", "x")]⟩], [], [("x", "x")]⟩

def source (value : Float) : Program := ⟨"entry.mjs", [sourceModule value]⟩
def construct (value : Float) : Program := ⟨"entry.mjs", [provider value, entry]⟩

/-- Original AST ordinal 1 is the terminal export list; the CoreJS body
contains only ordinal 0. -/
def bundle : EsmSplit.Bundle := [
  { src := "", defs := ["x"] },
  { src := "", eager := ["x"], exports := [("x", some "x")] }]

def request : EsmSplit.Spec := {
  entry := "entry.mjs"
  modules := [("provider.mjs", [.stmt 0]), ("entry.mjs", [.stmt 1])]
  order := ["provider.mjs"]
  sequential := true
}

/-- This is the ordinary planner and CoreJS split constructor. Metadata has
no executable CoreJS statement but supplies the entry export and import. -/
def planned (value : Float) : Program :=
  splitProgram [(.decl .const "x" (.num value))] bundle (EsmSplit.mkPlan bundle request)

theorem planned_eq_construct (value : Float) : planned value = construct value := by
  cbv

private def scope : Env := ⟨[("x", ⟨1, 0⟩)], .undef, none⟩
private def ready (w : World) : State w :=
  { initialState w 1 with cells := #[#[], #[⟨none, false⟩]] }

private def sourceLink (value : Float) (w : World) : CheckedLink (source value) w :=
  ⟨[(sourceModule value, scope)], ready w, by cbv⟩
private def constructedLink (value : Float) (w : World) : CheckedLink (construct value) w :=
  ⟨[(provider value, scope), (entry, scope)], ready w, by cbv⟩

/-- Both entry exports denote the same original binding cell, independently
of the initialized value and host world. -/
theorem exact_cell (value : Float) (w : World) :
    LinkedBehavior.exports w (source value) = some [("x", ⟨1, 0⟩)] ∧
    LinkedBehavior.exports w (construct value) = some [("x", ⟨1, 0⟩)] := by
  constructor <;> cbv

/-- The constructed graph retains the authored original executable ordinal. -/
theorem placement (value : Float) : Places [(0, "provider.mjs")] (source value) (construct value) := by
  unfold Places
  constructor
  · decide
  · constructor
    · conv => lhs; cbv
      exact List.Perm.refl _
    · conv => lhs; cbv

/-- The entry exports the same live cell for every world. -/
theorem exports (value : Float) : SameExports (source value) (construct value) := by
  apply sameExports_of_match
  intro w
  rw [exportsMatch_from_checked (sourceLink value w) (constructedLink value w)]
  rfl

/-- Linking and execution preserve the complete bounded result for every world,
including abrupt outcomes and fuel exhaustion. -/
theorem runs (value : Float) (w : World) (fuel : Nat) :
    runProgram w fuel (source value) = runProgram w fuel (construct value) := by
  apply run_eq_of_ordered_links fuel (sourceLink value w) (constructedLink value w)
  · rfl
  · rfl

/-- The constructor carries the modeled placement, live exports and full
bounded behavior; the proof uses no candidate-side acceptance check. -/
theorem construct_sound (value : Float) :
    Places [(0, "provider.mjs")] (source value) (construct value) ∧
    SameExports (source value) (construct value) ∧
    ∀ w fuel, runProgram w fuel (source value) = runProgram w fuel (construct value) :=
  ⟨placement value, exports value, runs value⟩

/-- The existing planner and model constructor satisfy the same obligations. -/
theorem planned_sound (value : Float) :
    Places [(0, "provider.mjs")] (source value) (planned value) ∧
    SameExports (source value) (planned value) ∧
    (∀ w fuel, runProgram w fuel (source value) = runProgram w fuel (planned value)) ∧
    (planned value).evalOrder = request.order ++ [request.entry] := by
  rw [planned_eq_construct]
  exact ⟨(construct_sound value).1, (construct_sound value).2.1,
    (construct_sound value).2.2, by cbv⟩

#print axioms exact_cell
#print axioms planned_eq_construct
#print axioms planned_sound
#print axioms construct_sound

end CoreJS.TerminalConstConstruction
