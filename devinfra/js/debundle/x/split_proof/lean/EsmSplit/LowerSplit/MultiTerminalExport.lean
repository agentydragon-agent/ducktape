import EsmSplit.LowerSplit.TerminalExportArtifact

/-! Proof-only bridge for sequential static-data splits with one trailing local
export list. The plan and emitter consume the authored original-node request;
only executable selector resolution omits the checked metadata selector. -/

namespace EsmSplit.LowerSplit.MultiTerminalExport

open Lean (Json)
open CoreJS CoreJS.LinkedBehavior
open EsmSplit.LowerSplit.SparseArtifact (classify sourceBundle executableLabels)

private def witness {α : Type} (result : Except String α) :
    Except String (Σ value : α, PLift (result = .ok value)) := do
  match h : result with
  | .ok value => return ⟨value, ⟨h⟩⟩
  | .error why => throw why

def executableRequest (request : EsmSplit.Spec) (terminal : Nat) : EsmSplit.Spec :=
  { request with order := [], sequential := false, modules := request.modules.map fun (owner, selectors) =>
    (owner, selectors.filter fun selector => match selector with
      | .stmt ordinal => ordinal != terminal
      | .name _ => true) }

def metadataClaims (request : EsmSplit.Spec) (terminal : Nat) : List (Nat × String) :=
  request.modules.flatMap fun (owner, selectors) => selectors.filterMap fun selector =>
    match selector with
    | .stmt ordinal => if ordinal == terminal then some (terminal, owner) else none
    | .name _ => none

structure Prepared (original : Json) (sourceText : String) (request : EsmSplit.Spec) where
  nodes : Array Json
  nodesMatch : ESTreeUnits.checkedNodes original sourceText = .ok nodes
  source : Program
  sourceMatch : LinkedInput.decodeSingletonSource original request.entry = .ok source
  staticData : CheckedSplit.supportsStrictStaticSource source = true
  terminal : Nat
  terminalPosition : terminal + 1 = nodes.size
  placement : ResolvedPlacement.CheckedPlacement source (executableRequest request terminal)
    (CheckedSplit.requestedPlacement source)
  metadata : classify (placement.module.body.map Prod.fst) nodes = .ok [terminal]
  metadataOwner : metadataClaims request terminal = [(terminal, request.entry)]
  sequential : request.sequential = true
  orderUnique : request.order.Nodup
  orderComplete : request.order.Perm ((request.modules.map Prod.fst).filter (· != request.entry))
  plan : EsmSplit.Plan
  planMatch : plan = EsmSplit.mkPlan (sourceBundle nodes) request
  planValid : EsmSplit.Valid (sourceBundle nodes) request plan
  coverage : (plan.mods.flatMap (·.stmts)).Perm (List.range nodes.size)
  entryModule : EsmSplit.Module
  entryMatch : plan.find request.entry = some entryModule
  metadataInEntry : entryModule.stmts.contains terminal = true
  labels : (executableLabels plan (placement.module.body.map Prod.fst)).Perm placement.assignment
  programs : Json
  generated : ESTreeEmit.programs nodes (sourceBundle nodes) plan sourceText = .ok programs

