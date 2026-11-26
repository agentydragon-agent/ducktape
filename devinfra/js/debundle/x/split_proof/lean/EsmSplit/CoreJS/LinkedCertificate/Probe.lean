import EsmSplit.CoreJS.LinkedCertificate.Proof
import EsmSplit.CoreJS.LinkedCertificate.QuoteCoreJS
import EsmSplit.CoreJS.LinkedPivotCertificate
import EsmSplit.CoreJS.ProbeReplay
import EsmSplit.CoreJS.StateMatch

namespace CoreJS.LinkedBehavior

/-- The constructor, application and literal nodes used to quote a probe observation. -/
private inductive ProbeTerm where
  | app (fn arg : ProbeTerm)
  | const (name : Lean.Name)
  | str (value : String)
  | nat (value : Nat)
  deriving DecidableEq

private def probeTerm? : Lean.Expr → Option ProbeTerm
  | .app f x => return .app (← probeTerm? f) (← probeTerm? x)
  | .const n _ => some (.const n)
  | .lit (.strVal s) => some (.str s)
  | .lit (.natVal n) => some (.nat n)
  | _ => none

/-! `State World.probe` has a closed shape. Keep a canonical projection of every
field in the run's final state; the probe's host state is `Unit`. Closures retain
their full code and environment through `Obj.code`. `ToExpr` quotes floats
by their IEEE bit patterns. -/
private structure ProbeStateObservation where
  heap : List (List CoreJS.Obj)
  cells : List (List CoreJS.Binding)
  region : Nat
  out : List String
  worldState : Unit
  handed : List CoreJS.Addr
  deriving Lean.ToExpr

private def observeProbeState (profile : HostPremises) (state : CoreJS.State (profile.specialize CoreJS.World.probe)) : ProbeStateObservation :=
  { heap := state.heap.toList.map Array.toList
    cells := state.cells.toList.map Array.toList
    region := state.region
    out := state.out.toList
    worldState := state.world.state
    handed := state.world.handed.toList }

/-- Compare the complete state of two completed executions in the concrete probe.
This is a refusal check only; matching probes still go through the all-world proof. -/
def probeStatesEqual (profile : HostPremises) (left right : CoreJS.State (profile.specialize CoreJS.World.probe)) : Bool :=
  let leftTerm := Lean.toExpr (observeProbeState profile left)
  let rightTerm := Lean.toExpr (observeProbeState profile right)
  -- Equal quotations need no projection. On a difference compare only the constructor data,
  -- retaining the same treatment of universe levels and unsupported nodes.
  leftTerm.equal rightTerm || decide (probeTerm? leftTerm = probeTerm? rightTerm)

/-- If both concrete runs finish and their complete state projections differ,
the runs' final results cannot be the shared result required by `Equivalent`.
The projection need not be injective: equality of states implies equality of
their quoted projections, which is enough to make a mismatch decisive. -/
theorem probeObservationMismatchRefutesEquivalent (profile : HostPremises) {source candidate : Program} {fuel : Nat}
    {sourceState candidateState : CoreJS.State (profile.specialize CoreJS.World.probe)}
    (sourceRun : CoreJS.runProgram (profile.specialize CoreJS.World.probe) fuel source = .ok () sourceState)
    (candidateRun : CoreJS.runProgram (profile.specialize CoreJS.World.probe) fuel candidate = .ok () candidateState)
    (different : probeStatesEqual profile sourceState candidateState = false) :
    ¬ Equivalent source candidate := by
  apply different_probe_states_refute_equivalence sourceRun candidateRun
  rintro rfl
  simp [probeStatesEqual] at different

/-- The canonical links shared by strategy checks on the same decoded pair. -/
structure CheckedProbePair (source candidate : Program) where
  before : CheckedLink source World.probe
  after : CheckedLink candidate World.probe

def checkProbePair (source candidate : Program) : Except String (CheckedProbePair source candidate) := do
  let before ← (checkLink source).mapError ("original linker: " ++ ·)
  let after ← (checkLink candidate).mapError ("candidate linker: " ++ ·)
  return ⟨before, after⟩

