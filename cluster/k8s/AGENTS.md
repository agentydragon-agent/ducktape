# k8s manifests — agent notes

## Network troubleshooting: always check CiliumNetworkPolicies

When pods in this namespace can't talk to each other (memberlist won't form,
gRPC clients timeout, intra-app probes fail, "empty ring" / "no schedulers"
type errors), check for CiliumNetworkPolicies **before** suspecting the CNI
datapath:

```bash
kubectl get cnp -n <ns>
kubectl get ccnp
```

A CNP scoped to the app may whitelist only external consumers and miss
intra-app paths (e.g. a SingleBinary policy that doesn't permit the
gossip/gRPC ports needed in a SimpleScalable layout). Symptom looks like a
broken overlay (ping/TCP timeouts to specific pods), but generic cross-node
traffic and unrelated pods on the same nodes are fine. Fix is to add the
missing intra-app `fromEndpoints` selector covering all ports the
distributed deployment requires.
