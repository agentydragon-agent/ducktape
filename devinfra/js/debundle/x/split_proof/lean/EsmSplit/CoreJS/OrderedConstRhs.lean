import EsmSplit.CoreJS.TerminalPlanFamily
import EsmSplit.CoreJS.TerminalPlanSelection
import EsmSplit.CoreJS.TerminalFootprints

/-! Source-defined primitive const initializers for an order-preserving full
plan. This is a CoreJS proof boundary: parser/printer and strict JavaScript
observations remain the responsibility of the caller. -/

namespace CoreJS.OrderedConstRhs

/-- The unary operators represented directly by JavaScript source syntax.
The internal coercion operation `.toString` is not itself a unary token. -/
def sourceUnary : UnOp → Bool
  | .toString => false
  | _ => true

/-- Closed, primitive-expression syntax. Reads are restricted to bindings
declared in this source; a forward or self read is retained, including its
modeled temporal-dead-zone result. Binary operators are CoreJS's source
binary operators; `in` and `instanceof` use different constructors. -/
inductive Rhs (names : List Name) : Expr → Prop where
  | undef : Rhs names .undef
  | null : Rhs names .null
  | bool (b : Bool) : Rhs names (.bool b)
  | num (n : Float) : Rhs names (.num n)
  | str (s : String) : Rhs names (.str s)
  | read (name : Name) : name ∈ names → Rhs names (.var name)
  | unary {op : UnOp} {arg : Expr} : sourceUnary op = true → Rhs names arg → Rhs names (.unary op arg)
  | binary {op : BinOp} {left right : Expr} : Rhs names left → Rhs names right → Rhs names (.binary op left right)

/-- Check the source syntax without evaluating it or examining a candidate. -/
def checkRhs (names : List Name) : (expr : Expr) → Option (PLift (Rhs names expr))
  | .undef => some ⟨.undef⟩
  | .null => some ⟨.null⟩
  | .bool b => some ⟨.bool b⟩
  | .num n => some ⟨.num n⟩
  | .str s => some ⟨.str s⟩
  | .var name => if h : name ∈ names then some ⟨.read name h⟩ else none
  | .unary op arg => do
    if h : sourceUnary op = true then
      let ⟨argument⟩ ← checkRhs names arg
      return ⟨.unary h argument⟩
    else none
  | .binary _op left right => do
    let ⟨lhs⟩ ← checkRhs names left
    let ⟨rhs⟩ ← checkRhs names right
    return ⟨.binary lhs rhs⟩
  | _ => none

/-- Every free binding in an admitted initializer belongs to this source. -/
theorem rhs_free {names : List Name} {expr : Expr} (rhs : Rhs names expr) :
    ∀ name ∈ expr.free, name ∈ names := by
  induction rhs with
  | undef | null | bool _ | num _ | str _ => simp [Expr.free]
  | read name member => simpa [Expr.free] using member
  | unary _ _ ih => simpa [Expr.free] using ih
  | binary _ _ left right =>
    intro name member
    simp only [Expr.free, List.mem_append] at member
    exact member.elim (left name) (right name)

/-- Names are taken from the actual source statements, not the output or a
second inferred bundle. Unsupported statements are refused by `checkBody`. -/
def sourceNames (body : List (Nat × Stmt)) : List Name :=
  body.flatMap fun unit => unit.2.bindings.map Prod.fst

/-- Unique const declarations of arbitrary length, with a source-defined RHS. -/
inductive Declarations (names : List Name) : List Name → List (Nat × Stmt) → Prop where
  | nil (earlier) : Declarations names earlier []
  | cons {earlier id name value rest} :
      name ∉ earlier → Rhs names value → Declarations names (name :: earlier) rest →
      Declarations names earlier ((id, .decl .const name value) :: rest)

