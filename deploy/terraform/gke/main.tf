# Agent Hangar no Google Cloud: GKE Autopilot (Dataplane V2: NetworkPolicy ligada) + Cloud SQL para PostgreSQL com IP
# privado + Workload Identity (a central fala com o Cloud SQL pelo Auth Proxy, sem IP liberado e sem chave de conta de
# serviço) + IP global e certificado gerenciado para o Ingress + o chart Helm.

locals {
  name      = var.name
  namespace = var.namespace
  ksa       = "${var.release}-agent-hangar-central" # ServiceAccount da central (regra do _helpers.tpl do chart)
}

resource "google_project_service" "apis" {
  for_each           = toset(["container.googleapis.com", "sqladmin.googleapis.com", "servicenetworking.googleapis.com", "compute.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

# ------------------------------------------------------------------ rede
resource "google_compute_network" "vpc" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "gke" {
  name          = "${local.name}-gke"
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = "10.10.0.0/20"
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/14"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }
  private_ip_google_access = true
}

# acesso privado a serviços (o Cloud SQL ganha um IP dentro da VPC)
resource "google_compute_global_address" "psa" {
  name          = "${local.name}-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa.name]
}

# ------------------------------------------------------------------ Cloud SQL
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "pg" {
  name                = local.name
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.deletion_protection
  settings {
    tier              = var.db_tier
    availability_type = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_autoresize   = true
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 14
      }
    }
    insights_config {
      query_insights_enabled = true
    }
  }
  depends_on = [google_service_networking_connection.psa]
}

resource "google_sql_database" "hangar" {
  name     = "hangar"
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "hangar" {
  name     = "hangar"
  instance = google_sql_database_instance.pg.name
  password = random_password.db.result
}

# ------------------------------------------------------------------ GKE Autopilot
resource "google_container_cluster" "gke" {
  name                = local.name
  location            = var.region
  enable_autopilot    = true
  network             = google_compute_network.vpc.id
  subnetwork          = google_compute_subnetwork.gke.id
  deletion_protection = var.deletion_protection
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }
  release_channel {
    channel = "REGULAR"
  }
  depends_on = [google_project_service.apis]
}

# ------------------------------------------------------------------ identidade da central (Workload Identity)
resource "google_service_account" "central" {
  account_id   = "${local.name}-central"
  display_name = "Agent Hangar central"
}

resource "google_project_iam_member" "sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.central.email}"
}

resource "google_service_account_iam_member" "wi" {
  service_account_id = google_service_account.central.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${local.namespace}/${local.ksa}]"
  depends_on         = [google_container_cluster.gke]
}

# ------------------------------------------------------------------ IP do Ingress (aponte o DNS do host para ele)
resource "google_compute_global_address" "ingress" {
  name = "${local.name}-ip"
}

# ------------------------------------------------------------------ chart
resource "helm_release" "hangar" {
  name             = var.release
  namespace        = local.namespace
  create_namespace = true
  repository       = var.chart_repository
  chart            = var.chart_repository == "" ? "${path.module}/../../../charts/agent-hangar" : "agent-hangar"
  version          = var.chart_repository == "" ? null : var.hangar_version
  timeout          = 900
  values = [
    file("${path.module}/../../../charts/agent-hangar/values-gke.yaml"),
    yamlencode({
      publicUrl      = "https://${var.host}"
      image          = { tag = var.hangar_version }
      serviceAccount = { annotations = { "iam.gke.io/gcp-service-account" = google_service_account.central.email } }
      central        = { replicas = var.central_replicas }
      ingress = {
        host        = var.host
        annotations = { "kubernetes.io/ingress.global-static-ip-name" = google_compute_global_address.ingress.name }
      }
      postgresql = {
        enabled       = false
        cloudSqlProxy = { enabled = true, instance = google_sql_database_instance.pg.connection_name, privateIp = true }
        external      = { url = "postgresql+psycopg://hangar:${random_password.db.result}@127.0.0.1:5432/hangar" }
      }
      memory        = { enabled = var.memory_backend != "none", backend = var.memory_backend == "none" ? "neo4j" : var.memory_backend }
      sso           = { bootstrapAdminEmails = join(",", var.admin_emails) }
      backup        = { enabled = true }
      observability = { serviceMonitor = { enabled = false } }
    }),
    var.extra_values,
  ]
  depends_on = [google_service_account_iam_member.wi, google_sql_database.hangar, google_sql_user.hangar]
}
