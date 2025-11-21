# Autoscaling with Workload Variant Autoscaler (WVA)

The Workload Variant Autoscaler (WVA) provides dynamic autoscaling capabilities for llm-d inference deployments, automatically adjusting replica counts based on workload metrics and desired performance characteristics.

## Overview

WVA integrates with llm-d to:
- Dynamically scale inference replicas based on workload metrics
- Optimize resource utilization by adjusting to traffic patterns
- Reduce tail latency through intelligent scaling decisions
- Support multiple accelerator types

> **Note**: WVA currently supports only the [Intelligent Inference Scheduling](../inference-scheduling/README.md) well-lit path. Other well-lit paths (such as Prefill/Decode Disaggregation or Wide Expert-Parallelism) are not currently supported.

## Prerequisites

Before installing WVA, ensure you have:

1. **llm-d base installation completed**: WVA requires the base llm-d [Intelligent Inference Scheduling](../inference-scheduling/README.md) well-lit path stack to be installed and running. Complete the [base installation](../inference-scheduling/README.md#installation) first.

2. **Prometheus monitoring stack**: WVA requires Prometheus to be accessible for metric collection. The monitoring setup depends on your platform:
   - **OpenShift**: User Workload Monitoring should be enabled (see [OpenShift monitoring docs](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/monitoring/configuring-user-workload-monitoring))
   - **GKE**: Google Cloud Managed Prometheus or automatic application monitoring should be enabled, (see [Google Cloud Managed Prometheus documentation](https://docs.cloud.google.com/stackdriver/docs/managed-prometheus))
   - **Other Kubernetes**: A Prometheus stack must be installed (see [monitoring documentation](../../docs/monitoring/README.md))

3. **Prometheus Adapter**: Required for exposing WVA's external metric to Kubernetes autoscalers (HPA or KEDA). Prometheus Adapter must be installed separately as a dependency with WVA-specific configuration rules. It is not installed by the workload-autoscaling helmfile. See [Step 3: Install Prometheus Adapter](#step-3-install-prometheus-adapter-required-dependency) for installation instructions with the correct configuration from the [WVA repository](https://github.com/llm-d-incubation/workload-variant-autoscaler/tree/main/config/samples).

4. **Platform-specific certificates** (if required):
   - **OpenShift**: Prometheus CA certificate from `openshift-monitoring` namespace
   - **Other platforms**: May require custom TLS configuration depending on your Prometheus setup

## Installation

WVA is installed as part of the workload-autoscaling guide, which includes the base llm-d inference-scheduling stack plus WVA. The helmfile in `guides/workload-autoscaling/` will install the base llm-d components and WVA. **Note**: Prometheus Adapter is a required dependency that must be installed separately (see [Step 3: Install Prometheus Adapter](#step-3-install-prometheus-adapter-required-dependency)). 

### Step 1: Configure WVA Values

WVA is configured primarily through the values file at `workload-autoscaling/values.yaml`. You can customize WVA settings by editing this file.

The default values file includes configuration for:
- WVA controller settings (image, metrics, prometheus connection)
- llm-d integration (namespace, model ID)
- Variant autoscaling settings (accelerator, SLOs)
- HPA/KEDA configuration
- vLLM service settings

**Optional**: You can override specific values using environment variables (see [Configuration Overrides](#configuration-overrides) section).

Set the base namespace:

```bash
export NAMESPACE=llm-d-autoscaler  # Should match your base llm-d namespace
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
      insecureSkipVerify: false  # Set to true for development
      caCertPath: "/etc/ssl/certs/prometheus-ca.crt"
```

Extract the Prometheus CA certificate (if needed):

```bash
kubectl get secret thanos-querier-tls -n openshift-monitoring -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/prometheus-ca.crt
```

#### GKE

For GKE deployments with Managed Prometheus:

```yaml
wva:
  prometheus:
    monitoringNamespace: gmp-system  # or your monitoring namespace
    baseURL: "https://your-prometheus-endpoint"
    tls:
      insecureSkipVerify: true  # Adjust based on your setup
```

#### Other Kubernetes Platforms

For self-managed Prometheus installations:

```yaml
wva:
  prometheus:
    monitoringNamespace: monitoring  # or your Prometheus namespace
    baseURL: "http://prometheus.monitoring.svc.cluster.local:9090"  # Adjust to your setup
    tls:
      insecureSkipVerify: true  # Adjust based on TLS configuration
```

### Step 3: Install Prometheus Adapter (Required Dependency)

Prometheus Adapter is required for WVA to expose the external metric to Kubernetes autoscalers (HPA or KEDA). It must be installed separately before installing WVA with specific configuration rules to expose WVA metrics.

Install Prometheus Adapter in your monitoring namespace:

```bash
# Add prometheus-community helm repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Set monitoring namespace
export MON_NS=${MON_NS:-monitoring}  # Set to your monitoring namespace

# Download the appropriate prometheus-adapter values file from WVA repo
# For OpenShift:
curl -o /tmp/prometheus-adapter-values.yaml \
  https://raw.githubusercontent.com/llm-d-incubation/workload-variant-autoscaler/main/config/samples/prometheus-adapter-values-ocp.yaml

# For other platforms (generic Kubernetes):
# curl -o /tmp/prometheus-adapter-values.yaml \
#   https://raw.githubusercontent.com/llm-d-incubation/workload-variant-autoscaler/main/config/samples/prometheus-adapter-values.yaml

# Update the prometheus URL in the values file to match your Prometheus endpoint
# The downloaded config has platform-specific defaults that may need adjustment:
# - prometheus.url: Update to your Prometheus service URL (e.g., http://prometheus.monitoring.svc.cluster.local)
# - prometheus.port: Update to your Prometheus service port (typically 9090)
# The configuration includes essential rules to expose WVA's external metric
# For OpenShift, the default points to thanos-querier; for other platforms, adjust as needed

# Install prometheus-adapter with WVA-specific configuration
helm upgrade -i prometheus-adapter prometheus-community/prometheus-adapter \
  --version 4.0.1 \
  -n ${MON_NS} \
  --create-namespace \
  -f /tmp/prometheus-adapter-values.yaml
```

> **Note**: The WVA-specific prometheus-adapter configuration includes rules to expose the external metric. See the [WVA repository configuration samples](https://github.com/llm-d-incubation/workload-variant-autoscaler/tree/main/config/samples) for platform-specific values files:
> - [OpenShift](https://github.com/llm-d-incubation/workload-variant-autoscaler/blob/main/config/samples/prometheus-adapter-values-ocp.yaml)
> - [Generic Kubernetes](https://github.com/llm-d-incubation/workload-variant-autoscaler/blob/main/config/samples/prometheus-adapter-values.yaml)

Verify prometheus-adapter is running:

```bash
kubectl get pods -n ${MON_NS} -l app.kubernetes.io/name=prometheus-adapter
```

> **Note**: Prometheus Adapter is not installed by the workload-autoscaling helmfile. It is a required dependency that must be installed separately with WVA-specific configuration.

### Step 4: Create WVA Namespace (if needed)

WVA is installed in the `llm-d-autoscaler` namespace (same as the base llm-d installation). The helmfile will create this namespace automatically when you run `helmfile apply`.

For OpenShift, you may need to create it with specific labels first:

```bash
# For OpenShift only - create namespace with monitoring label
kubectl create namespace llm-d-autoscaler
kubectl label namespace llm-d-autoscaler openshift.io/user-monitoring=true
```

For other platforms, the namespace will be created automatically by helmfile.

### Step 5: Install Inference Scheduling Stack (includes WVA)

Install the inference-scheduling stack, which includes WVA:

```bash
cd guides/workload-autoscaling
helmfile apply -e wva -n ${NAMESPACE}
```

This will install:
- Base llm-d components (infra, gaie, modelservice)
- `workload-variant-autoscaler` in the `llm-d-autoscaler` namespace

> **Note**: Prometheus Adapter must be installed separately as a dependency (see [Step 3](#step-3-install-prometheus-adapter-required-dependency)). It is not installed by this helmfile.

### Step 6: Verify Installation

Check that all components are running:

```bash
# Check prometheus-adapter (should be installed separately in Step 3)
kubectl get pods -n ${MON_NS:-monitoring} -l app.kubernetes.io/name=prometheus-adapter

# Check WVA controller
kubectl get pods -n llm-d-autoscaler -l app.kubernetes.io/name=workload-variant-autoscaler

# Verify WVA metrics are available via prometheus-adapter (after a few minutes)
# This should return the metric exposed by WVA
kubectl get --raw "/apis/external.metrics.k8s.io/v1beta1/namespaces/${NAMESPACE}/inferno_desired_replicas" | jq

# Check VariantAutoscalings resource
kubectl get variantautoscalings -n ${NAMESPACE}
```

## Configuration

WVA is configured primarily through the values file at `workload-autoscaling/values.yaml`. The helmfile automatically uses this file when installing WVA.

### Primary Configuration: Values File

Edit `workload-autoscaling/values.yaml` to customize WVA settings:

```yaml
llmd:
  namespace: llm-d-autoscaler  # Should match your base llm-d namespace
  modelID: "Qwen/Qwen3-0.6B"  # Must match your model ID from base installation

va:
  accelerator: L40S  # Your accelerator type (e.g., L40S, A100, H100, Intel-Max-1550)
  sloTpot: 10  # Time per output token SLO (ms)
  sloTtft: 1000  # Time to first token SLO (ms)

wva:
  prometheus:
    monitoringNamespace: openshift-user-workload-monitoring  # Your monitoring namespace
    baseURL: "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091"
```

The helmfile also sets the following values automatically:
- `targetInferencePool`: Links to the InferencePool (gaie) release
- `targetModelService`: Links to the ModelService (ms) release

### Configuration Overrides

While the values file is the primary configuration method, you can override specific values using environment variables if your helmfile is configured to support them. Check your helmfile configuration for supported environment variable overrides.

The helmfile automatically sets the following values based on your deployment:
- `targetInferencePool`: Automatically links to your InferencePool (gaie) release
- `targetModelService`: Automatically links to your ModelService (ms) release

### Model ID Alignment

**Important**: The model ID configured in WVA (`llmd.modelID` in values.yaml) must match the model ID used in your base llm-d installation.

To use a different model:

1. **Update base llm-d model** (in `ms-inference-scheduling/values.yaml`):
   ```yaml
   modelArtifacts:
     uri: "hf://unsloth/Meta-Llama-3.1-8B"
     name: "unsloth/Meta-Llama-3.1-8B"
   ```

2. **Update WVA model configuration** (in `workload-autoscaling/values.yaml`):
   ```yaml
   llmd:
     modelID: "unsloth/Meta-Llama-3.1-8B"
   ```

### Accelerator Configuration

Set the accelerator type in `workload-autoscaling/values.yaml`:

```yaml
va:
  accelerator: L40S  # For NVIDIA L40S
# or
  accelerator: A100    # For NVIDIA A100
# or
  accelerator: Intel-Max-1550  # For Intel XPU
```

### Custom WVA Configuration

See the [WVA chart documentation](https://github.com/llm-d-incubation/workload-variant-autoscaler/blob/main/charts/workload-variant-autoscaler/README.md) for all available configuration options in the values file.

## Cleanup

To remove WVA:

```bash
# Find the exact release name
helm ls -n llm-d-autoscaler | grep workload-variant-autoscaler

# Manual uninstall (replace with actual release name from above)
# Default release name is: workload-variant-autoscaler
helm uninstall workload-variant-autoscaler -n llm-d-autoscaler

# Remove prometheus-adapter (installed separately as dependency)
export MON_NS=${MON_NS:-monitoring}
helm uninstall prometheus-adapter -n ${MON_NS}
```

**Important Notes**:
- WVA is installed in the `llm-d-autoscaler` namespace (same as the base llm-d installation)
- The release name is `workload-variant-autoscaler`
- To remove the entire workload-autoscaling stack including WVA, run from `guides/workload-autoscaling/`:
  ```bash
  cd guides/workload-autoscaling
  helmfile destroy -e wva -n ${NAMESPACE}
  ```
- The base llm-d installation will continue to operate without autoscaling after WVA removal
- Prometheus-adapter is installed separately as a dependency. Uninstall it only if not needed by other components