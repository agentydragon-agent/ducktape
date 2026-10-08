### Kubernetes admin Actions for operations outside your own RBAC

Agentplane Actions has a `kubernetes_admin` group for Kubernetes operations performed under
linked operator authority. It is **not** an alternate ServiceAccount or permission granted by
access to the API. For a user-authorized probe or diagnosis, first check the exact verb,
resource/subresource, name and namespace with `kubectl auth can-i`. Use your own standing
kubectl access when it safely suffices. If it does not, discover the relevant operation with
`GET /v1/action-groups` on the Actions Service (described in the shared platform instructions),
and its arguments with
`GET /v1/action-groups/kubernetes_admin/actions/{action}`. Examples include `pods_exec`,
`pods_log`, and `resources_get`; choose the narrowest operation and arguments. For a database
migration check, a read-only `pods_exec` query in the named database Pod is preferable to a
broad administrative mutation. Do not read or print secrets as a diagnostic shortcut.

Inspect your `/v1/action-policy` bindings and `auto_approve_if` for the *exact* action and
arguments before submitting. A Kubernetes admin Action may require manual operator approval;
never assume its presence in the catalog means it is auto-approved. If approval is needed,
explain why your own RBAC cannot perform the operation, submit a narrowly scoped request,
and wait for the decision and execution result via the Actions API/notifications as described
in the shared platform instructions. Never impersonate an operator, bypass the egress proxy,
or use admin Actions for unrelated work. Approval is not execution success.
