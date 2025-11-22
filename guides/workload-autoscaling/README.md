# Autoscaling with Workload Variant Autoscaler (WVA)

The [Workload Variant Autoscaler](https://github.com/llm-d-incubation/workload-variant-autoscaler) (WVA) provides dynamic autoscaling capabilities for llm-d inference deployments, automatically adjusting replica counts based on workload metrics and desired performance characteristics.

## Overview

WVA integrates with llm-d to:
- Dynamically scale inference replicas based on workload metrics
- Optimize resource utilization by adjusting to traffic patterns
- Reduce tail latency through intelligent scaling decisions
- Support multiple accelerator types

> **Note**: WVA currently supports only the [Intelligent Inference Scheduling](../inference-scheduling/README.md) well-lit path. Other well-lit paths (such as Prefill/Decode Disaggregation or Wide Expert-Parallelism) are not currently supported.

## Prerequisites

Before installing WVA, ensure you have:

1. **Gateway control plane**: Configure and deploy your [Gateway control plane](../prereq/gateway-provider/README.md) (Istio) before installation.

2. **Prometheus monitoring stack**: WVA requires Prometheus to be accessible for metric collection. **WVA requires HTTPS connections to Prometheus** - HTTP-only Prometheus will cause WVA to fail. The monitoring setup depends on your platform:
   - **OpenShift**: User Workload Monitoring should be enabled (see [OpenShift monitoring docs](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/monitoring/configuring-user-workload-monitoring))
   - **GKE**: An in-cluster Prometheus instance is required (GMP does not expose HTTP API). See [GKE configuration](#gke) below for setup instructions.
   - **Kind/Minikube**: Prometheus must be configured with TLS/HTTPS. Default HTTP-only Prometheus will not work with WVA. See [Kind/Minikube configuration](#other-kubernetes-platforms-kind-minikube-etc) below.
   - **Other Kubernetes**: A Prometheus stack must be installed with HTTPS support (see [monitoring documentation](../../docs/monitoring/README.md))

3. **Prometheus Adapter**: Required for exposing WVA's external metric to Kubernetes autoscalers (HPA or KEDA). Prometheus Adapter must be installed separately as a dependency with WVA-specific configuration rules. It is not installed by the workload-autoscaling helmfile. See [Step 3: Install Prometheus Adapter](#step-3-install-prometheus-adapter-required-dependency) for installation instructions with the correct configuration from the [WVA repository](https://github.com/llm-d-incubation/workload-variant-autoscaler/tree/main/config/samples).

4. **HuggingFace token secret**: The model service requires a Kubernetes secret named `llm-d-hf-token` in your target namespace with the key `HF_TOKEN` containing a valid HuggingFace token to pull models. Create the namespace and secret before running `helmfile apply` (Step 6):
   ```bash
   export HF_TOKEN=<your-huggingface-token>
   export NAMESPACE=llm-d-autoscaler  # or your target namespace
   
   # Create namespace if it doesn't exist
   kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
   
   # Create HuggingFace token secret
   kubectl create secret generic llm-d-hf-token \
       --from-literal="HF_TOKEN=${HF_TOKEN}" \
       --namespace "${NAMESPACE}" \
       --dry-run=client -o yaml | kubectl apply -f -
   ```
   For more details, see the [client setup prerequisites](../prereq/client-setup/README.md#huggingface-token).

## Installation

The workload-autoscaling helmfile installs the complete llm-d [Intelligent Inference Scheduling](../inference-scheduling/README.md) stack (infra, gaie, modelservice) plus WVA in a single `helmfile apply` command. **Install Prometheus Adapter separately in [Step 3](#step-3-install-prometheus-adapter-required-dependency) before running helmfile apply.** 

### Step 1: Configure WVA Values

Edit `workload-autoscaling/values.yaml` to configure WVA settings (controller, Prometheus, accelerator, SLOs, HPA). Set namespace:

```bash
export NAMESPACE=llm-d-autoscaler
```

### Step 2: Platform-Specific Configuration

Update `workload-autoscaling/values.yaml` with platform-specific settings:

#### OpenShift

For OpenShift deployments, update the values file:

```yaml
wva:
  prometheus:
    monitoringNamespace: openshift-user-workload-monitoring
    baseURL: "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091"
    tls:
      insecureSkipVerify: false
      caCertPath: "/etc/ssl/certs/prometheus-ca.crt"
```

Extract CA cert: `kubectl get secret thanos-querier-tls -n openshift-monitoring -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/prometheus-ca.crt`

#### GKE

GMP doesn't expose HTTP API. Deploy in-cluster Prometheus:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts && helm repo update
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n llm-d-monitoring --create-namespace
```

Update `workload-autoscaling/values.yaml`:

```yaml
wva:
  prometheus:
    monitoringNamespace: llm-d-monitoring
    baseURL: "http://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local:9090"
    tls:
      insecureSkipVerify: true
```


#### Other Kubernetes Platforms (Kind, Minikube, etc.)

> **WVA HTTPS Requirement**: WVA **requires** HTTPS for Prometheus connections. The default Prometheus installation on Kind/Minikube uses HTTP only. You **must** configure Prometheus with TLS.

For self-managed Prometheus installations on kind or other Kubernetes platforms:

```yaml
wva:
  prometheus:
    monitoringNamespace: llm-d-monitoring  # Default monitoring namespace for llm-d
    baseURL: "https://llmd-kube-prometheus-stack-prometheus.llm-d-monitoring.svc.cluster.local:9090"  # MUST use https://
    tls:
      insecureSkipVerify: true  # Set to true for self-signed certificates
      caCertPath: ""  # Leave empty when using insecureSkipVerify
```

**Enabling TLS on Prometheus for Kind** (Required):

WVA requires HTTPS for Prometheus. For Kind clusters, configure Prometheus with TLS:

```bash
export MON_NS=llm-d-monitoring

# Create self-signed TLS certificate
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /tmp/prometheus-tls.key -out /tmp/prometheus-tls.crt -days 365 \
  -subj "/CN=prometheus" \
  -addext "subjectAltName=DNS:llmd-kube-prometheus-stack-prometheus.${MON_NS}.svc.cluster.local,DNS:llmd-kube-prometheus-stack-prometheus.${MON_NS}.svc,DNS:prometheus,DNS:localhost"

# Create TLS secret and upgrade Prometheus
kubectl create secret tls prometheus-web-tls --cert=/tmp/prometheus-tls.crt --key=/tmp/prometheus-tls.key -n ${MON_NS} --dry-run=client -o yaml | kubectl apply -f -

helm upgrade llmd prometheus-community/kube-prometheus-stack -n ${MON_NS} \
  --set prometheus.prometheusSpec.web.tlsConfig.cert.secret.name=prometheus-web-tls \
  --set prometheus.prometheusSpec.web.tlsConfig.cert.secret.key=tls.crt \
  --set prometheus.prometheusSpec.web.tlsConfig.keySecret.name=prometheus-web-tls \
  --set prometheus.prometheusSpec.web.tlsConfig.keySecret.key=tls.key \
  --reuse-values
```

> **Note**: For Kind clusters, consider using [simulated-accelerators](../simulated-accelerators/README.md) if vLLM GPU detection fails. WVA automatically discovers its namespace via `POD_NAMESPACE`.

### Step 3: Install Prometheus Adapter (Required Dependency)

Prometheus Adapter exposes WVA's external metric to HPA/KEDA. Install **after** Prometheus TLS configuration (Step 2) with platform-specific settings:

```bash
# Common setup
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
export MON_NS=${MON_NS:-llm-d-monitoring}

# Download platform-specific values
# OpenShift:
curl -o /tmp/prometheus-adapter-values.yaml \
  https://raw.githubusercontent.com/llm-d-incubation/workload-variant-autoscaler/main/config/samples/prometheus-adapter-values-ocp.yaml
PROM_URL="https://thanos-querier.openshift-monitoring.svc.cluster.local"

# Other platforms (GKE/Generic):
# curl -o /tmp/prometheus-adapter-values.yaml \
#   https://raw.githubusercontent.com/llm-d-incubation/workload-variant-autoscaler/main/config/samples/prometheus-adapter-values.yaml
# PROM_URL="http://llmd-kube-prometheus-stack-prometheus.${MON_NS}.svc.cluster.local:9090"

# Update Prometheus URL
sed -i.bak "s|url:.*|url: ${PROM_URL}|" /tmp/prometheus-adapter-values.yaml || \
  echo "Manually edit /tmp/prometheus-adapter-values.yaml to set prometheus.url"

# Install
helm upgrade -i prometheus-adapter prometheus-community/prometheus-adapter \
  --version 4.0.1 -n ${MON_NS} --create-namespace -f /tmp/prometheus-adapter-values.yaml
```

**For Kind/HTTPS Prometheus**: Configure CA certificate before installation:

```bash
export MON_NS=${MON_NS:-llm-d-monitoring}

# Extract CA cert and create ConfigMap
kubectl get secret prometheus-web-tls -n ${MON_NS} -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/prometheus-ca.crt
kubectl create configmap prometheus-ca -n ${MON_NS} --from-file=ca.crt=/tmp/prometheus-ca.crt --dry-run=client -o yaml | kubectl apply -f -

# Download and configure values with CA cert
curl -o /tmp/prometheus-adapter-values.yaml \
  https://raw.githubusercontent.com/llm-d-incubation/workload-variant-autoscaler/main/config/samples/prometheus-adapter-values.yaml

cat >> /tmp/prometheus-adapter-values.yaml <<EOF
prometheus:
  url: https://llmd-kube-prometheus-stack-prometheus.${MON_NS}.svc.cluster.local
  port: 9090
extraArgs:
  - --prometheus-ca-file=/etc/ssl/certs/prometheus-ca.crt
extraVolumeMounts:
  - name: prometheus-ca
    mountPath: /etc/ssl/certs/prometheus-ca.crt
    subPath: ca.crt
    readOnly: true
extraVolumes:
  - name: prometheus-ca
    configMap:
      name: prometheus-ca
EOF

helm upgrade -i prometheus-adapter prometheus-community/prometheus-adapter \
  --version 4.0.1 -n ${MON_NS} --create-namespace -f /tmp/prometheus-adapter-values.yaml
```

Verify: `kubectl get pods -n ${MON_NS} -l app.kubernetes.io/name=prometheus-adapter` and test external metrics API.

### Step 4: Create WVA Namespace (if needed)

The helmfile creates `llm-d-autoscaler` namespace automatically if it doesn't exist. **Note:** If you created the namespace in Prerequisites #4 for the HF token secret, it's already created. For OpenShift only, ensure it has the monitoring label:

```bash
export NAMESPACE=${NAMESPACE:-llm-d-autoscaler}
kubectl label namespace "${NAMESPACE}" openshift.io/user-monitoring=true --overwrite
```

### Step 5: Install WVA CRDs (Required)

Install WVA CRDs before deploying:

```bash
kubectl apply -f https://raw.githubusercontent.com/llm-d-incubation/workload-variant-autoscaler/refs/heads/main/charts/workload-variant-autoscaler/crds/llmd.ai_variantautoscalings.yaml
kubectl get crd variantautoscalings.llmd.ai
```

### Step 6: Install llm-d Stack with WVA

Install the complete llm-d inference-scheduling stack (infra, gaie, modelservice) plus WVA:

```bash
cd guides/workload-autoscaling
helmfile apply -n ${NAMESPACE}
```

This installs the complete [Intelligent Inference Scheduling](../inference-scheduling/README.md) stack:
- **Infra** (gateway infrastructure)
- **GAIE** (inference pool and endpoint picker)
- **Model Service** (vLLM inference pods)
- **WVA** (workload-variant-autoscaler) in `llm-d-autoscaler` namespace

WVA automatically discovers its namespace via `POD_NAMESPACE`.

### Step 7: Verify Installation

```bash
export NAMESPACE=${NAMESPACE:-llm-d-autoscaler}
export MON_NS=${MON_NS:-llm-d-monitoring}

# Check pods
kubectl get pods -n ${MON_NS} -l app.kubernetes.io/name=prometheus-adapter
kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=workload-variant-autoscaler

# Verify metrics and HPA
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/${NAMESPACE}/inferno_desired_replicas" | jq
kubectl get hpa -n ${NAMESPACE}
kubectl get variantautoscalings -n ${NAMESPACE}
```

## Configuration

Edit `workload-autoscaling/values.yaml` for WVA settings. Key configurations:

**Model ID** (must match model configured in modelservice):
```yaml
llmd:
  modelID: "Qwen/Qwen3-0.6B"  # Must match model ID in ms-workload-autoscaling/values.yaml
```

**Accelerator** (L40S, A100, H100, Intel-Max-1550):
```yaml
va:
  accelerator: L40S
  sloTpot: 10    # Time per output token SLO (ms)
  sloTtft: 1000  # Time to first token SLO (ms)
```

**Prometheus** (platform-specific):
```yaml
wva:
  prometheus:
    monitoringNamespace: llm-d-monitoring
    baseURL: "https://..."  # Platform-specific URL
    tls:
      insecureSkipVerify: true
```

See [WVA chart documentation](https://github.com/llm-d-incubation/workload-variant-autoscaler/blob/main/charts/workload-variant-autoscaler/README.md) for all options.

## Cleanup

Remove WVA and Prometheus Adapter:

```bash
# Remove WVA stack
cd guides/workload-autoscaling
helmfile destroy -n ${NAMESPACE:-llm-d-autoscaler}

# Remove Prometheus Adapter (if not needed by other components)
helm uninstall prometheus-adapter -n ${MON_NS:-llm-d-monitoring}
```

The llm-d stack (infra, gaie, modelservice) continues operating without autoscaling after WVA removal.