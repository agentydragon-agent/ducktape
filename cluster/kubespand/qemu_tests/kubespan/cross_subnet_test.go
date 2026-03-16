package kubespan_test

import "testing"

func TestCrossSubnet(t *testing.T) {
	t.Parallel()
	runTopology(t, "cross_subnet")
}
