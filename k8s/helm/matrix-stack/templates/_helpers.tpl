{{- define "matrix-stack.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "matrix-stack.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "matrix-stack.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}


{{- define "matrix-stack.synapse-internal-url" -}}
{{- printf "http://%s-synapse:8008" (include "matrix-stack.fullname" .) -}}
{{- end -}}
{{- define "matrix-stack.render-config-env" -}}
env:
  - name: REGISTRATION_SHARED_SECRET
    valueFrom:
      secretKeyRef:
        name: {{ include "matrix-stack.secret-name" . }}
        key: registration-shared-secret
{{- if .Values.synapse.oidc.enabled }}
  - name: OIDC_CLIENT_SECRET
    valueFrom:
      secretKeyRef:
        name: {{ include "matrix-stack.secret-name" . }}
        key: {{ .Values.synapse.oidc.clientSecretKey | quote }}
{{- end }}
{{- end -}}

{{- define "matrix-stack.render-config-init" -}}
- name: render-config
  image: python:3.12-alpine
  command: ["python", "/tmpl/render_homeserver.py"]
{{ include "matrix-stack.render-config-env" . | indent 2 }}
  volumeMounts:
    - name: homeserver-tmpl
      mountPath: /tmpl
    - name: config
      mountPath: /config
    - name: secrets
      mountPath: /secrets
{{- end -}}

{{- define "matrix-stack.secret-name" -}}
{{- ternary .Values.sealedSecrets.name .Values.synapse.secrets.name .Values.sealedSecrets.enabled -}}
{{- end -}}