/-- Typed syntax categories for the linked schedules used by replay. -/
def CheckedProbePair.replayBlockers {source candidate : Program}
    (pair : CheckedProbePair source candidate) : List ReplayBlocker :=
  (replayScheduleBlockers (unitsOf pair.before.linked) ++
    replayScheduleBlockers (unitsOf pair.after.linked)).eraseDups

/-- Successful concrete runs at the same fuel and with the same host premises.
Compiled replay uses these runs when lifting the result to other worlds. -/
structure ProbeWitness (source candidate : Program) where
  premises : HostPremises
  fuel : Nat
  sourceState : State (premises.specialize World.probe)
  candidateState : State (premises.specialize World.probe)
  sourceRun : runProgram (premises.specialize World.probe) fuel source = .ok () sourceState
  candidateRun : runProgram (premises.specialize World.probe) fuel candidate = .ok () candidateState
  statesAgree : probeStatesEqual premises sourceState candidateState = true

private def premisedStateAgreement (premises : HostPremises)
    (sourceState candidateState : State (premises.specialize World.probe)) :
    Option (PLift (sourceState = candidateState)) := by
  letI : DecidableEq (premises.specialize World.probe).σ := by
    change DecidableEq Unit
    infer_instance
  exact StateMatch.state sourceState candidateState

private theorem replayPremisedEquivalentFor {premises : HostPremises} {source candidate : Program} {fuel : Nat}
    {sourceState candidateState : State (premises.specialize World.probe)}
    (sourceReplay : ∀ w, runProgram (premises.specialize w) fuel source =
      .ok () (replaceWorld (premises.specialize w) sourceState))
    (candidateReplay : ∀ w, runProgram (premises.specialize w) fuel candidate =
      .ok () (replaceWorld (premises.specialize w) candidateState))
    (statesAgree : sourceState = candidateState) : EquivalentFor premises source candidate := by
  by_cases empty : premises = {}
  · subst premises
    apply of_runs fuel
    intro w
    have satisfied : ({} : HostPremises).Satisfied w := by
      simp [HostPremises.Satisfied]
    have sourceRun := sourceReplay w
    have candidateRun := candidateReplay w
    rw [← statesAgree] at candidateRun
    have specialized := HostPremises.specialize_eq ({} : HostPremises) w satisfied
    have sourceRunAtWorld : runProgram w fuel source = .ok () (replaceWorld w sourceState) := by
      have transport := congrArg
        (fun world : World => runProgram world fuel source = .ok () (replaceWorld world sourceState))
        specialized
      exact transport.mp sourceRun
    have candidateRunAtWorld : runProgram w fuel candidate = .ok () (replaceWorld w sourceState) := by
      have transport := congrArg
        (fun world : World => runProgram world fuel candidate = .ok () (replaceWorld world sourceState))
        specialized
      exact transport.mp candidateRun
    exact ⟨_, sourceRunAtWorld, candidateRunAtWorld⟩
  · simp [EquivalentFor, empty]
    intro w satisfied
    have sourceRun := sourceReplay w
    have candidateRun := candidateReplay w
    rw [← statesAgree] at candidateRun
    have specialized := premises.specialize_eq w satisfied
    have sourceRunAtWorld : runProgram w fuel source = .ok () (replaceWorld w sourceState) := by
      have transport := congrArg
        (fun world : World => runProgram world fuel source = .ok () (replaceWorld world sourceState))
        specialized
      exact transport.mp sourceRun
    have candidateRunAtWorld : runProgram w fuel candidate = .ok () (replaceWorld w sourceState) := by
      have transport := congrArg
        (fun world : World => runProgram world fuel candidate = .ok () (replaceWorld world sourceState))
        specialized
      exact transport.mp candidateRun
    exact ⟨replaceWorld w sourceState,
      ⟨fuel, sourceRunAtWorld, by simp⟩,
      ⟨fuel, candidateRunAtWorld, by simp⟩⟩

theorem CheckedProbePair.sameExports {source candidate : Program} (pair : CheckedProbePair source candidate)
    (exportsMatched : exportsMatchFrom pair.before pair.after = true) : SameExports source candidate := by
  apply sameExports_of_match
  intro w
  rw [exportsMatch_from_checked (pair.before.forWorld w) (pair.after.forWorld w)]
  exact exportsMatched

