# GPU Cloud Comparison: A100/H100-tier (May 2026)

Scope: renting 1–8× A100 or H100-class GPUs for compute workloads.
Not covering consumer-tier (RTX 4090 etc.) or older (V100, T4) GPUs.

## PCIe vs SXM matters for multi-GPU

- **PCIe**: cheaper, GPU connected via PCIe bus. Fine for inference, single-GPU
  training, or loosely-coupled multi-GPU via NVLink bridges.
- **SXM**: on a baseboard with NVLink, significantly higher GPU-to-GPU bandwidth
  (~600 GB/s vs ~64 GB/s). Required for tightly-coupled multi-GPU training (DDP,
  tensor parallelism). SXM instances are almost always sold as full 8-GPU nodes.

For inference or single-GPU training: PCIe is fine and cheaper.
For serious multi-GPU training: you want SXM 8× nodes.

---

## H100 — price per GPU (May 2026, 24/7 = 730 hrs/mo)

| Provider               | $/GPU/hr | $/GPU/mo | Type      | Min unit     | Notes                                                |
| ---------------------- | -------- | -------- | --------- | ------------ | ---------------------------------------------------- |
| **Vast.ai**            | $1.23    | ~$900    | spot      | 1×           | Variable, interruptible. Can be much lower off-peak. |
| **Thunder Compute**    | $1.38    | ~$1,010  | on-demand | 1×           | Smaller provider, NVL variant                        |
| **Hyperstack**         | $1.90    | ~$1,390  | on-demand | 1×           | —                                                    |
| **RunPod** (community) | $2.69    | ~$1,965  | on-demand | 1×           | SXM; community hardware, less SLA                    |
| **RunPod** (secure)    | $2.99    | ~$2,185  | on-demand | 1×           | SXM; dedicated hosts, better reliability             |
| **OVHcloud**           | $2.99    | ~$2,185  | on-demand | unknown      | —                                                    |
| **Vultr**              | $2.99    | ~$17,500 | on-demand | 8× only      | Per-node (8 GPUs); multi-GPU only                    |
| **Lambda Labs**        | $3.29    | ~$2,400  | on-demand | 1×           | PCIe; most reliable availability of mid-tier         |
| **DigitalOcean**       | $3.39    | ~$2,475  | on-demand | 1×           | —                                                    |
| **CoreWeave**          | $6.16    | ~$36,000 | on-demand | 8× (SXM HGX) | Per-node; enterprise; k8s-native; contract pricing   |
| **AWS p5.4xlarge**     | $6.88    | ~$5,025  | on-demand | 1×           | SXM; p5.48xlarge (8×) = ~$71,800/mo                  |
| **Azure NCadsH100v5**  | $6.98    | ~$5,095  | on-demand | 1×           | —                                                    |

## A100 — price per GPU (May 2026, 24/7 = 730 hrs/mo)

| Provider               | $/GPU/hr   | $/GPU/mo  | Type      | Min unit | Notes                                        |
| ---------------------- | ---------- | --------- | --------- | -------- | -------------------------------------------- |
| **Vast.ai**            | $0.14–0.76 | ~$100–555 | spot      | 1×       | Wildly variable; avg spot ~$0.76             |
| **Thunder Compute**    | $0.78      | ~$570     | on-demand | 1×       | 80GB                                         |
| **RunPod** (community) | $1.19      | ~$870     | on-demand | 1×       | —                                            |
| **Hyperstack**         | $1.35      | ~$985     | on-demand | 1×       | 80GB                                         |
| **RunPod** (secure)    | $1.39      | ~$1,015   | on-demand | 1×       | —                                            |
| **Lambda Labs**        | $1.99      | ~$1,455   | on-demand | 1×       | 40GB variant                                 |
| **CoreWeave**          | $2.21      | ~$1,615   | on-demand | 1×       | 80GB; enterprise                             |
| **AWS p4d.24xlarge**   | $4.10      | ~$23,960  | on-demand | 8× only  | Per-node (8× A100 40GB); $32.77/hr full node |

## Monthly cost — 8× H100 SXM node

| Provider        | $/mo approx     |
| --------------- | --------------- |
| RunPod secure   | ~$17,200        |
| Lambda Labs     | ~$17,000–19,000 |
| CoreWeave       | ~$32,000+       |
| AWS p5.48xlarge | ~$71,800        |

---

## Provider profiles

### Vast.ai

GPU marketplace — individual and datacenter sellers list hardware, you bid/rent.
Cheapest option by far for spot/interruptible workloads. Reliability is variable:
hardware quality depends on the host, uptime is not guaranteed. Good for batch
jobs that can be checkpointed and resumed; bad for anything requiring continuous
uptime or SLA. Has a TF provider and API. Not suitable as a permanent k8s node.

### RunPod

