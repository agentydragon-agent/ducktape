import EsmSplit.CoreJS.BrowserPageHost
import EsmSplit.CoreJS.NodeHost
import EsmSplit.CoreJS.RecordedNodeHost
import EsmSplit.CoreJS.Value
import Lean.Data.Json

namespace CoreJS

structure HostProfile where
  name : String
  layers : List HostLayer := []
  /-- Merged lookup tables derived from `layers`; host facts are authored only in the layers. -/
  resolvedGlobals : List HostGlobalEntry := []
  resolvedMembers : List HostMemberEntry := []
  deriving DecidableEq, Repr

namespace HostProfile

def label (profile : HostProfile) : String := profile.name

def hasCapability (profile : HostProfile) (capability : HostCapability) : Bool :=
  profile.layers.any fun layer => layer.capabilities.any (·.capability == capability)

def capabilityPremise? (profile : HostProfile) (capability : HostCapability) : Option String :=
  (profile.layers.flatMap (·.capabilities)).findSome? fun entry =>
    if entry.capability == capability then entry.premise else none

private def mergeField {α : Type} [BEq α] (left right : Option α) : Option (Option α) :=
  match left, right with
  | some a, some b => if a == b then some (some a) else none
  | some a, none | none, some a => some (some a)
  | none, none => some none

private def mergePremise (left right : Option String) : Option String :=
  match left, right with
  | some a, some b => some (if a == b then a else s!"{a}; additionally, {b}")
  | some a, none | none, some a => some a
  | none, none => none

private def mergeGlobal (left right : HostGlobalEntry) : Option HostGlobalEntry := do
  guard (left.name == right.name)
  guard (!(left.undeclared || right.undeclared) ||
    !(left.typeTag.isSome || right.typeTag.isSome || left.identity.isSome || right.identity.isSome ||
      left.opaqueRef || right.opaqueRef || left.recordedValue || right.recordedValue ||
      left.worldCall || right.worldCall))
  guard (!(left.opaqueRef || right.opaqueRef) ||
    !(left.identity.isSome || right.identity.isSome ||
      (left.typeTag.isSome && left.typeTag != some "undefined") ||
      (right.typeTag.isSome && right.typeTag != some "undefined")))
  let typeTag ← mergeField left.typeTag right.typeTag
  let identity ← mergeField left.identity right.identity
  let premise := mergePremise left.premise right.premise
  pure ⟨left.name, typeTag, identity, left.opaqueRef || right.opaqueRef,
    left.recordedValue || right.recordedValue, left.undeclared || right.undeclared,
    left.worldCall || right.worldCall, premise⟩

private def mergeMember (left right : HostMemberEntry) : Option HostMemberEntry := do
  guard (left.owner == right.owner && left.key == right.key)
  let identity ← mergeField left.identity right.identity
  let primitive ← mergeField left.primitive right.primitive
  let dataValue ← mergeField left.dataValue right.dataValue
  let worldCall := left.worldCall || right.worldCall
  guard (!(primitive.isSome && worldCall))
  guard (dataValue.isNone || (identity.isNone && !worldCall && primitive.isNone))
  pure ⟨left.owner, left.key, identity, worldCall, primitive, dataValue, mergePremise left.premise right.premise⟩

private def mergeGlobalEntries (layers : List HostLayer) : Option (List HostGlobalEntry) := Id.run do
  let mut entries : List HostGlobalEntry := []
  for entry in layers.flatMap (·.globals) do
    if let some prior := entries.find? (·.name == entry.name) then
      if let some merged := mergeGlobal prior entry then
        entries := entries.map fun old => if old.name == entry.name then merged else old
      else
        return none
    else
      entries := entries ++ [entry]
  return some entries

private def mergeMemberEntries (layers : List HostLayer) : Option (List HostMemberEntry) := Id.run do
  let mut entries : List HostMemberEntry := []
  for entry in layers.flatMap (·.members) do
    if let some prior := entries.find? fun old => old.owner == entry.owner && old.key == entry.key then
      if let some merged := mergeMember prior entry then
        entries := entries.map fun old =>
          if old.owner == entry.owner && old.key == entry.key then merged else old
      else
        return none
    else
      entries := entries ++ [entry]
  return some entries

