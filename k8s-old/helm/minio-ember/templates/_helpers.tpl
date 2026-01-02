{{/*
Helper templates for the minio-ember chart.
*/}}

{{- define "minio-ember.fullname" -}}
{{- include "common.fullname" . -}}
{{- end -}}

{{- define "minio-ember.labels" -}}
{{- include "common.labels" . -}}
{{- end -}}

{{- define "minio-ember.selectorLabels" -}}
{{- include "common.selectorLabels" . -}}
{{- end -}}

{{- define "minio-ember.serviceAccountName" -}}
{{- printf "%s-sa" (include "minio-ember.fullname" .) -}}
{{- end -}}

{{- define "minio-ember.bucketJobName" -}}
{{- printf "%s-bucket-job" (include "minio-ember.fullname" .) -}}
{{- end -}}

{{- define "minio-ember.bucketName" -}}
{{- if .Values.tenant.bucketName -}}
{{ .Values.tenant.bucketName }}
{{- else -}}
{{ printf "%s-media" .Release.Name }}
{{- end -}}
{{- end -}}

{{- define "minio-ember.policyName" -}}
{{- if .Values.tenant.policyName -}}
{{ .Values.tenant.policyName }}
{{- else -}}
{{ printf "%s-policy" (include "minio-ember.bucketName" .) }}
{{- end -}}
{{- end -}}

{{- define "minio-ember.accessSecretName" -}}
{{- if .Values.tenant.accessSecretName -}}
{{ .Values.tenant.accessSecretName }}
{{- else -}}
{{ printf "%s-objectstore" (include "minio-ember.fullname" .) }}
{{- end -}}
{{- end -}}
