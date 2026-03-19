# Talos readonly client configuration (os:reader role)
#
# Uses talosctl to generate a new talosconfig with limited os:reader role.
# Requires the cluster to be running (depends on bootstrap).

resource "terraform_data" "talos_reader_config" {
  triggers_replace = [
    talos_machine_secrets.cluster.machine_secrets.certs.os.key,
  ]

  provisioner "local-exec" {
    command = "talosctl config new ${path.module}/talosconfig-reader.yml --roles os:reader --crt-ttl 8760h --nodes $NODE"
    environment = {
      TALOSCONFIG = local_file.talosconfig.filename
      NODE        = hcloud_server.vps[local.bootstrap_node].ipv4_address
    }
  }

  depends_on = [
    talos_machine_bootstrap.cluster,
    local_file.talosconfig,
  ]
}

data "local_file" "talos_reader_config" {
  filename   = "${path.module}/talosconfig-reader.yml"
  depends_on = [terraform_data.talos_reader_config]
}
