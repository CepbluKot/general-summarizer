{{- define "general-summarizer.fullname" -}}
{{- printf "general-summarizer" }}
{{- end }}

{{- define "general-summarizer.secretName" -}}
{{- printf "general-summarizer-credentials" }}
{{- end }}

{{- define "general-summarizer.dataPVC" -}}
{{- printf "summarizer-data" }}
{{- end }}

{{- define "general-summarizer.runsPVC" -}}
{{- printf "summarizer-runs" }}
{{- end }}

{{- define "general-summarizer.labels" -}}
app.kubernetes.io/name: general-summarizer
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
