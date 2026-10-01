output "ingress_ip" {
  description = "Aponte o DNS do host (registro A) para este IP; o certificado gerenciado sai em 15–60 min"
  value       = google_compute_global_address.ingress.address
}

output "url" {
  value = "https://${var.host}"
}

output "kubectl" {
  description = "Credenciais do cluster para kubectl / hangar doctor"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.gke.name} --region ${var.region} --project ${var.project_id}"
}

output "cloud_sql_instance" {
  value = google_sql_database_instance.pg.connection_name
}

output "next_steps" {
  value = "hangar setup --target kubernetes (cadastra o LLM, cria o admin, configura as ferramentas) e hangar doctor --namespace ${var.namespace}"
}
