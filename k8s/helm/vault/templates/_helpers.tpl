{{/*
Helper templates for the Vault chart wrapper.
*/}}

{{- define "vault-ducktape.labels" -}}
{{ include "common.labels" . }}
app.kubernetes.io/component: vault
{{- end -}}

{{- define "vault-ducktape.selectorLabels" -}}
app.kubernetes.io/name: {{ include "common.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: vault
{{- end -}}

{{- define "vault-ducktape.serviceAccountName" -}}
{{ printf "%s-controller" (include "common.fullname" .) }}
{{- end -}}

{{- define "vault-ducktape.namespace" -}}
{{- if and .Values.namespace .Values.namespace.create -}}
{{- .Values.namespace.name -}}
{{- else -}}
{{- ((.Values.namespace).name | default .Release.Namespace) -}}
{{- end -}}
{{- end -}}