/-- A compiled replay check. It accepts only when both programs have a
successful probe run, their complete probe states match, both reached schedules
have replay witnesses, and their public exports match. -/
def replayPremisedPrograms {source candidate : Program}
    (pair : CheckedProbePair source candidate) (probe : ProbeWitness source candidate) :
    Option (PLift (EquivalentFor probe.premises source candidate ∧ SameExports source candidate)) := do
  let allowLogical := source.modules.length == 1 && source.modules.all (fun m => m.imports.isEmpty)
  let sourceSupported ← replayPremisedDynamicWitness (premises := probe.premises) probe.fuel allowLogical pair.before
  let candidateSupported ← replayPremisedDynamicWitness (premises := probe.premises) probe.fuel allowLogical pair.after
  let stateAgreement ← premisedStateAgreement probe.premises probe.sourceState probe.candidateState
  if exportsMatched : exportsMatchFrom pair.before pair.after then
    return ⟨⟨replayPremisedEquivalentFor
        (sourceSupported.down probe.sourceState probe.sourceRun) (candidateSupported.down probe.candidateState probe.candidateRun)
        stateAgreement.down,
      pair.sameExports exportsMatched⟩⟩
  else none

#audit_linked_programs probeObservationMismatchRefutesEquivalent
#audit_linked_programs replayPremisedEquivalentFor
#print axioms CheckedProbePair.sameExports
#audit_linked_programs CheckedProbePair.sameExports
#audit_linked_programs replayPremisedPrograms

inductive RefusalCode where
  | probeMismatch | probeThrow | probeUnknown | probeFuel | proofPreparation

def RefusalCode.label : RefusalCode → String
  | .probeMismatch => "probe_mismatch"
  | .probeThrow => "probe_throw"
  | .probeUnknown => "probe_unknown"
  | .probeFuel => "probe_fuel"
  | .proofPreparation => "proof_preparation"

structure Refusal where
  code : RefusalCode
  reason : String
  observation : Option Lean.Json := none

private structure ValuePair where
  path : List Lean.Json
  original : Val
  candidate : Val

private def pathKey : PropertyKey → Lean.Json
  | .str name => .str name
  | .wellKnownSymbol sym => Lean.Json.mkObj [("symbol", .str sym.description)]
  | .symbol a => Lean.Json.mkObj [("symbol", .str "fresh"), ("region", Lean.toJson a.region), ("index", Lean.toJson a.index)]

private def displayValue : Val → String
  | .undef => "undefined"
  | .null => "null"
  | .bool b => toString b
  | .num n => if n.toBits == 0x8000000000000000 then "-0" else toString n
  | .str s => (s.take 160).toString.quote
  | .wellKnownSymbol sym => sym.description
  | .symbol a => s!"symbol@{a.region}.{a.index}"
  | .obj _ => "object"
  | .host n => "host value " ++ n
  | .error k msg => s!"{repr k}: {(msg.take 160).toString.quote}"

/-- Inspect exported cells and their immediate own data properties without calling JS. -/
private def observeExports (profile : HostPremises) (source candidate : Program)
    (original split : State (profile.specialize World.probe)) : List ValuePair := Id.run do
  let world := profile.specialize World.probe
  let a := (exports world source).getD []
  let b := (exports world candidate).getD []
  let mut values := []
  for (name, addr) in a do
    let some left := (original.cellAt addr).bind (·.value) | continue
    let some right := ((b.lookup name).bind split.cellAt).bind (·.value) | continue
    values := ⟨[.str name], left, right⟩ :: values
    if let (.obj l, .obj r) := (left, right) then
      if let (some l, some r) := (original.objAt l, split.objAt r) then
        let properties := Std.HashMap.ofList r.props
        for (key, value) in l.props do
          if let (.data a .., some (.data b ..)) := (value, properties[key]?) then
            values := ⟨[.str name, pathKey key], a, b⟩ :: values
  return values.reverse

