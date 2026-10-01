terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # Estado remoto com criptografia (o estado guarda a senha do banco): descomente e ajuste.
  # backend "gcs" {
  #   bucket = "minha-empresa-tfstate"
  #   prefix = "agent-hangar"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_client_config" "me" {}

provider "helm" {
  kubernetes {
    host                   = "https://${google_container_cluster.gke.endpoint}"
    token                  = data.google_client_config.me.access_token
    cluster_ca_certificate = base64decode(google_container_cluster.gke.master_auth[0].cluster_ca_certificate)
  }
}
