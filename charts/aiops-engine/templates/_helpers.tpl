{{- define "aiops.name" -}}
{{- printf "%s-aiops" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
