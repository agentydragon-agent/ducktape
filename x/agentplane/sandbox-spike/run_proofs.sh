#!/usr/bin/env bash
set -euo pipefail

SPIKE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SPIKE_NAMESPACE=agentplane-sandbox-spike
SPIKE_PROXY_URL=http://127.0.0.1:8081
SPIKE_VERIFIER_URL=http://verifier.agentplane-sandbox-spike.svc.cluster.local:8080

cleanup() {
  kubectl delete -k "$SPIKE_ROOT" --ignore-not-found --wait=false >/dev/null
  kubectl wait --for=delete namespace/$SPIKE_NAMESPACE --timeout=180s >/dev/null || true
}
trap cleanup EXIT

if kubectl get namespace "$SPIKE_NAMESPACE" >/dev/null 2>&1; then
  echo "$SPIKE_NAMESPACE already exists; refusing to reuse an unknown experiment" >&2
  exit 1
fi

run_runner() {
  local sandbox=$1
  shift
  kubectl -n "$SPIKE_NAMESPACE" exec "$sandbox" -c runner -- python /app/runner.py "$@"
}

wait_for_restart() {
  local sandbox=$1
  local container=$2
  local attempt
  local restarts
  for attempt in {1..30}; do
    restarts=$(
      kubectl -n "$SPIKE_NAMESPACE" get pod "$sandbox" \
        -o "jsonpath={.status.containerStatuses[?(@.name==\"$container\")].restartCount}"
    )
    if [[ $restarts -ge 1 ]]; then
      kubectl -n "$SPIKE_NAMESPACE" wait --for=condition=Ready "pod/$sandbox" --timeout=120s \
        >/dev/null
      printf '%s_restart_count=%s\n' "$container" "$restarts"
      return
    fi
    sleep 2
  done
  echo "$container did not restart" >&2
  exit 1
}

kubectl apply -k "$SPIKE_ROOT" >/dev/null
kubectl -n "$SPIKE_NAMESPACE" wait --for=condition=Available deployment/verifier --timeout=180s \
  >/dev/null
kubectl -n "$SPIKE_NAMESPACE" wait --for=condition=Ready \
  sandbox/sandbox-a sandbox/sandbox-b --timeout=240s >/dev/null

SPIKE_INSPECTION=$(run_runner sandbox-a inspect)
printf '%s\n' "$SPIKE_INSPECTION"
jq -e '
  .credential_env_present == false and
  .credential_mount_present == false and
  .projected_identity_mount_present == false and
  .service_account_mount_present == false and
  .proxy_process_visible == false and
  .proxy_root_mount_visible == false
' <<<"$SPIKE_INSPECTION" >/dev/null

kubectl -n "$SPIKE_NAMESPACE" get pod sandbox-a -o json | jq -e '
  .spec.automountServiceAccountToken == false and
  .spec.shareProcessNamespace != true and
  ([.spec.containers[] | select(.name == "runner") | .volumeMounts[].name] | sort) ==
    ["runner-code", "runner-tmp"] and
  ([.spec.containers[] | select(.name == "proxy") | .volumeMounts[].name] | sort) ==
    ["proxy-code", "proxy-tmp", "upstream-credential", "workload-identity"]
' >/dev/null
test "$(kubectl auth can-i --as \
  system:serviceaccount:$SPIKE_NAMESPACE:sandbox-proxy get pods -n "$SPIKE_NAMESPACE")" = no
echo "runner_secret_and_kubernetes_authority=absent"

SPIKE_A=$(run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000001001 200)
SPIKE_B=$(run_runner sandbox-b operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000001002 200)
printf '%s\n%s\n' "$SPIKE_A" "$SPIKE_B"
test "$(jq -r '.body.pod_uid' <<<"$SPIKE_A")" != "$(jq -r '.body.pod_uid' <<<"$SPIKE_B")"
test "$(jq -r '.body.sandbox_uid' <<<"$SPIKE_A")" != \
  "$(jq -r '.body.sandbox_uid' <<<"$SPIKE_B")"

run_runner sandbox-a connect verifier.agentplane-sandbox-spike.svc.cluster.local 8080 connected
run_runner sandbox-a direct "$SPIKE_VERIFIER_URL" \
  00000000000000000000000000001003 401
run_runner sandbox-a forge "$SPIKE_VERIFIER_URL" \
  00000000000000000000000000001004 401
run_runner sandbox-a arbitrary "$SPIKE_PROXY_URL" \
  00000000000000000000000000001005 400
run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000001006 200
run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000001006 409
run_runner sandbox-a connect 1.1.1.1 80 blocked
run_runner sandbox-a connect kubernetes.default.svc.cluster.local 443 blocked