/-- Build the derived lookup tables once after composing the authored layers. -/
def fromLayers (name : String) (layers : List HostLayer) : HostProfile :=
  ⟨name, layers, (mergeGlobalEntries layers).getD [], (mergeMemberEntries layers).getD []⟩

def withLayers (profile : HostProfile) (layers : List HostLayer) : HostProfile :=
  fromLayers profile.name layers

def globalEntry? (profile : HostProfile) (name : String) : Option HostGlobalEntry := Id.run do
  return profile.resolvedGlobals.find? (·.name == name)

def memberEntry? (profile : HostProfile) (owner key : String) : Option HostMemberEntry := Id.run do
  return profile.resolvedMembers.find? fun entry => entry.owner == owner && entry.key == key

def valid (profile : HostProfile) : Bool := Id.run do
  unless profile.layers.all HostLayer.validPremises do return false
  return mergeGlobalEntries profile.layers == some profile.resolvedGlobals &&
    mergeMemberEntries profile.layers == some profile.resolvedMembers

def premises (profile : HostProfile) : List String := Id.run do
  let mut result : List String := []
  for layer in profile.layers do
    for entry in layer.opaqueConstructors do
      if let some premise := entry.premise then result := result ++ [premise]
    for entry in layer.capabilities do
      if let some premise := entry.premise then result := result ++ [premise]
  return result.eraseDups

private def stripPrefix? (receiver pref : String) : Option String :=
  (receiver.dropPrefix? pref).map ToString.toString

private def ownerName (receiver : String) : String :=
  ((stripPrefix? receiver "window.").orElse fun _ =>
    (stripPrefix? receiver "intrinsic.").orElse fun _ => stripPrefix? receiver "node.").getD receiver

private def bindingPremises (profile : HostProfile) (name : String) : List String :=
  ((profile.globalEntry? name).bind (·.premise)).toList

def premisesForRef (profile : HostProfile) : HostRef → List String
  | .binding name => bindingPremises profile name
  | .property "window" name => bindingPremises profile name
  | .property receiver key =>
    ((profile.memberEntry? (ownerName receiver) key).bind (·.premise)).toList

def premiseForOperation (profile : HostProfile) (name : String) : Option String := Id.run do
  if let some entry := profile.globalEntry? name then return entry.premise
  for entry in profile.layers.flatMap (·.members) do
    if s!"{entry.owner}.{entry.key}" == name then return entry.premise
  return none

def empty : HostProfile := fromLayers "empty" []
def ecmascript : HostProfile := fromLayers "ecmascript" [ECMAScriptHost.layer]
def browserPage : HostProfile := fromLayers "browser-page" BrowserPageHost.layers
def node : HostProfile := fromLayers "node" NodeHost.layers
def nodeRecording : HostProfile := fromLayers "node-recording" RecordedNodeHost.layers

def isEmpty (profile : HostProfile) : Bool := profile.layers.isEmpty

/-- Fresh Symbol calls and well-known symbols use the shared ECMAScript layer. -/
def ambientSymbols (profile : HostProfile) : Bool := profile.hasCapability .ambientSymbols

/-- Recorded values are supplied by the world. This field asserts no property of its answer. -/
def recordedHostValue (profile : HostProfile) (name : String) : Bool :=
  (profile.globalEntry? name).any (·.recordedValue)

def undeclaredGlobal (profile : HostProfile) (name : String) : Bool :=
  (profile.globalEntry? name).any (·.undeclared) ||
    (profile.hasCapability .undeclaredNames && (profile.globalEntry? name).isNone)

def recordedPrim (profile : HostProfile) (owner key : String) : Option Prim := do
  let primitive ← (profile.memberEntry? owner key).bind (·.primitive)
  if primitive == .log || profile.hasCapability .recordedModelPrimitives then some primitive else none

def aliases := ["window", "globalThis", "self"]

