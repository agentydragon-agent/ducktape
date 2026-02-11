terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source = "goauthentik/authentik"
    }
  }

  backend "kubernetes" {
    secret_suffix = "authentik-blueprint-users"
    namespace     = "flux-system"
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}

# Data source for authentik Admins group
data "authentik_group" "admins" {
  name = "authentik Admins"
}

# Create agentydragon user
resource "authentik_user" "agentydragon" {
  username = "agentydragon"
  name     = "Rai"
  email    = "agentydragon@gmail.com"
  password = var.user_password
  groups   = [data.authentik_group.admins.id]
}