private def firstExportDifference (values : List ValuePair) : Option Lean.Json := Id.run do
  let mut seenOriginal : Std.HashMap (Nat × Nat) ((Nat × Nat) × List Lean.Json) := {}
  let mut seenSplit : Std.HashMap (Nat × Nat) ((Nat × Nat) × List Lean.Json) := {}
  for ⟨path, original, split⟩ in values do
    if let (.obj a, .obj b) := (original, split) then
      let l := (a.region, a.index)
      let r := (b.region, b.index)
      let detail (earlier : List Lean.Json) (aliased : Bool) := Lean.Json.mkObj [
        ("kind", Lean.toJson "alias"), ("paths", Lean.toJson [earlier, path]),
        ("original_alias", Lean.toJson aliased), ("split_alias", Lean.toJson (!aliased))]
      if let some (previous, earlier) := seenOriginal[l]? then
        if previous != r then return some (detail earlier true)
      if let some (previous, earlier) := seenSplit[r]? then
        if previous != l then return some (detail earlier false)
      seenOriginal := seenOriginal.insert l (r, path)
      seenSplit := seenSplit.insert r (l, path)
    else if Lean.toExpr original != Lean.toExpr split then
      return some (Lean.Json.mkObj [
        ("kind", Lean.toJson "value"), ("path", Lean.toJson path),
        ("original", Lean.toJson (displayValue original)), ("split", Lean.toJson (displayValue split))])
  return none

/-- Only fuel exhaustion can be resolved by a larger witness. A normal probe
selects a witness for the kernel proof. If both runs finish but their complete
states differ, the theorem above proves that no all-world certificate can hold. -/
private def probeWitnessAt (profile : HostPremises) (source candidate : Program) (fuel : Nat) :
    Except Refusal (Option (ProbeWitness source candidate)) := do
  match sourceRun : runProgram (profile.specialize World.probe) fuel source with
  | .ok () sourceState =>
    match candidateRun : runProgram (profile.specialize World.probe) fuel candidate with
    | .ok () candidateState =>
      match statesAgree : probeStatesEqual profile sourceState candidateState with
      | true => return some ⟨profile, fuel, sourceState, candidateState, sourceRun, candidateRun, statesAgree⟩
      | false =>
        let _ : ¬ Equivalent source candidate :=
          probeObservationMismatchRefutesEquivalent profile sourceRun candidateRun statesAgree
        throw ⟨.probeMismatch, "probe executions completed normally with different final states",
          firstExportDifference (observeExports profile source candidate sourceState candidateState)⟩
    | .fuel => return none
    | .throw .. => throw ⟨.probeThrow, "split threw during linked initialization", none⟩
    | .unknown why _ => throw ⟨.probeUnknown, s!"split reached an unknown result during linked initialization: {why}", none⟩
  | .fuel => return none
  | .throw .. => throw ⟨.probeThrow, "original threw during linked initialization", none⟩
  | .unknown why _ => throw ⟨.probeUnknown, s!"original reached an unknown result during linked initialization: {why}", none⟩

/-- Evaluating a flat record uses one level of interpreter fuel per property.
Reserve the usual depth for its expressions and surrounding declaration. -/
private def recordFuelLimit (source : Program) : Nat := Id.run do
  let mut width := 0
  for m in source.modules do
    for (_, s) in m.body do
      if let .decl _ _ (.obj props) := s then
        width := max width props.length
  return min 2048 (64 + width)

private def findProbe (profile : HostPremises) (source candidate : Program) : Except Refusal (ProbeWitness source candidate) := do
  let test := probeWitnessAt profile source candidate
  for fuel in [16, 32, 64] do
    if let some witness ← test fuel then return witness
  let limit := recordFuelLimit source
  if limit > 64 then
    if let some witness ← test limit then return witness
  throw ⟨.probeFuel, s!"linked initialization exhausted the fuel search budget ({limit})", none⟩

/-- Combine dynamic observations from both concrete executions with the premises needed by
profile-directed lowering in either complete CoreJS tree. The latter remain required when
the lowered operation is in an inactive branch or an uncalled function: the lowering rule
already used that host description to encode the retained syntax. -/
private inductive ProfileUse where
  | prim (operation : Prim)
  | unary (operation : UnOp)

