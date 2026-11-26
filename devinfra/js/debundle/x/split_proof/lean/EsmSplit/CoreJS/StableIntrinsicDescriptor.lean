import EsmSplit.CoreJS.Move
import EsmSplit.CoreJS.HostProfile

namespace CoreJS

/-- A stable global binding and one stable data property of its receiver. -/
structure StableIntrinsic where
  id : String
  binding : String
  owner : String
  key : String
  value : HostValue
  premise : String
  deriving DecidableEq

namespace StableIntrinsic

def fromProfile? (profile : HostProfile) (id : String) : Option StableIntrinsic := do
  let [path, version] := id.splitOn "@" | none
  guard (version == "1")
  let [binding, key] := path.splitOn "." | none
  let global ← profile.globalEntry? binding
  guard !global.recordedValue
  let owner ← global.identity
  let bindingPremise ← global.premise
  let entry ← profile.memberEntry? binding key
  let value ← match entry.dataValue, entry.identity with
    | some value, none => some value
    | none, some identity => some (.identity identity)
    | _, _ => none
  let propertyPremise ← entry.premise
  let propertyValue := match value with
    | .identity identity => s!"the stable host reference {identity}"
    | .number bits => s!"a Number with binary64 bits {bits.toNat}"
  return ⟨id, binding, owner, key, value,
    s!"the ambient binding {binding} returns {owner} throughout initialization; {propertyPremise}; it returns {propertyValue}"⟩

/-- Parse a host profile and resolve every selected stable intrinsic through its
layer entries. Certification separately enforces the structural-mode requirement. -/
def readContract (j : Lean.Json) : Except String (HostProfile × List StableIntrinsic) := do
  let profile ← HostProfile.read j
  let ids ← match j.getObjVal? "stableIntrinsicValues" with
    | .error _ => pure []
    | .ok values => (← values.getArr?).toList.mapM Lean.Json.getStr?
  let intrinsics ← ids.mapM fun id =>
    match fromProfile? profile id with
    | some intrinsic => pure intrinsic
    | none => throw s!"host profile does not define stable intrinsic {id}"
  return (profile, intrinsics)

end StableIntrinsic
end CoreJS
