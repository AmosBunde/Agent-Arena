{{- define "agent-arena.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "agent-arena.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agent-arena.labels" -}}
app.kubernetes.io/name: {{ include "agent-arena.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "agent-arena.appEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "agent-arena.fullname" . }}-env
      key: DATABASE_URL
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "agent-arena.fullname" . }}-env
      key: REDIS_URL
- name: TRACE_STORE_URL
  value: {{ .Values.objectStore.traceStoreUrl | quote }}
{{- if .Values.objectStore.endpointUrl }}
- name: S3_ENDPOINT_URL
  value: {{ .Values.objectStore.endpointUrl | quote }}
{{- end }}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "agent-arena.fullname" . }}-env
      key: AWS_ACCESS_KEY_ID
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "agent-arena.fullname" . }}-env
      key: AWS_SECRET_ACCESS_KEY
- name: AWS_DEFAULT_REGION
  value: {{ .Values.objectStore.region | quote }}
{{- if .Values.observability.otelExporterEndpoint }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.observability.otelExporterEndpoint | quote }}
{{- end }}
- name: METRICS_ENABLED
  value: {{ .Values.observability.metricsEnabled | quote }}
{{- end -}}
