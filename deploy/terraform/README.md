# Terraform: Agent Hangar on GKE, AKS or EKS

Each folder creates a production-ready base in one `terraform apply` and installs the Helm chart:

| | Cluster | Database | Identity | Ingress |
|---|---|---|---|---|
| [`gke`](gke) | GKE Autopilot (Dataplane V2: NetworkPolicy on) | Cloud SQL Postgres 16, private IP, regional HA, PITR | Workload Identity; the Cloud SQL Auth Proxy runs next to the central | GKE Ingress, global static IP, Google-managed certificate |
| [`aks`](aks) | AKS with Cilium, OIDC and Workload Identity, autoscaling across 3 zones | Azure Database for PostgreSQL Flexible Server 16, private (VNet), zone-redundant HA | User-assigned identity federated with the central's ServiceAccount | Application routing (managed NGINX); TLS with cert-manager |
| [`eks`](eks) | EKS (VPC CNI with NetworkPolicy, EBS CSI gp3, AWS Load Balancer Controller) | RDS Postgres 16, private, Multi-AZ, encrypted | IRSA for the central and the controllers | ALB with an ACM certificate |

All three:
- run **2 central replicas** (high availability);
- keep **14 days** of database backups, plus the chart's `pg_dump` backup;
- turn on agent **memory** (Neo4j by default);
- keep the cluster and the database **protected against `terraform destroy`** (`deletion_protection`).

## Step by step

1. **Requirements:**
   - Terraform 1.6+ and Helm;
   - the cloud CLI signed in (`gcloud auth application-default login`, `az login` or `aws configure`);
   - a domain;
   - EKS only: an ACM certificate for the host.
2. **Configure:**
   ```bash
   cd deploy/terraform/gke            # or aks / eks
   cp terraform.tfvars.example terraform.tfvars   # edit: project/subscription, host, admin e-mails
   ```
   The **state holds the database password**. Turn on the remote backend in `versions.tf` (GCS, Azure Storage or
   S3, all encrypted) before the first `apply`.
3. **Create:**
   ```bash
   terraform init
   terraform apply
   ```
   This takes 15–25 minutes.
4. **DNS:**
   - GKE: point the host at the `ingress_ip` output;
   - AKS: point it at the IP from `ingress_hint`;
   - EKS: point it at the ALB from `alb_hint`.
5. **Finish the setup** with the cluster credentials (the `kubectl` output). `--configure-only` does not touch the
   Helm release managed by Terraform: it only registers and tests the LLM, creates the admin and generates the AI
   tool configs.
   ```bash
   hangar setup --configure-only
   hangar doctor --namespace agent-hangar
   ```

## Customizing

- `extra_values`: YAML merged into the chart values. Use it for SSO (Google, Entra ID, Okta…), MCP OAuth,
  observability (`observability.serviceMonitor`, `observability.otlp.endpoint`) and External Secrets.
- `chart_repository = ""`: uses the chart from this checkout instead of the published one. While the repository is
  private, pulling from ghcr needs `helm registry login ghcr.io`.
- Secrets in a vault: install the External Secrets Operator and set `externalSecrets` in `extra_values`; see
  [docs/kubernetes.md](../../docs/kubernetes.md#secrets-in-a-vault-external-secrets).
- The central's cloud identity (outputs `central_identity_client_id` / `central_role_arn`, and the Google service
  account) starts with no permissions beyond the database. Grant roles as needed: Key Vault, Secret Manager,
  Bedrock through a gateway, and so on.

These stacks pass `terraform validate` in CI. They were not applied to real accounts by the project. Review sizes,
regions and costs before the first `apply`.