mutual
  private partial def profileUsesExpr : Expr → List ProfileUse
    | .func f => profileUsesFunc f
    | .obj props => props.flatMap profileUsesProp
    | .arr elems => elems.flatMap profileUsesExpr
    | .spreadArg source => profileUsesExpr source
    | .cls _ _ ctor members => profileUsesFunc ctor ++ members.flatMap profileUsesClassMember
    | .derived _ _ parent members ctor =>
      profileUsesExpr parent ++ members.flatMap profileUsesClassMember ++
        (ctor.toList.flatMap fun (prefixStmts, call, f) =>
          prefixStmts.flatMap profileUsesStmt ++ profileUsesSuperCall call ++ profileUsesFunc f)
    | .get o k | .getOptional o k | .delete o k => profileUsesExpr o ++ profileUsesExpr k
    | .hasProp k o => profileUsesExpr k ++ profileUsesExpr o
    | .getSuper k => profileUsesExpr k
    | .assign target rhs | .assignOp target _ rhs | .assignLogical target _ rhs =>
      profileUsesTarget target ++ profileUsesExpr rhs
    | .update target .. => profileUsesTarget target
    | .call f args | .new f args => profileUsesExpr f ++ args.flatMap profileUsesExpr
    | .callMethod o k args | .callOptionalReceiver o k args =>
      profileUsesExpr o ++ profileUsesExpr k ++ args.flatMap profileUsesExpr
    | .callSuper k args _ => profileUsesExpr k ++ args.flatMap profileUsesExpr
    | .callOptionalCallee o k args property =>
      profileUsesExpr o ++ profileUsesExpr k ++ args.flatMap profileUsesExpr ++ property.toList.flatMap profileUsesExpr
    | .prim operation args => .prim operation :: args.flatMap profileUsesExpr
    | .unary operation e => .unary operation :: profileUsesExpr e
    | .binary _ a b | .logical _ a b => profileUsesExpr a ++ profileUsesExpr b
    | .cond c t e => profileUsesExpr c ++ profileUsesExpr t ++ profileUsesExpr e
    | .seq a b => profileUsesExpr a ++ profileUsesExpr b
    | .undef | .null | .bool _ | .num _ | .str _ | .regexp _ | .var _ | .host _ | .this => []

  private partial def profileUsesFunc : Func → List ProfileUse
    | .mk _ _ _ _ body | .withDefaults _ _ _ _ _ body | .withRest _ _ _ _ _ body =>
      body.flatMap profileUsesStmt
    | .opaque .. => []

  private partial def profileUsesProp : PropDef → List ProfileUse
    | .init key value => profileUsesExpr key ++ profileUsesExpr value
    | .method key f | .getter key f | .setter key f => profileUsesExpr key ++ profileUsesFunc f
    | .proto value => profileUsesExpr value
    | .spread source _ => profileUsesExpr source

  private partial def profileUsesClassMember : ClassMember → List ProfileUse
    | .method _ key f | .getter _ key f | .setter _ key f => profileUsesExpr key ++ profileUsesFunc f
    | .field _ key init => profileUsesExpr key ++ profileUsesExpr init
    | .staticBlock f => profileUsesFunc f

  private partial def profileUsesTarget : Target → List ProfileUse
    | .member o k => profileUsesExpr o ++ profileUsesExpr k
    | .var _ | .frozen _ => []

  private partial def profileUsesSuperCall : SuperCall → List ProfileUse
    | .forward => []
    | .explicit args => args.flatMap profileUsesExpr
    | .conditional _ consequent alternate =>
      consequent.flatMap profileUsesExpr ++ alternate.flatMap profileUsesExpr

  private partial def profileUsesBinding : BindingPattern → List ProfileUse
    | .name _ => []
    | .object properties => properties.flatMap fun (key, value) => profileUsesExpr key ++ profileUsesBinding value
    | .array elements rest =>
      elements.flatMap (Option.elim · [] profileUsesBinding) ++ rest.toList.flatMap profileUsesBinding
    | .defaultValue pattern fallback => profileUsesBinding pattern ++ profileUsesExpr fallback

  private partial def profileUsesStmt : Stmt → List ProfileUse
    | .expr e | .ret e | .throw e => profileUsesExpr e
    | .decl _ _ init => profileUsesExpr init
    | .bind _ pattern init => profileUsesBinding pattern ++ profileUsesExpr init
    | .varDecl _ | .brk | .cont | .opaque .. => []
    | .funDecl f => profileUsesFunc f
    | .ite c t e => profileUsesExpr c ++ profileUsesStmt t ++ profileUsesStmt e
    | .block body => body.flatMap profileUsesStmt
    | .loop init test update body =>
      init.flatMap profileUsesStmt ++ profileUsesExpr test ++ profileUsesExpr update ++ profileUsesStmt body
    | .breakScope body => profileUsesStmt body
    | .forOf _ pattern source body => profileUsesBinding pattern ++ profileUsesExpr source ++ profileUsesStmt body
    | .tryCatch body _ handler => profileUsesStmt body ++ profileUsesStmt handler
    | .tryFinally body finalizer => profileUsesStmt body ++ profileUsesStmt finalizer
