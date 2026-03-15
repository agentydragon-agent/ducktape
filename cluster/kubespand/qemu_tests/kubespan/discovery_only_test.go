package kubespan_test

import "testing"

func TestDiscoveryOnly(t *testing.T) {
	t.Parallel()
	runTopology(t, "discovery_only")
}
