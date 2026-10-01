output "url" {
  value = "https://${var.host}"
}

output "kubectl" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "alb_hint" {
  description = "Endereço do ALB: aponte o DNS do host para ele (Route 53 alias ou CNAME)"
  value       = "kubectl -n ${var.namespace} get ingress -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}'"
}

output "central_role_arn" {
  description = "Papel IAM da central (IRSA): anexe políticas (ex.: Bedrock) quando precisar"
  value       = module.central_irsa.iam_role_arn
}

output "rds_endpoint" {
  value = aws_db_instance.pg.address
}

output "next_steps" {
  value = "hangar setup --target kubernetes e hangar doctor --namespace ${var.namespace}"
}