def prepare (original : Json) (sourceText : String) (request : EsmSplit.Spec) :
    Except String (Prepared original sourceText request) := do
  let ⟨nodes, ⟨nodesMatch⟩⟩ ← witness (ESTreeUnits.checkedNodes original sourceText)
  let terminal := nodes.size - 1
  if terminalPosition : terminal + 1 = nodes.size then
    let ⟨source, ⟨sourceMatch⟩⟩ ← witness (LinkedInput.decodeSingletonSource original request.entry)
    if staticData : CheckedSplit.supportsStrictStaticSource source = true then
      let placement ← ResolvedPlacement.resolve source (executableRequest request terminal)
        (CheckedSplit.requestedPlacement source)
      let ⟨actualMetadata, ⟨metadataMatch⟩⟩ ← witness (classify (placement.module.body.map Prod.fst) nodes)
      if sameMetadata : actualMetadata = [terminal] then
        have metadata : classify (placement.module.body.map Prod.fst) nodes = .ok [terminal] := by
          rw [← sameMetadata]
          exact metadataMatch
        if metadataOwner : metadataClaims request terminal = [(terminal, request.entry)] then
          if sequential : request.sequential = true then
            if orderUnique : request.order.Nodup then
              if orderComplete : request.order.Perm ((request.modules.map Prod.fst).filter (· != request.entry)) then
                let bundle := sourceBundle nodes
                let plan := EsmSplit.mkPlan bundle request
                let .isTrue valid := (inferInstance : Decidable (EsmSplit.Valid bundle request plan)) |
                  throw "original-node plan failed validation"
                if coverage : (plan.mods.flatMap (·.stmts)).Perm (List.range nodes.size) then
                  match entryMatch : plan.find request.entry with
                  | none => throw "entry missing from plan"
                  | some entryModule =>
                    if metadataInEntry : entryModule.stmts.contains terminal = true then
                      if labels : (executableLabels plan (placement.module.body.map Prod.fst)).Perm placement.assignment then
                        let ⟨programs, ⟨generated⟩⟩ ← witness (ESTreeEmit.programs nodes bundle plan sourceText)
                        return ⟨nodes, nodesMatch, source, sourceMatch, staticData, terminal, terminalPosition,
                          placement, metadata, metadataOwner, sequential, orderUnique, orderComplete,
                          plan, rfl, valid, coverage, entryModule, entryMatch, metadataInEntry, labels,
                          programs, generated⟩
                      else throw "plan changes executable owners"
                    else throw "terminal export is not in entry"
                else throw "plan does not cover original nodes exactly once"
              else throw "order must cover every nonentry module"
            else throw "duplicate module in order"
          else throw "expected sequential placement"
        else throw "terminal export must be explicitly selected once by entry"
      else throw "expected exactly one terminal local export list"
    else throw "source is outside strict static data"
  else throw "source is empty"

private def noProviders := Json.mkObj []

def Verified (original files : Json) {sourceText request}
    (prepared : Prepared original sourceText request) : Prop :=
  ∃ decoded,
    LinkedInput.decodeSingleton original noProviders files prepared.plan = .ok decoded ∧
    decoded.before = prepared.source ∧
    ResolvedPlacement.Sound prepared.placement .allOutcomes decoded.after

def verify (original files : Json) {sourceText request}
    (prepared : Prepared original sourceText request) : Except String (PLift (Verified original files prepared)) :=
  match lowered : LinkedInput.decodeSingleton original noProviders files prepared.plan with
  | .error reason => .error reason
  | .ok decoded => do
    let some ⟨sourceMatches⟩ := SyntaxMatch.programEq decoded.before prepared.source |
      throw "original lowered differently during verification"
    let ⟨placed⟩ ← checkPlaces prepared.placement.assignment prepared.source decoded.after
    let links ← checkProbePair prepared.source decoded.after
    let checked ← (checkLinkedSchedules [] links.before links.after {}).mapError StructuralRefusal.reason
    match checked with
    | ⟨.allOutcomes, .preservedOrder, ⟨equivalent, exports⟩⟩ =>
      have runs : ScheduleEquivalent .allOutcomes (fun _ => True) prepared.source decoded.after := by
        intro w _ n
        exact equivalent w (by simp [StableIntrinsic.Worlds]) n
      return ⟨⟨decoded, lowered, sourceMatches, placed, exports, runs⟩⟩
    | _ => throw "expected an order-preserved all-outcomes schedule"

theorem verify_sound {original files sourceText request}
    {prepared : Prepared original sourceText request} {proof : PLift (Verified original files prepared)}
    (_accepted : verify original files prepared = .ok proof) : Verified original files prepared := proof.down

#print axioms prepare
#print axioms verify
#print axioms verify_sound

end EsmSplit.LowerSplit.MultiTerminalExport