def checkDeclarations (names : List Name) : (earlier : List Name) → (body : List (Nat × Stmt)) →
    Option (PLift (Declarations names earlier body))
  | earlier, [] => some ⟨.nil earlier⟩
  | earlier, (_, .decl .const name value) :: rest => do
    if fresh : name ∉ earlier then
      let ⟨rhs⟩ ← checkRhs names value
      let ⟨tail⟩ ← checkDeclarations names (name :: earlier) rest
      return ⟨.cons fresh rhs tail⟩
    else none
  | _, _ => none

/-- Proof-carrying source check. The full declaration list fixes the set of
names, so no host/global or candidate-derived binding can be introduced. -/
def checkBody (body : List (Nat × Stmt)) : Option (PLift (Declarations (sourceNames body) [] body)) :=
  checkDeclarations (sourceNames body) [] body

theorem all_const {names earlier : List Name} {body : List (Nat × Stmt)}
    (decls : Declarations names earlier body) :
    ∀ stmt ∈ body.map Prod.snd, ∃ name value, stmt = .decl .const name value := by
  induction decls with
  | nil => simp
  | @cons earlier id name value rest fresh rhs tail ih =>
    intro stmt member
    simp only [List.map_cons, List.mem_cons] at member
    rcases member with rfl | member
    · exact ⟨name, value, rfl⟩
    · exact ih stmt member

/-- Separate source-order read condition for callers whose JavaScript
observation contract cannot admit a reached TDZ exception. This condition
does not assert that every possible operation or host environment is safe. -/
inductive EarlierReads : List Name → List (Nat × Stmt) → Prop where
  | nil (earlier) : EarlierReads earlier []
  | cons {earlier id name value rest} :
      (∀ x ∈ value.free, x ∈ earlier) → EarlierReads (name :: earlier) rest →
      EarlierReads earlier ((id, .decl .const name value) :: rest)

def checkEarlierReads : (earlier : List Name) → (body : List (Nat × Stmt)) →
    Option (PLift (EarlierReads earlier body))
  | earlier, [] => some ⟨.nil earlier⟩
  | earlier, (_, .decl .const name value) :: rest => do
    if reads : ∀ x ∈ value.free, x ∈ earlier then
      let ⟨tail⟩ ← checkEarlierReads (name :: earlier) rest
      return ⟨.cons reads tail⟩
    else none
  | _, _ => none

/-- The checked singleton source has the original dense executable IDs and
its exact public table. No initialized value or execution is inspected. -/
theorem source_shape {input : Program × List EsmSplit.LocalExportUnit}
    (checked : TerminalSource.Checked input) (noImports : checked.source.imports = []) :
    input.1 = TerminalPlanLink.source checked.source.name checked.row.names (checked.source.body.map Prod.snd) := by
  have hm := checked.singleton
  have he := checked.entry
  have hb := ProjectedOrder.terminal_body checked.source checked.terminal
  have hexports := checked.fullTable
  cases h : checked.source with
  | mk name imports body exports =>
    simp only [h] at hm he hb noImports hexports ⊢
    cases hp : input.1 with
    | mk entry modules =>
      simp only [hp] at hm he ⊢
      subst imports
      subst modules
      subst entry
      simp only [TerminalPlanLink.source]
      rw [← hb, ← hexports]

