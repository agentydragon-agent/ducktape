package kubeapiproxy

import (
	"k8s.io/apimachinery/pkg/util/sets"
	apirequest "k8s.io/apiserver/pkg/endpoints/request"
)

type (
	RequestInfo         = apirequest.RequestInfo
	RequestInfoResolver = apirequest.RequestInfoResolver
)

func newRequestInfoResolver() RequestInfoResolver {
	return &apirequest.RequestInfoFactory{
		APIPrefixes:          sets.NewString("api", "apis"),
		GrouplessAPIPrefixes: sets.NewString("api"),
	}
}