SPIKE_CROSS_COPY=$(
  kubectl -n "$SPIKE_NAMESPACE" exec sandbox-a -c proxy -- \
    python -c 'from pathlib import Path; print(Path("/var/run/spike-identity/token").read_text(), end="")' \
    | kubectl -n "$SPIKE_NAMESPACE" exec -i sandbox-b -c proxy -- \
      python /app/proxy.py present-token
)
printf '%s\n' "$SPIKE_CROSS_COPY"
jq -e '.status == 403 and .body.error == "source_pod_mismatch"' \
  <<<"$SPIKE_CROSS_COPY" >/dev/null

run_runner sandbox-a crash-proxy "$SPIKE_PROXY_URL"
wait_for_restart sandbox-a proxy
run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000001007 200
test "$(kubectl -n "$SPIKE_NAMESPACE" logs sandbox-a -c proxy --previous | wc -c)" -eq 0

run_runner sandbox-a request-restart /tmp/restart-requested || true
wait_for_restart sandbox-a runner
run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000001008 200
test "$(kubectl -n "$SPIKE_NAMESPACE" logs sandbox-a -c runner --previous | wc -c)" -eq 0
echo "credential_material_in_previous_container_logs=absent"

kubectl -n "$SPIKE_NAMESPACE" patch secret synthetic-upstream-credential --type=merge \
  -p '{"stringData":{"value":"agentplane-spike-obviously-fake-v2","version":"v2"}}' \
  >/dev/null
for SPIKE_ATTEMPT in {1..50}; do
  SPIKE_REQUEST_ID=$(printf '%032x' "$((2000 + SPIKE_ATTEMPT))")
  if SPIKE_ROTATION=$(run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
    "$SPIKE_REQUEST_ID" 200 2>/dev/null); then
    if [[ $(jq -r '.body.credential_version' <<<"$SPIKE_ROTATION") == v2 ]]; then
      printf '%s\nrotation_observed_after_attempt=%s\n' "$SPIKE_ROTATION" "$SPIKE_ATTEMPT"
      break
    fi
  fi
  if [[ $SPIKE_ATTEMPT -eq 50 ]]; then
    echo "Secret projection did not converge to v2" >&2
    exit 1
  fi
  sleep 3
done

SPIKE_OLD_TOKEN=$(
  kubectl -n "$SPIKE_NAMESPACE" exec sandbox-a -c proxy -- \
    python -c 'from pathlib import Path; print(Path("/var/run/spike-identity/token").read_text(), end="")'
)
SPIKE_OLD_POD_UID=$(kubectl -n "$SPIKE_NAMESPACE" get pod sandbox-a -o jsonpath='{.metadata.uid}')
SPIKE_SANDBOX_UID=$(kubectl -n "$SPIKE_NAMESPACE" get sandbox sandbox-a \
  -o jsonpath='{.metadata.uid}')
kubectl -n "$SPIKE_NAMESPACE" patch sandbox sandbox-a --type=merge \
  -p '{"spec":{"operatingMode":"Suspended"}}' >/dev/null
kubectl -n "$SPIKE_NAMESPACE" wait --for=delete pod/sandbox-a --timeout=180s >/dev/null
kubectl -n "$SPIKE_NAMESPACE" wait --for=condition=Suspended sandbox/sandbox-a --timeout=120s \
  >/dev/null
kubectl -n "$SPIKE_NAMESPACE" patch sandbox sandbox-a --type=merge \
  -p '{"spec":{"operatingMode":"Running"}}' >/dev/null
kubectl -n "$SPIKE_NAMESPACE" wait --for=condition=Ready sandbox/sandbox-a --timeout=240s \
  >/dev/null
SPIKE_NEW_POD_UID=$(kubectl -n "$SPIKE_NAMESPACE" get pod sandbox-a -o jsonpath='{.metadata.uid}')
SPIKE_NEW_SANDBOX_UID=$(kubectl -n "$SPIKE_NAMESPACE" get sandbox sandbox-a \
  -o jsonpath='{.metadata.uid}')
printf 'pod_uid: %s -> %s\nsandbox_uid: %s -> %s\n' \
  "$SPIKE_OLD_POD_UID" "$SPIKE_NEW_POD_UID" "$SPIKE_SANDBOX_UID" "$SPIKE_NEW_SANDBOX_UID"
test "$SPIKE_OLD_POD_UID" != "$SPIKE_NEW_POD_UID"
test "$SPIKE_SANDBOX_UID" = "$SPIKE_NEW_SANDBOX_UID"
SPIKE_STALE=$(
  printf '%s' "$SPIKE_OLD_TOKEN" \
    | kubectl -n "$SPIKE_NAMESPACE" exec -i sandbox-a -c proxy -- \
      python /app/proxy.py present-token
)
unset SPIKE_OLD_TOKEN
printf '%s\n' "$SPIKE_STALE"
jq -e '.status == 401 and .body.error == "workload_token_rejected"' \
  <<<"$SPIKE_STALE" >/dev/null
run_runner sandbox-a operate "$SPIKE_PROXY_URL" \
  00000000000000000000000000003001 200

echo "all_proofs=passed"
