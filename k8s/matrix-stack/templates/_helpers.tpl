{{- define "matrix-stack.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "matrix-stack.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "matrix-stack.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

