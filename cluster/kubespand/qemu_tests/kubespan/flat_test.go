package kubespan_test

import "testing"

func TestFlat(t *testing.T) {
	t.Parallel()
	runTopology(t, "flat")
}