def bindingType (profile : HostProfile) (name : String) : Option String :=
  match profile.globalEntry? name with
  | some entry => entry.typeTag <|> if entry.undeclared then some "undefined" else none
  | none => if profile.hasCapability .undeclaredNames then some "undefined" else none

def opaqueBinding (profile : HostProfile) (name : String) : Bool :=
  (profile.globalEntry? name).any fun entry => entry.opaqueRef && entry.identity.isNone

/-- Standard globals keep their shared intrinsic identity in every profile.
Page-only globals already carry their explicit `window.*` identities. -/
private def presentedIdentity (_profile : HostProfile) (identity : String) : String := identity

def bindingIdentity (profile : HostProfile) (name : String) : Option String :=
  match profile.globalEntry? name with
  | some entry => if entry.recordedValue then none else entry.identity.map profile.presentedIdentity
  | none => none

def memberValue? (profile : HostProfile) (owner key : String) : Option HostValue := do
  let entry ← profile.memberEntry? owner key
  entry.dataValue.orElse fun _ => entry.identity.map HostValue.identity

def valueForRef? (profile : HostProfile) : HostRef → Option HostValue
  | .binding name | .property "window" name => do
    let entry ← profile.globalEntry? name
    if entry.recordedValue then none
    else HostValue.identity <$> (entry.identity.map profile.presentedIdentity)
  | .property receiver key => do
    match ← profile.memberValue? (ownerName receiver) key with
    | .identity name => some (.identity (profile.presentedIdentity name))
    | value => some value

def identity (profile : HostProfile) : HostRef → Option String
  | ref => do
    let .identity name ← profile.valueForRef? ref | none
    return profile.presentedIdentity name

/-- An allowed opaque constructor can be retained in deferred code. A reached lookup ends
the modeled execution before argument evaluation, even inside a catch clause. -/
def opaqueConstructor (profile : HostProfile) (name : String) : Bool :=
  profile.layers.any fun layer => layer.opaqueConstructors.any (·.name == name) ||
    (profile.hasCapability .opaqueStandardConstructors && ECMAScriptHost.opaqueConstructorNames.contains name)

private def optionalJson (j : Lean.Json) (key : String) : Except String (Option Lean.Json) :=
  match j.getObjVal? key with
  | .ok value => pure (some value)
  | .error _ => pure none

private def optionalString (j : Lean.Json) (key : String) : Except String (Option String) := do
  match ← optionalJson j key with
  | none => pure none
  | some value => some <$> value.getStr?

private def optionalBool (j : Lean.Json) (key : String) : Except String Bool := do
  match ← optionalJson j key with
  | none => pure false
  | some value => value.getBool?

private def arrayField (j : Lean.Json) (key : String) : Except String (List Lean.Json) := do
  match ← optionalJson j key with
  | none => pure []
  | some value => return (← value.getArr?).toList

private def parseGlobal (j : Lean.Json) : Except String HostGlobalEntry := do
  let name ← j.getObjValAs? String "name"
  let typeTag ← optionalString j "typeof"
  let identity ← optionalString j "identity"
  let opaqueRef ← optionalBool j "opaque"
  let recordedValue ← optionalBool j "recordedValue"
  let undeclared ← optionalBool j "undeclared"
  let worldCall ← optionalBool j "worldCall"
  let premise ← optionalString j "premise"
  pure { name, typeTag, identity, opaqueRef, recordedValue, undeclared, worldCall, premise }

private def parsePrimitive : String → Except String Prim
  | "log" => pure .log
  | "create" => pure .create
  | "defineProperty" => pure .defineProperty
  | "getPrototypeOf" => pure .getPrototypeOf
  | "setPrototypeOf" => pure .setPrototypeOf
  | name => throw s!"unsupported host primitive {name}"

private def parseHostValue (j : Lean.Json) : Except String HostValue := do
  let kind ← j.getObjValAs? String "kind"
  match kind with
  | "identity" => return .identity (← j.getObjValAs? String "name")
  | "number" =>
    let bits ← j.getObjValAs? String "bits"
    let some value := bits.toNat? | throw "host number bits must be a decimal string"
    let value := UInt64.ofNat value
    unless value.toNat == bits.toNat?.getD 0 do throw "host number bits exceed UInt64"
    return .number value
  | name => throw s!"unsupported host data value {name}"

