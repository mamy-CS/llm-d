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

3. **Prometheus Adapter**: Required for exposing custom metrics to Kubernetes HPA. This is installed automatically by the helmfile as part of the inference-scheduling stack.

4. **Platform-specific certificates** (if required):
   - **OpenShift**: Prometheus CA certificate from `openshift-monitoring` namespace
   - **Other platforms**: May require custom TLS configuration depending on your Prometheus setup

## Installation

WVA is installed automatically as part of the base llm-d inference-scheduling stack. The helmfile will automatically install both prometheus-adapter and WVA from the published Helm repository when you deploy the inference-scheduling stack.

### Step 1: Configure WVA Values

WVA is configured primarily through the values file at `workload-autoscaling/values.yaml`. You can customize WVA settings by editing this file.

The default values file includes configuration for:
- WVA controller settings (image, metrics, prometheus connection)
- llm-d integration (namespace, model ID)
- Variant autoscaling settings (accelerator, SLOs)
- HPA configuration
- vLLM service settings

**Optional**: You can override specific values using environment variables (see [Configuration Overrides](#configuration-overrides) section).

Set the base namespace:

```bash
export NAMESPACE=llm-d-inference-scheduler  # Should match your base llm-d namespace
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

### Step 3: Create WVA Namespace (if needed)

The helmfile will create the `workload-variant-autoscaler-system` namespace automatically. For OpenShift, you may need to create it with specific labels first:

```bash
# For OpenShift only - create namespace with monitoring label
kubectl create namespace workload-variant-autoscaler-system
kubectl label namespace workload-variant-autoscaler-system openshift.io/user-monitoring=true
```

For other platforms, the namespace will be created automatically by helmfile when you run `helmfile apply`.

### Step 4: Install Inference Scheduling Stack (includes WVA)

Install the inference-scheduling stack, which includes WVA and prometheus-adapter:

```bash
cd guides/inference-scheduling
helmfile apply -n ${NAMESPACE}
```

This will install:
- Base llm-d components (infra, gaie, modelservice)
- `prometheus-adapter` in the monitoring namespace (for WVA custom metrics)
- `workload-variant-autoscaler` in the `workload-variant-autoscaler-system` namespace

The WVA Helm chart is published to the Helm repository `workload-autoscaling` and will be pulled automatically. The helmfile uses the values file at `workload-autoscaling/values.yaml` for configuration.

### Step 5: Verify Installation

Check that all components are running:

```bash
# Check prometheus-adapter, example for openshift (in monitoring namespace from values.yaml)
kubectl get pods -n openshift-user-workload-monitoring | grep prometheus-adapter
# Or for other platforms, check your monitoring namespace

# Check WVA controller
kubectl get pods -n workload-variant-autoscaler-system

# Verify WVA metrics are available (after a few minutes)
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
  namespace: llm-d-inference-scheduling  # Should match your base llm-d namespace
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

2. **Update WVA model configuration** (in `workload-variant-autoscaler/values.yaml`):
   ```yaml
   llmd:
     modelID: "unsloth/Meta-Llama-3.1-8B"
   ```

### Accelerator Configuration

Set the accelerator type in `workload-variant-autoscaler/values.yaml`:

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
# Find the exact release name (includes release name postfix)
helm ls -n ${NAMESPACE} | grep workload-variant-autoscaler

# Manual uninstall (replace with actual release name from above)
# Default release name is: workload-variant-autoscaler-inference-scheduling
helm uninstall workload-variant-autoscaler-inference-scheduling -n workload-variant-autoscaler-system

# Delete namespace
kubectl delete namespace workload-variant-autoscaler-system

# Optional: Remove prometheus-adapter if not needed by other components
# helm uninstall prometheus-adapter -n <monitoring-namespace>
```

**Important Notes**:
- WVA is installed as part of the base inference-scheduling stack. The release name follows the pattern `workload-variant-autoscaler-{release_name_postfix}`.
- To remove the entire inference-scheduling stack including WVA, use `helmfile destroy -n ${NAMESPACE}`.
- The base llm-d installation will continue to operate without autoscaling after WVA removal.
- Prometheus-adapter is installed as part of the stack for WVA. Consider whether it's needed by other components before uninstalling.