/-- For the actual decoded source and authored full plan, supported RHS
syntax supplies the const-source premise. The other inputs are source/plan
checks, not a proposed behavioral equality or an execution comparison. The
result keeps the complete live exports, all modeled outcomes and original
authored unit owners on the single actual plan. -/
theorem planned_family {input : Program × List EsmSplit.LocalExportUnit}
    (checked : TerminalSource.Checked input) (noImports : checked.source.imports = [])
    (grammar : Declarations (sourceNames checked.source.body) [] checked.source.body)
    (B : EsmSplit.Bundle) (S : EsmSplit.Spec) (entry : EsmSplit.Module)
    (valid : EsmSplit.Valid B S (EsmSplit.mkPlan B S))
    (footprints : MetadataCells.Footprints (checked.source.body.map Prod.snd) B)
    (ordered : ProjectedOrder.Kept (checked.source.body.map Prod.snd) (EsmSplit.mkPlan B S))
    (complete : B.length = checked.row.ordinal + 1)
    (found : (EsmSplit.mkPlan B S).find (EsmSplit.mkPlan B S).entry = some entry)
    (units : entry.stmts = [checked.row.ordinal]) (glue : entry.exports = [])
    (rowFootprint : checked.row.FootprintMatches (B.stmt checked.row.ordinal))
    (sourceDefs : MetadataCells.RowLocalsDefined (checked.source.body.map Prod.snd) B checked.row)
    (selection : TerminalExportPlacement.Selection ⟨checked.source, checked.row.ordinal⟩ S)
    (matching : TerminalPlanSelection.ClaimantsMatch B S selection.selected) :
    LinkedBehavior.SameExports input.1 (splitProgram (checked.source.body.map Prod.snd) B (EsmSplit.mkPlan B S)) ∧
    (∀ w fuel, runProgram w fuel input.1 =
      runProgram w fuel (splitProgram (checked.source.body.map Prod.snd) B (EsmSplit.mkPlan B S))) ∧
    (∀ i, i < B.length → i < (checked.source.body.map Prod.snd).length ∨ i = checked.row.ordinal) ∧
    (selection.selected.map Prod.fst).Nodup ∧
    (∀ m ∈ (EsmSplit.mkPlan B S).mods, ∀ i (hi : i < (checked.source.body.map Prod.snd).length),
      (i, (checked.source.body.map Prod.snd)[i]) ∈
        (moduleOf (checked.source.body.map Prod.snd) B (EsmSplit.mkPlan B S) m).body ↔
          (i, m.name) ∈ selection.selected) ∧
    (checked.row.ordinal, entry.name) ∈ selection.selected ∧
    (∀ owner, (checked.row.ordinal, owner) ∈ selection.selected → owner = entry.name) ∧
    (moduleOf (checked.source.body.map Prod.snd) B (EsmSplit.mkPlan B S) entry).body = [] := by
  have semantics := TerminalPlanFamily.family (all_const grammar) valid footprints ordered
    checked.source.name checked.row entry found units glue rowFootprint sourceDefs
  have shape := source_shape checked noImports
  rw [← shape] at semantics
  have terminal : checked.row.ordinal = (checked.source.body.map Prod.snd).length := by
    simpa using checked.terminal.2
  have ids : checked.source.body.map Prod.fst = List.range (checked.source.body.map Prod.snd).length := by
    simpa using checked.terminal.1
  have selectionFacts := TerminalPlanSelection.selected_owners checked.row terminal complete valid entry found units
    ⟨checked.source, checked.row.ordinal⟩ rfl ids selection matching
  have ownership := TerminalPlanOwnership.all_original_owners checked.row terminal complete valid entry found units
  exact ⟨semantics.1, semantics.2, ownership.1, selection.selectedUnique,
    selectionFacts.1, selectionFacts.2.1, selectionFacts.2.2, ownership.2.2.2.2⟩

-- The syntax check admits nested arithmetic, while the separate earlier-read
-- check distinguishes a forward read. Neither test evaluates a candidate.
example : (checkBody [(0, .decl .const "a" (.num 3)),
    (1, .decl .const "b" (.binary .sub (.var "a") (.unary .neg (.num 1))))]).isSome = true := by decide

example : (checkBody [(0, .decl .const "a" (.var "b")), (1, .decl .const "b" (.bool true))]).isSome = true := by decide

example : (checkEarlierReads [] [(0, .decl .const "a" (.var "b")),
    (1, .decl .const "b" (.bool true))]).isSome = false := by decide

example : (checkBody [(0, .decl .const "a" (.host "console"))]).isSome = false := by decide

#print axioms checkRhs
#print axioms rhs_free
#print axioms checkBody
#print axioms all_const
#print axioms checkEarlierReads
#print axioms source_shape
#print axioms planned_family

end CoreJS.OrderedConstRhs
