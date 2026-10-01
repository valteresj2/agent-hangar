{{- define "hangar.fullname" -}}
{{- if contains "agent-hangar" .Release.Name -}}{{ .Release.Name | trunc 40 | trimSuffix "-" }}{{- else -}}{{ printf "%s-agent-hangar" .Release.Name | trunc 40 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "hangar.labels" -}}
app.kubernetes.io/name: agent-hangar
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "hangar.selector" -}}
app.kubernetes.io/name: agent-hangar
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "hangar.tag" -}}{{ .Values.image.tag | default .Chart.AppVersion }}{{- end -}}
{{- define "hangar.image" -}}{{ printf "%s/%s:%s" .ctx.Values.image.registry .name (include "hangar.tag" .ctx) }}{{- end -}}

{{- define "hangar.secretName" -}}
{{- .Values.secrets.existingSecret | default (printf "%s-secrets" (include "hangar.fullname" .)) -}}
{{- end -}}

{{- define "hangar.centralUrl" -}}http://{{ include "hangar.fullname" . }}-central:8080{{- end -}}

{{/* Valor de um segredo: o informado nos values, senão o já gravado no cluster (upgrade), senão um novo. */}}
{{- define "hangar.secret" -}}
{{- $existing := lookup "v1" "Secret" .ctx.Release.Namespace (printf "%s-secrets" (include "hangar.fullname" .ctx)) -}}
{{- if .value -}}{{ .value }}
{{- else if and $existing $existing.data (hasKey $existing.data .key) -}}{{ index $existing.data .key | b64dec }}
{{- else if eq .kind "fernet" -}}{{ randAlphaNum 32 | b64enc | replace "+" "-" | replace "/" "_" }}
{{- else -}}{{ randAlphaNum 48 }}
{{- end -}}
{{- end -}}

{{- define "hangar.podSecurity" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile: {type: RuntimeDefault}
{{- end -}}

{{- define "hangar.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: {drop: [ALL]}
{{- end -}}

{{- define "hangar.pullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}
