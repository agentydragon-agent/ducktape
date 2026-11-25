import EsmSplit.CoreJS.Value

/-! Materialize the symbolic realm layout. Hosts supply all additional global and intrinsic properties. -/
namespace CoreJS.Realm

/-- Standard properties only; host-defined Error properties and toString behavior are not modeled. -/
def errorPrototype : Obj :=
  { proto := some objectProto, props := [
    ("constructor", .data (.obj errorConstructor) true false true),
    ("name", .data (.str "Error") true false true),
    ("message", .data (.str "") true false true),
    ("toString", .data (.host "Error.prototype.toString") true false true)] }

def errorConstructorObject : Obj :=
  { proto := some functionProto, code := some (.host "%Error%"), props := [
    ("length", .data (.num 1) false false true),
    ("name", .data (.str "Error") false false true),
    ("prototype", .data (.obj errorProto) false false false)] }

def object : RealmId → Obj
  | .globalObject => { proto := none, props := [] }
  | .intrinsic .errorPrototype => errorPrototype
  | .intrinsic .errorConstructor => errorConstructorObject

def heap : Array Obj := builtins ++ (realmIds.map object).toArray

#guard builtins.size == arrayIteratorProto.index + 1
#guard realmIds.eraseDups.length == realmIds.length
#guard ECMAScriptHost.realmGlobalBindings.all (fun (_, id) => ECMAScriptHost.realmIntrinsics.contains id)
#guard errorProto != errorConstructor && errorProto != globalObject && errorConstructor != globalObject

end CoreJS.Realm