Two tiers: **Community Cloud** (someone's hardware, cheaper, less reliable) and
**Secure Cloud** (dedicated datacenter hardware, more reliable). Good mid-tier
option. API and TF provider available. Pods are more like short-lived instances
than permanent nodes — joining one to a k8s cluster as a persistent worker is
possible but non-trivial (node churn on interruption). Better for on-demand
batch work than as a static cluster node.

### Lambda Labs

Most established mid-tier GPU cloud. Reliable on-demand availability, clean
API, TF provider available. Pricing is mid-range. Good choice for
production-grade GPU workloads without the hyperscaler premium. No k8s
integration out of the box — you get a VM.

### CoreWeave

**K8s-native GPU cloud.** You get actual Kubernetes clusters with GPU node pools
— NVIDIA device plugin, GPU operator, etc. are pre-configured. Directly relevant
if you want to extend your existing cluster or run GPU workloads on k8s. More
expensive than RunPod/Lambda (~$6/GPU/hr H100), but enterprise SLAs and
contract pricing available. Sales-driven for larger commitments. Probably the
best fit if you want GPU nodes in a k8s context without DIY plumbing.

### AWS / GCP / Azure

**Rejected: cost.** 2–5× more per GPU/hr than mid-tier providers for comparable
hardware. AWS p5.48xlarge (8× H100 SXM) is $98/hr on-demand — $71k/mo. The
only reason to use hyperscalers for GPU is if you're deeply integrated with
their ecosystem (managed storage, networking, IAM, SageMaker, Vertex AI, etc.)
or need enterprise SLAs without vendor risk. For raw compute they are a bad deal.

### Hetzner (GPU)

**Not H100/A100.** Hetzner's GPU dedicated servers use NVIDIA RTX (4000 Ada,
6000 Ada, RTX PRO 6000 Blackwell). EU-only (FSN/NBG/HEL). Starting ~€184/mo.
One GPU per server. Good value for RTX-class inference workloads, but not in
the A100/H100 tier. Not relevant for serious training.

### OVH Eco / Kimsufi (GPU)

OVH lists H100 at ~$2.99/GPU/hr but availability and exact configuration are
unclear from public docs. Their GPU servers are likely EU-only (same as dedicated
server auction situation). Worth checking if EU latency is acceptable.

---

## TF / provisioning

| Provider        | TF provider                           | Provisioning model                   |
| --------------- | ------------------------------------- | ------------------------------------ |
| **Lambda Labs** | `lambdal/lambdacloud` (official)      | VM per instance, SSH in              |
| **RunPod**      | `RunPod/runpod` (official)            | Pod API; less suited to Talos        |
| **Vast.ai**     | `vast-ai/vastai` (community)          | Marketplace; unreliable for IaC      |
| **CoreWeave**   | Native k8s API                        | You get a kubeconfig; GPU node pools |
| **AWS**         | `hashicorp/aws` (official, mature)    | EC2 instances                        |
| **GCP**         | `hashicorp/google` (official, mature) | GCE instances                        |
| **Hetzner**     | `hetznercloud/hcloud` (official)      | Dedicated root server                |

---

## K8s integration notes

Joining a GPU node to the existing Talos cluster requires:

1. Talos installed on the node (needs rescue-mode install for bare metal, or a
   GPU-capable Talos image with NVIDIA extensions from Image Factory)
2. Nebula cert for the node (same as any other node)
3. NVIDIA device plugin deployed to the cluster (via Helm/Flux)
4. The GPU provider must allow arbitrary OS installation — most VM providers do,
   bare-metal providers (Hetzner dedicated, OVH, CoreWeave) definitely do

**CoreWeave** is the odd one out: their k8s clusters are managed by them, not
Talos-based. You'd either run workloads there independently or federate with the
existing cluster (more complex). Probably better treated as a separate GPU cluster
than bolted onto the existing one.

**Lambda Labs / RunPod VMs** can run Talos and join via Nebula in principle, but
pod/instance churn (interruptions, billing stops) creates node lifecycle issues for
k8s. Better to treat them as standalone compute rather than persistent cluster nodes.

**Dedicated bare metal with GPU** (e.g. OVH with GPU option, Hetzner dedicated GPU,
HOSTKEY) is the cleanest path for a persistent k8s GPU worker node — install Talos,
join Nebula, join cluster, stays up indefinitely.

---

## Rejected / not compelling

- **AWS/GCP/Azure**: cost, see above
- **Equinix Metal**: EOL June 30, 2026
- **Latitude.sh**: H100 offerings exist but at $2,000+/mo for smallest config;
  primarily AI/ML focused but priced for enterprise
- **Hetzner GPU**: RTX only, EU only, single GPU per server — not H100/A100 tier
- **Paperspace**: $5.99/GPU/hr H100 — expensive relative to Lambda/RunPod for
  no clear benefit; acquired by DigitalOcean, future unclear
