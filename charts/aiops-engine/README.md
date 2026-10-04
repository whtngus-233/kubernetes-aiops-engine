# AIOps chart — examples only

This chart is authored for later human review. It has not been installed.
Run `helm lint charts/aiops-engine` and `helm template demo charts/aiops-engine --namespace aiops` locally.
`allowedNamespaces` creates a Role/RoleBinding per namespace, with only pods/events get/list.
No ClusterRole, mutation verbs, Secrets API, logs/exec or AWS permissions are granted.
Choose existing target namespaces; the chart does not create them.

Prometheus/Loki are queried over configured HTTP endpoints, needing network reachability and backend authorization,
not additional Kubernetes API RBAC. A Kubernetes service proxy would separately need narrowly reviewed
services/proxy permissions and a matching transport; that transport is not built into this chart.
Use existing safe endpoints rather than exposing internal observability services publicly.

Provision `existingSecret` separately without putting values in Git, Helm values or command history.
Require AIOPS_API_TOKEN before making the ClusterIP available outside a trusted network.
Keep one replica/one worker until a shared store and distributed deduplication are implemented.
In-cluster ServiceAccount authentication is supported. No kubeconfig or AWS credential is copied into the image.
The operator confirmed a previous HOST image build and HTTP 200, but Docker health was unhealthy. Final image/runtime validation is pending `scripts/final_host_validation.sh` on HOST; the sandbox socket restriction is not a project failure. Registry push, chart installation and Alertmanager reconfiguration remain unverified.