private def parseMember (j : Lean.Json) : Except String HostMemberEntry := do
  let owner ← j.getObjValAs? String "owner"
  let key ← j.getObjValAs? String "key"
  let identity ← optionalString j "identity"
  let worldCall ← optionalBool j "worldCall"
  let primitive ← match ← optionalString j "primitive" with
    | none => pure none
    | some name => some <$> parsePrimitive name
  let dataValue ← match ← optionalJson j "dataValue" with
    | none => pure none
    | some value => some <$> parseHostValue value
  let premise ← optionalString j "premise"
  pure { owner, key, identity, worldCall, primitive, dataValue, premise }

private def parseCapability : String → Except String HostCapability
  | "ambientSymbols" => pure .ambientSymbols
  | "arrayFromTemplate" => pure .arrayFromTemplate
  | "opaqueStandardConstructors" => pure .opaqueStandardConstructors
  | "pageEnvironment" => pure .pageEnvironment
  | "recordedModelPrimitives" => pure .recordedModelPrimitives
  | "recordedStringConversion" => pure .recordedStringConversion
  | "undeclaredNames" => pure .undeclaredNames
  | name => throw s!"unsupported host capability {name}"

private def parseCapabilityEntry (j : Lean.Json) : Except String HostCapabilityEntry := do
  let name ← j.getObjValAs? String "capability"
  let capability ← parseCapability name
  let premise ← optionalString j "premise"
  pure { capability, premise }

private def parseConstructor (j : Lean.Json) : Except String HostConstructorEntry := do
  let name ← j.getObjValAs? String "name"
  let premise ← optionalString j "premise"
  pure { name, premise }

private def parseLayer (j : Lean.Json) : Except String HostLayer := do
  let name ← j.getObjValAs? String "name"
  let globals ← (← arrayField j "globals").mapM parseGlobal
  let members ← (← arrayField j "members").mapM parseMember
  let opaqueConstructors ← (← arrayField j "opaqueConstructors").mapM parseConstructor
  let capabilities ← (← arrayField j "capabilities").mapM parseCapabilityEntry
  pure { name, globals, members, opaqueConstructors, capabilities }

def read (j : Lean.Json) : Except String HostProfile := do
  let name ← j.getObjValAs? String "profile"
  let profile := match name with
    | "empty" => empty
    | "browser-page" => browserPage
    | "ecmascript" => ecmascript
    | "node" => node
    | "node-recording" => nodeRecording
    | _ => empty
  if profile.name == "empty" && name != "empty" then
    throw s!"unsupported host profile {name}"
  let extensions ← (← arrayField j "extensions").mapM parseLayer
  let profile := profile.withLayers (profile.layers ++ extensions)
  unless profile.valid do throw "host profile contains an entry without a premise or conflicting entries"
  return profile

end HostProfile

/-- In any host state, this read returns exactly the indicated result and leaves
the state intact. Identity and Number-bits results are distinct constructors. -/
abbrev World.StableRead (w : World) (ref : HostRef) (value : HostValue) : Prop :=
  ∀ s, w.hostRef ref s = some (value, s)

/-- The observations used by a certificate, independent of the selected decoding profile. -/
structure HostPremises where
  typeofBindings : List (String × String) := []
  refs : List (HostRef × HostValue) := []
  profileFacts : List String := []
  deriving DecidableEq, Repr

namespace HostPremises

