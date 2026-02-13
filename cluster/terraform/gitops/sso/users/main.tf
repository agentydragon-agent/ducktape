terraform {
  required_version = ">= 1.0"

  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2025.12.0"
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

# ---------- Custom authentication flow (no MFA) ----------
# The default flow includes an MFA validation stage that rejects users with no
# enrolled authenticator devices. We create a custom flow without that stage.
# TODO: Re-enable MFA (TOTP/WebAuthn) once device enrollment is set up.

data "authentik_stage" "identification" {
  name = "default-authentication-identification"
}

data "authentik_stage" "password" {
  name = "default-authentication-password"
}

data "authentik_stage" "login" {
  name = "default-authentication-login"
}

resource "authentik_flow" "authentication" {
  name        = "authentication-flow"
  title       = "Welcome to allegedly.works!"
  slug        = "custom-authentication-flow"
  designation = "authentication"
}

resource "authentik_flow_stage_binding" "identification" {
  target = authentik_flow.authentication.uuid
  stage  = data.authentik_stage.identification.id
  order  = 10
}

resource "authentik_flow_stage_binding" "password" {
  target = authentik_flow.authentication.uuid
  stage  = data.authentik_stage.password.id
  order  = 20
}

resource "authentik_flow_stage_binding" "login" {
  target = authentik_flow.authentication.uuid
  stage  = data.authentik_stage.login.id
  order  = 30
}

resource "authentik_brand" "default" {
  domain              = "allegedly.works"
  default             = true
  flow_authentication = authentik_flow.authentication.uuid
  branding_title      = "allegedly.works"
}
