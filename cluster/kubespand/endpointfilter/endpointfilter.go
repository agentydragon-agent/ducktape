// Package endpointfilter provides CIDR-based allow/deny filtering for KubeSpan endpoints.
//
// Used by both the discovery controller (to filter self-announced endpoints before
// publishing) and the PeerSpec controller (imported via the peerspec embed).
package endpointfilter

import (
	"net/netip"
	"slices"
	"strings"
)

// Filter is a parsed CIDR filter with allow/deny semantics.
type Filter struct {
	prefix netip.Prefix
	deny   bool
}

// Parse parses endpoint filter strings ("!cidr" for deny, "cidr" for allow).
func Parse(raw []string) []Filter {
	var filters []Filter
	for _, s := range raw {
		deny := false
		cidr := s
		if strings.HasPrefix(s, "!") {
			deny = true
			cidr = s[1:]
		}
		prefix, err := netip.ParsePrefix(cidr)
		if err != nil {
			continue
		}
		filters = append(filters, Filter{prefix: prefix, deny: deny})
	}
	return filters
}

// Apply returns only the endpoints allowed by the filter list.
// When no filters are configured, all endpoints are returned (matching upstream behavior).
func Apply(endpoints []netip.AddrPort, filters []Filter) []netip.AddrPort {
	if len(filters) == 0 {
		return slices.Clone(endpoints)
	}
	var result []netip.AddrPort
	for _, ep := range endpoints {
		if allowed(ep, filters) {
			result = append(result, ep)
		}
	}
	return result
}

// allowed checks if an endpoint is allowed by the filter list.
// First match wins. Empty filters = allow all.
func allowed(ep netip.AddrPort, filters []Filter) bool {
	if len(filters) == 0 {
		return true
	}
	for _, f := range filters {
		if f.prefix.Contains(ep.Addr()) {
			return !f.deny
		}
	}
	return false
}
