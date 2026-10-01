output "url" {
  value = "https://${var.host}"
}

output "kubectl" {
  value = "az aks get-credentials -g ${azurerm_resource_group.rg.name} -n ${azurerm_kubernetes_cluster.aks.name}"
}

output "ingress_hint" {
  description = "IP público do roteamento de aplicativos: aponte o DNS do host para ele"
  value       = "kubectl -n app-routing-system get svc nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}'"
}

output "central_identity_client_id" {
  description = "Identidade da central (Workload Identity): dê a ela papéis no Key Vault, Azure OpenAI etc."
  value       = azurerm_user_assigned_identity.central.client_id
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.pg.fqdn
}

output "next_steps" {
  value = "hangar setup --target kubernetes e hangar doctor --namespace ${var.namespace}"
}
