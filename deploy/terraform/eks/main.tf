# Agent Hangar na AWS: VPC + EKS (VPC CNI com NetworkPolicy, EBS CSI gp3, AWS Load Balancer Controller) + RDS para
# PostgreSQL privado (Multi-AZ) + IRSA para a central e os controladores + o chart Helm (ALB com certificado do ACM).

data "aws_availability_zones" "az" {
  state = "available"
}

locals {
  name = var.name
  azs  = slice(data.aws_availability_zones.az.names, 0, 3)
  ksa  = "${var.release}-agent-hangar-central" # ServiceAccount da central (regra do _helpers.tpl do chart)
}

# ------------------------------------------------------------------ rede
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name                 = local.name
  cidr                 = "10.50.0.0/16"
  azs                  = local.azs
  private_subnets      = ["10.50.0.0/19", "10.50.32.0/19", "10.50.64.0/19"]
  public_subnets       = ["10.50.96.0/22", "10.50.100.0/22", "10.50.104.0/22"]
  database_subnets     = ["10.50.112.0/24", "10.50.113.0/24", "10.50.114.0/24"]
  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}

# ------------------------------------------------------------------ EKS
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name                             = local.name
  cluster_version                          = var.kubernetes_version
  cluster_endpoint_public_access           = true
  enable_cluster_creator_admin_permissions = true
  vpc_id                                   = module.vpc.vpc_id
  subnet_ids                               = module.vpc.private_subnets

  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni = {
      configuration_values = jsonencode({ enableNetworkPolicy = "true" }) # as NetworkPolicies do chart passam a valer
    }
    aws-ebs-csi-driver = {
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_type]
      min_size       = var.node_min
      max_size       = var.node_max
      desired_size   = var.node_min
    }
  }
}

module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.48"

  role_name             = "${local.name}-ebs-csi"
  attach_ebs_csi_policy = true
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }
}

resource "kubernetes_storage_class_v1" "gp3" {
  metadata {
    name        = "gp3"
    annotations = { "storageclass.kubernetes.io/is-default-class" = "true" }
  }
  storage_provisioner    = "ebs.csi.aws.com"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true
  parameters             = { type = "gp3", encrypted = "true" }
}

# ------------------------------------------------------------------ AWS Load Balancer Controller (Ingress -> ALB)
module "lbc_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.48"

  role_name                              = "${local.name}-lbc"
  attach_load_balancer_controller_policy = true
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "helm_release" "lbc" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.lbc_chart_version
  values = [yamlencode({
    clusterName = module.eks.cluster_name
    vpcId       = module.vpc.vpc_id
    region      = var.region
    serviceAccount = {
      name        = "aws-load-balancer-controller"
      annotations = { "eks.amazonaws.com/role-arn" = module.lbc_irsa.iam_role_arn }
    }
  })]
}

# ------------------------------------------------------------------ RDS PostgreSQL (privado)
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_security_group" "db" {
  name   = "${local.name}-db"
  vpc_id = module.vpc.vpc_id
  ingress {
    description     = "Postgres a partir dos nós do EKS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "aws_db_instance" "pg" {
  identifier                   = local.name
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.db_instance_class
  allocated_storage            = 50
  max_allocated_storage        = 500
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_name                      = "hangar"
  username                     = "hangar"
  password                     = random_password.db.result
  db_subnet_group_name         = module.vpc.database_subnet_group_name
  vpc_security_group_ids       = [aws_security_group.db.id]
  multi_az                     = var.db_multi_az
  backup_retention_period      = 14
  deletion_protection          = var.deletion_protection
  skip_final_snapshot          = !var.deletion_protection
  final_snapshot_identifier    = var.deletion_protection ? "${local.name}-final" : null
  performance_insights_enabled = true
  auto_minor_version_upgrade   = true
}

# ------------------------------------------------------------------ identidade da central (IRSA)
# Sem permissões por padrão: anexe políticas (ex.: Bedrock, Secrets Manager) a este papel quando precisar.
module "central_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.48"

  role_name = "${local.name}-central"
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["${var.namespace}:${local.ksa}"]
    }
  }
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
    file("${path.module}/../../../charts/agent-hangar/values-eks.yaml"),
    yamlencode({
      publicUrl      = "https://${var.host}"
      image          = { tag = var.hangar_version }
      serviceAccount = { annotations = { "eks.amazonaws.com/role-arn" = module.central_irsa.iam_role_arn } }
      central        = { replicas = var.central_replicas }
      ingress = {
        host        = var.host
        annotations = { "alb.ingress.kubernetes.io/certificate-arn" = var.acm_certificate_arn }
      }
      postgresql = {
        enabled  = false
        external = { url = "postgresql+psycopg://hangar:${random_password.db.result}@${aws_db_instance.pg.address}:5432/hangar?sslmode=require" }
      }
      memory = { enabled = var.memory_backend != "none", backend = var.memory_backend == "none" ? "neo4j" : var.memory_backend }
      sso    = { bootstrapAdminEmails = join(",", var.admin_emails) }
      backup = { enabled = true }
    }),
    var.extra_values,
  ]
  depends_on = [helm_release.lbc, kubernetes_storage_class_v1.gp3, aws_db_instance.pg]
}
