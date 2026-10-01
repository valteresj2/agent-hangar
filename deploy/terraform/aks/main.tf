# Agent Hangar no Azure: AKS com Cilium (NetworkPolicy), OIDC + Workload Identity e roteamento de aplicativos (NGINX
# gerenciado) + Azure Database for PostgreSQL – Flexible Server com acesso privado (VNet) + o chart Helm.

locals {
  name = var.name
  ksa  = "${var.release}-agent-hangar-central" # ServiceAccount da central (regra do _helpers.tpl do chart)
}

resource "azurerm_resource_group" "rg" {
  name     = "${local.name}-rg"
  location = var.location
}

# ------------------------------------------------------------------ rede
resource "azurerm_virtual_network" "vnet" {
  name                = "${local.name}-vnet"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = ["10.40.0.0/16"]
}

resource "azurerm_subnet" "aks" {
  name                 = "aks"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.40.0.0/20"]
}

resource "azurerm_subnet" "pg" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.40.16.0/24"]
  delegation {
    name = "pg"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_private_dns_zone" "pg" {
  name                = "${local.name}.private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "pg" {
  name                  = "${local.name}-pg"
  private_dns_zone_name = azurerm_private_dns_zone.pg.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
  resource_group_name   = azurerm_resource_group.rg.name
}

# ------------------------------------------------------------------ PostgreSQL Flexible Server (privado)
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "${local.name}-pg"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.pg.id
  private_dns_zone_id           = azurerm_private_dns_zone.pg.id
  public_network_access_enabled = false
  administrator_login           = "hangar"
  administrator_password        = random_password.db.result
  sku_name                      = var.db_sku
  storage_mb                    = 65536
  backup_retention_days         = 14
  geo_redundant_backup_enabled  = false
  dynamic "high_availability" {
    for_each = var.db_high_availability ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }
  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
  depends_on = [azurerm_private_dns_zone_virtual_network_link.pg]
}

resource "azurerm_postgresql_flexible_server_database" "hangar" {
  name      = "hangar"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# ------------------------------------------------------------------ AKS
resource "azurerm_kubernetes_cluster" "aks" {
  name                      = local.name
  location                  = azurerm_resource_group.rg.location
  resource_group_name       = azurerm_resource_group.rg.name
  dns_prefix                = local.name
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  automatic_upgrade_channel = "patch"

  default_node_pool {
    name                 = "system"
    vm_size              = var.node_size
    vnet_subnet_id       = azurerm_subnet.aks.id
    auto_scaling_enabled = true
    min_count            = var.node_min
    max_count            = var.node_max
    zones                = ["1", "2", "3"]
    upgrade_settings {
      max_surge = "33%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    service_cidr        = "10.41.0.0/16"
    dns_service_ip      = "10.41.0.10"
  }

  web_app_routing {
    dns_zone_ids = []
  }
}

# ------------------------------------------------------------------ identidade da central (Workload Identity)
# Pronta para dar acesso a Key Vault, Azure OpenAI etc. sem segredo: atribua papéis a esta identidade.
resource "azurerm_user_assigned_identity" "central" {
  name                = "${local.name}-central"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_federated_identity_credential" "central" {
  name                = "${local.name}-central"
  resource_group_name = azurerm_resource_group.rg.name
  parent_id           = azurerm_user_assigned_identity.central.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:${var.namespace}:${local.ksa}"
}

# ------------------------------------------------------------------ chart
resource "helm_release" "hangar" {
  name             = var.release
  namespace        = var.namespace
  create_namespace = true
  repository       = var.chart_repository
  chart            = var.chart_repository == "" ? "${path.module}/../../../charts/agent-hangar" : "agent-hangar"
  version          = var.chart_repository == "" ? null : var.hangar_version
  timeout          = 900
  values = [
    file("${path.module}/../../../charts/agent-hangar/values-aks.yaml"),
    yamlencode({
      publicUrl      = "https://${var.host}"
      image          = { tag = var.hangar_version }
      serviceAccount = { annotations = { "azure.workload.identity/client-id" = azurerm_user_assigned_identity.central.client_id } }
      central = {
        replicas  = var.central_replicas
        podLabels = { "azure.workload.identity/use" = "true" }
      }
      ingress = {
        host        = var.host
        annotations = var.cert_manager_issuer == "" ? {} : { "cert-manager.io/cluster-issuer" = var.cert_manager_issuer }
      }
      postgresql = {
        enabled  = false
        external = { url = "postgresql+psycopg://hangar:${random_password.db.result}@${azurerm_postgresql_flexible_server.pg.fqdn}:5432/hangar?sslmode=require" }
      }
      networkPolicy = { allowPrivateEgress = false }
      memory        = { enabled = var.memory_backend != "none", backend = var.memory_backend == "none" ? "neo4j" : var.memory_backend }
      sso           = { bootstrapAdminEmails = join(",", var.admin_emails) }
      backup        = { enabled = true, image = "postgres:16" }
    }),
    var.extra_values,
  ]
  depends_on = [azurerm_postgresql_flexible_server_database.hangar, azurerm_federated_identity_credential.central]
}