def assumptions (p : HostPremises) : List String :=
  p.profileFacts ++
  (p.typeofBindings.map fun (name, value) =>
    s!"typeof {name} is {value} without observable effects throughout initialization") ++
  (p.refs.map fun (ref, value) =>
    let read := match ref with
      | .binding name => name
      | .property receiver key => receiver ++ "." ++ key
    let result := match value with
      | .number bits => s!"the Number with binary64 bits {bits.toNat}"
      | .identity identity =>
        if ref == HostRef.property "Symbol" "iterator" && identity == "Symbol.iterator" then
          "the well-known iterator symbol"
        else if ref == HostRef.property "Symbol" "asyncIterator" && identity == "Symbol.asyncIterator" then
          "the well-known asyncIterator symbol"
        else if ref == HostRef.property "Symbol" "hasInstance" && identity == "Symbol.hasInstance" then
          "the well-known hasInstance symbol"
        else if ref == HostRef.property "Symbol" "toStringTag" && identity == "Symbol.toStringTag" then
          "the well-known toStringTag symbol"
        else if identity == "intrinsic.Array" then "the intrinsic Array constructor"
        else if identity == "intrinsic.Array.from" then "the intrinsic Array.from function"
        else if identity == "intrinsic.Symbol" then "the intrinsic Symbol function"
        else if identity == "window" then "the same page object" else s!"the stable host reference {identity}"
    s!"{read} returns {result} without observable effects throughout initialization").eraseDups

/-- This world selects candidate premises. The certificate independently checks execution
for every world satisfying just the observations made by the two initializers. -/
def observations (profile : HostProfile) : World where
  σ := HostPremises
  -- Capabilities and opaque-constructor allowances select profile-wide lowering
  -- rules. Global and member facts are added only by the observations that use
  -- their entries, avoiding both unused premises and a large proof-state list.
  init := { profileFacts := profile.premises }
  step := fun name this args st =>
    let st := match profile.premiseForOperation name with
      | some premise => { st with profileFacts := st.profileFacts.insert premise }
      | none => st
    ((World.probe.step name this args ()).1, st)
  talk := fun request st => ((World.probe.talk request ()).1, st)
  globalTypeof := fun name st => do
    let value ← profile.bindingType name
    let facts := (profile.globalEntry? name).bind (·.premise) <|>
      if profile.undeclaredGlobal name then HostProfile.capabilityPremise? profile .undeclaredNames else none
    let profileFacts := match facts with
      | some premise => st.profileFacts.insert premise
      | none => st.profileFacts
    return (.ret (.str value), { st with typeofBindings := st.typeofBindings.insert (name, value), profileFacts })
  hostRef := fun ref st => do
    let value ← profile.valueForRef? ref
    let profileFacts := (profile.premisesForRef ref).foldl
      (fun facts premise => facts.insert premise) st.profileFacts
    return (value, { st with refs := st.refs.insert (ref, value), profileFacts })

/-- Each used observation returns the specified result and preserves every host state. -/
def Satisfied (p : HostPremises) (w : World) : Prop :=
  (∀ name value, p.typeofBindings.lookup name = some value →
    ∀ s, w.globalTypeof name s = some (.ret (.str value), s)) ∧
  (∀ ref value, p.refs.lookup ref = some value → w.StableRead ref value)

def specialize (p : HostPremises) (w : World) : World :=
  { w with
    globalTypeof := fun name s =>
      match p.typeofBindings.lookup name with
      | some value => some (.ret (.str value), s)
      | none => w.globalTypeof name s
    hostRef := fun ref s =>
      match p.refs.lookup ref with
      | some value => some (value, s)
      | none => w.hostRef ref s }

theorem specialize_eq (p : HostPremises) (w : World) (h : p.Satisfied w) : p.specialize w = w := by
  have typeObs : (p.specialize w).globalTypeof = w.globalTypeof := by
    funext name s
    cases he : p.typeofBindings.lookup name with
    | none => simp [specialize, he]
    | some value => simpa [specialize, he] using (h.1 name value he s).symm
  have refObs : (p.specialize w).hostRef = w.hostRef := by
    funext ref s
    cases he : p.refs.lookup ref with
    | none => simp [specialize, he]
    | some identity => simpa [specialize, he] using (h.2 ref identity he s).symm
  cases w with
  | mk σ init step observe read talk =>
    exact congr (congrArg (fun f g => World.mk σ init step f g talk) typeObs) refObs

end HostPremises
end CoreJS
