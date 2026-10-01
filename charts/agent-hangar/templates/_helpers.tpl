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

{{/* Cloud SQL Auth Proxy como sidecar nativo (initContainer com restartPolicy Always, Kubernetes 1.29+) */}}
{{- define "hangar.cloudSqlProxy" -}}
{{- with .Values.postgresql.cloudSqlProxy }}{{ if .enabled }}
- name: cloud-sql-proxy
  image: {{ .image }}
  restartPolicy: Always
  args:
    - "--structured-logs"
    - "--health-check"
    - "--http-address=0.0.0.0"
    - "--port=5432"
    {{- if .privateIp }}
    - "--private-ip"
    {{- end }}
    {{- if .iamAuth }}
    - "--auto-iam-authn"
    {{- end }}
    - {{ required "postgresql.cloudSqlProxy.instance é obrigatório (PROJETO:REGIÃO:INSTÂNCIA)" .instance | quote }}
  securityContext: {runAsNonRoot: true, allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
  resources: {requests: {cpu: 50m, memory: 64Mi}}
  startupProbe:  # o container principal só começa com o proxy pronto
    httpGet: {path: /startup, port: 9090}
    periodSeconds: 1
    failureThreshold: 60
{{- end }}{{ end }}
{{- end -}}

{{/* pod do pg_dump (CronJob diário e hook pre-upgrade) */}}
{{- define "hangar.backupPod" -}}
{{- $full := include "hangar.fullname" . -}}
metadata:
  labels: {{- include "hangar.selector" . | nindent 4 }}
    app.kubernetes.io/component: backup
spec:
  restartPolicy: Never
  serviceAccountName: {{ $full }}-central
  securityContext: {runAsNonRoot: true, runAsUser: 999, runAsGroup: 999, fsGroup: 999, seccompProfile: {type: RuntimeDefault}}
  {{- include "hangar.pullSecrets" . | nindent 2 }}
  {{- if .Values.postgresql.cloudSqlProxy.enabled }}
  initContainers: {{- include "hangar.cloudSqlProxy" . | nindent 4 }}
  {{- end }}
  containers:
    - name: pg-dump
      image: {{ .Values.backup.image }}
      command: ["/bin/bash", "-ec"]
      args:
        - |
          url="${DATABASE_URL/+psycopg/}"
          # a NetworkPolicy leva alguns segundos para reconhecer um pod novo: espera o banco responder
          for i in $(seq 1 30); do pg_isready -q -d "$url" && break; sleep 2; done
          f="/backup/hangar-$(date -u +%Y%m%d-%H%M%S)-${REASON}.dump"
          pg_dump --format=custom --no-owner --dbname="$url" --file="$f.tmp"
          mv "$f.tmp" "$f"
          echo "backup: $f ($(du -h "$f" | cut -f1))"
          ls -1t /backup/hangar-*.dump | tail -n +$(( {{ .Values.backup.keep }} + 1 )) | xargs -r rm -f
          echo "mantidos: $(ls /backup/hangar-*.dump | wc -l)"
      env:
        - name: DATABASE_URL
          valueFrom: {secretKeyRef: {name: {{ include "hangar.secretName" . }}, key: DATABASE_URL}}
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumeMounts:
        - {name: backup, mountPath: /backup}
        - {name: tmp, mountPath: /tmp}
  volumes:
    - name: backup
      persistentVolumeClaim: {claimName: {{ $full }}-backup}
    - name: tmp
      emptyDir: {}
{{- end -}}
