# Harbor infrastructure for Props — agent image registry
#
# Creates:
#   - props project (private, for props agent images: critic, grader, etc.)
#   - props robot account with push+pull (used by the props backend proxy
#     to forward pushes to Harbor and to pull config blobs for metadata)
#
# Stores robot credentials in Vault at kv/harbor/props-robot.
# The props backend reads these via the props-harbor-robot ExternalSecret.

data "kubernetes_secret" "harbor_admin_password" {
  metadata {
    name      = "harbor-admin-initial"
    namespace = "harbor"
  }
}

provider "harbor" {
  url      = var.harbor_url
  username = "admin"
  password = data.kubernetes_secret.harbor_admin_password.data["HARBOR_ADMIN_PASSWORD"]
}

provider "vault" {
  address = var.vault_address
  auth_login_jwt {
    mount = "kubernetes"
    role  = "tf-runner"
    jwt   = fileexists("/var/run/secrets/kubernetes.io/serviceaccount/token") ? file("/var/run/secrets/kubernetes.io/serviceaccount/token") : "not-in-cluster"
  }
}

resource "harbor_project" "props" {
  name   = "props"
  public = false
}

resource "harbor_robot_account" "props" {
  name        = "props"
  description = "Props backend proxy — push/pull agent images (critic, grader, critic_dev)"
  level       = "system"

  permissions {
    kind      = "project"
    namespace = harbor_project.props.name

    access {
      action   = "push"
      resource = "repository"
    }
    access {
      action   = "pull"
      resource = "repository"
    }
    access {
      action   = "read"
      resource = "artifact"
    }
    access {
      action   = "create"
      resource = "tag"
    }
    access {
      action   = "delete"
      resource = "artifact"
    }
  }
}

resource "vault_kv_secret_v2" "harbor_props_robot" {
  mount = "kv"
  name  = "harbor/props-robot"

  data_json = jsonencode({
    username = harbor_robot_account.props.full_name
    password = harbor_robot_account.props.secret
  })
}