end

private def profileUsesProgram (program : Program) : List ProfileUse :=
  program.modules.flatMap fun module => module.body.flatMap fun (_, stmt) => profileUsesStmt stmt

private def recordedPrimitiveFacts (profile : HostProfile) (owner key : String) (operation : Prim) : List String :=
  if profile.recordedPrim owner key == some operation then
    (profile.premiseForOperation (owner ++ "." ++ key)).toList ++
      (if profile.hasCapability .recordedModelPrimitives then
        (profile.capabilityPremise? .recordedModelPrimitives).toList
      else [])
  else []

private def opaqueConstructorFacts (profile : HostProfile) (name : String) : List String :=
  let named := (profile.layers.flatMap (·.opaqueConstructors)).filterMap fun entry =>
    if entry.name == name then entry.premise else none
  let standard :=
    if profile.hasCapability .opaqueStandardConstructors && ECMAScriptHost.opaqueConstructorNames.contains name then
      (profile.capabilityPremise? .opaqueStandardConstructors).toList
    else []
  named ++ standard

private def factsForProfileUse (profile : HostProfile) : ProfileUse → List String
  | .unary .toString => (profile.capabilityPremise? .recordedStringConversion).toList
  | .unary _ => []
  | .prim .freshSymbol =>
    ((profile.globalEntry? "Symbol").bind (·.premise)).toList ++
      (profile.capabilityPremise? .ambientSymbols).toList
  | .prim (.wellKnownSymbol symbol) =>
    ((profile.globalEntry? "Symbol").bind (·.premise)).toList ++
      ((profile.memberEntry? "Symbol" symbol.member).bind (·.premise)).toList ++
      (profile.capabilityPremise? .ambientSymbols).toList
  | .prim (.opaqueConstructorRef name) => opaqueConstructorFacts profile name
  | .prim .log => recordedPrimitiveFacts profile "console" "log" .log
  | .prim .create => recordedPrimitiveFacts profile "Object" "create" .create
  | .prim .defineProperty => recordedPrimitiveFacts profile "Object" "defineProperty" .defineProperty
  | .prim .getPrototypeOf => recordedPrimitiveFacts profile "Object" "getPrototypeOf" .getPrototypeOf
  | .prim .setPrototypeOf => recordedPrimitiveFacts profile "Object" "setPrototypeOf" .setPrototypeOf
  | .prim .checkArrayFrom | .prim .templateIterable => (profile.capabilityPremise? .arrayFromTemplate).toList
  | .prim _ => []

private def observePremises (profile : HostProfile) (source candidate : Program) : HostPremises := Id.run do
  if profile.isEmpty then return {}
  let world := HostPremises.observations profile
  let limit := max (recordFuelLimit source) (recordFuelLimit candidate)
  let observed := fun (program : Program) =>
    match runProgram world limit program with
    | .ok _ s | .throw _ s | .unknown _ s => s.world.state
    | .fuel => ({} : HostPremises)
  let left := observed source
  let right := observed candidate
  let profileFacts :=
    ((profileUsesProgram source ++ profileUsesProgram candidate).flatMap (factsForProfileUse profile)).eraseDups
  return { typeofBindings := (left.typeofBindings ++ right.typeofBindings).eraseDups.mergeSort (fun a b => a.1 ≤ b.1)
           refs := (left.refs ++ right.refs).eraseDups.reverse,
           profileFacts := (left.profileFacts ++ right.profileFacts ++ profileFacts).eraseDups }

/-- Find the concrete fuel witness before generating the all-world proof. -/
def probeWitness (profile : HostProfile) (source candidate : Program) : Except Refusal (ProbeWitness source candidate) :=
  findProbe (observePremises profile source candidate) source candidate

end CoreJS.LinkedBehavior
