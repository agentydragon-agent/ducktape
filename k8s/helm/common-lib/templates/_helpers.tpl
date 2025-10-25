{{/*
Common Helm helper templates for Ducktape workloads.
*/}}

{{/* Return the chart name */}}
{{- define "common.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Generate a fully-qualified release name */}}
{{- define "common.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "common.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Common chart label */}}
{{- define "common.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{/* Standard labels applied to most resources */}}
{{- define "common.labels" -}}
helm.sh/chart: {{ include "common.chart" . }}
app.kubernetes.io/name: {{ include "common.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- end -}}

{{/* Labels with additional key/value pairs */}}
{{- define "common.labelsWith" -}}
{{- $context := index . "context" -}}
{{- $extra := index . "extra" | default (dict) -}}
{{ include "common.labels" $context }}
{{- range $k, $v := $extra }}
{{ $k }}: {{ $v }}
{{- end }}
{{- end -}}

{{/* Pod selector labels */}}
{{- define "common.selectorLabels" -}}
app.kubernetes.io/name: {{ include "common.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Selector labels with additional key/value pairs */}}
{{- define "common.selectorLabelsWith" -}}
{{- $context := index . "context" -}}
{{- $extra := index . "extra" | default (dict) -}}
{{ include "common.selectorLabels" $context }}
{{- range $k, $v := $extra }}
{{ $k }}: {{ $v }}
{{- end }}
{{- end -}}

{{/* Build component/app label map for a context */}}
{{- define "common.componentLabelMap" -}}
{{- $ctx := index . "context" -}}
{{- $component := index . "component" -}}
{{- $addApp := index . "addAppLabel" | default true -}}
{{- $extra := dict -}}
{{- if $component }}{{- $_ := set $extra "app.kubernetes.io/component" $component }}{{- end }}
{{- if $addApp }}{{- $_ := set $extra "app" (include "common.name" $ctx) }}{{- end }}
{{- range $k, $v := index . "extra" | default (dict) }}{{- $_ := set $extra $k $v }}{{- end }}
{{ toYaml $extra }}
{{- end -}}

{{/* Labels including component/app info */}}
{{- define "common.componentLabels" -}}
{{- $ctx := index . "context" -}}
{{- $extra := include "common.componentLabelMap" . | fromYaml -}}
{{ include "common.labelsWith" (dict "context" $ctx "extra" $extra) }}
{{- end -}}

{{/* Selector labels including component/app info */}}
{{- define "common.componentSelectorLabels" -}}
{{- $ctx := index . "context" -}}
{{- $extra := include "common.componentLabelMap" . | fromYaml -}}
{{ include "common.selectorLabelsWith" (dict "context" $ctx "extra" $extra) }}
{{- end -}}

{{/* Blueprint auto-instantiate label helper for Authentik */}}
{{- define "common.blueprintLabels" -}}
blueprints.goauthentik.io/instantiate: "true"
{{- end -}}

{{/* Compute service account name given optional override */}}
{{- define "common.serviceAccountName" -}}
{{- $values := index . "values" -}}
{{- $create := default true (index $values "create") -}}
{{- $override := index $values "name" -}}
{{- $default := index . "default" -}}
{{- if $override }}{{ $override }}{{ else }}{{ ternary $default "default" $create }}{{ end }}
{{- end -}}

{{/* Optionally render a Docker registry secret from chart values */}}
{{- define "common.dockerRegistrySecret" -}}
{{- $root := . -}}
{{- with $root.Values.imagePullSecrets }}
{{- if .create }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ .name }}
  namespace: {{ $root.Release.Namespace }}
  labels:
{{ include "common.labels" $root | indent 4 }}
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
    {{- $username := default "" .username -}}
    {{- $password := default "" .password -}}
    {{- $auth := printf "%s:%s" $username $password | b64enc -}}
    {{- $config := dict "auths" (dict .registry (dict "username" $username "password" $password "auth" $auth)) -}}
    {{ $config | toJson }}
{{- end }}
{{- end }}
{{- end -}}

{{/* Emit imagePullSecrets stanza for a workload if configured */}}
{{- define "common.renderImagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
{{- if .name }}
imagePullSecrets:
  - name: {{ .name }}
{{- end }}
{{- end }}
{{- end -}}
