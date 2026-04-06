# Split Nebula Certs: Plaintext Public + SOPS Private

## Context

Nebula host certs and CA certs are public (signed identity + IP, not secret),
but currently all nebula data is fully SOPS-encrypted. This hides IP assignments
and makes certs uninspectable without decryption. Split public certs into
plaintext PEM files; keep only private keys in SOPS.

## New file layout

```text
secrets/nebula/
  ca.crt                     # CA public cert (plaintext PEM, shared)
  wyrm2.crt                  # host cert (plaintext PEM)
  rugged.crt
  iguana.crt
  atlas.crt
secrets/
  wyrm2-nebula.yaml          # only nebula_host_key (SOPS)
  rugged-nebula.yaml         # only nebula_host_key (SOPS)
  iguana-nebula.yaml         # only nebula_host_key (SOPS)
  atlas-nebula.yaml          # only nebula_host_key (SOPS)
  nebula-ca.yaml             # only ca_key (SOPS)
  k8s-worker.yaml            # keep nebula_ca_cert for now (also has private bootstrap token)
```

The `secrets/nebula/` directory is new — plain PEM files, committed to git, no
encryption. Inspectable with `nebula-cert print -path secrets/nebula/wyrm2.crt`.

## Changes

### 1. Extract certs to plaintext files (manual, requires admin age key)

```bash
mkdir -p secrets/nebula
sops -d --extract '["ca_crt"]' secrets/nebula-ca.yaml > secrets/nebula/ca.crt
for host in wyrm2 rugged iguana atlas; do
  sops -d --extract '["nebula_host_cert"]' secrets/${host}-nebula.yaml > secrets/nebula/${host}.crt
done
```

### 2. Trim SOPS files — remove public keys

For each `secrets/{host}-nebula.yaml`: remove `nebula_host_cert` and
`nebula_ca_cert`, keep only `nebula_host_key`.

For `secrets/nebula-ca.yaml`: remove `ca_crt`, keep only `ca_key`.

### 3. `nix/nixos/modules/k8s-worker-sops.nix`

Current: reads `nebula_host_cert` and `nebula_ca_cert` from SOPS via
`sops.secrets`.

Change: read certs from plaintext files via `builtins.readFile`, write to
`/etc/nebula/` via `environment.etc`. Only `nebula_host_key` stays as
`sops.secrets`.

```nix
# Before
sops.secrets.nebula_ca_cert.sopsFile = k8sWorkerFile;
sops.secrets.nebula_host_cert.sopsFile = cfg.nebulaFile;

ducktape.nebulaMesh = {
  caCertPath = config.sops.secrets.nebula_ca_cert.path;
  hostCertPath = config.sops.secrets.nebula_host_cert.path;
  hostKeyPath = config.sops.secrets.nebula_host_key.path;
};

# After
environment.etc."nebula/ca.crt".text =
  builtins.readFile (secretsDir + "/nebula/ca.crt");
environment.etc."nebula/host.crt".text =
  builtins.readFile (secretsDir + "/nebula/${cfg.hostname}.crt");

ducktape.nebulaMesh = {
  caCertPath = "/etc/nebula/ca.crt";
  hostCertPath = "/etc/nebula/host.crt";
  hostKeyPath = config.sops.secrets.nebula_host_key.path;
};
```

Remove `sops.secrets.nebula_ca_cert` entirely (was from `k8s-worker.yaml`).

### 4. `ansible/roles/nebula/tasks/main.yml`

Current: decrypts entire SOPS file, extracts all three values from YAML.

Change: read certs from plaintext files, only decrypt SOPS for the key.

```yaml
# After — read certs from plain files, only SOPS for key
- name: Deploy Nebula CA certificate
  copy:
    src: "{{ nebula_certs_dir }}/ca.crt"
    dest: /etc/nebula/ca.crt

- name: Deploy Nebula host certificate
  copy:
    src: "{{ nebula_certs_dir }}/{{ inventory_hostname }}.crt"
    dest: /etc/nebula/host.crt

- name: Decrypt Nebula host key with sops
  shell: >
    SOPS_AGE_KEY=... sops -d --extract '["nebula_host_key"]'
    {{ nebula_sops_secrets_file }}
  register: nebula_host_key_raw

- name: Deploy Nebula host key
  copy:
    content: "{{ nebula_host_key_raw.stdout }}"
    dest: /etc/nebula/host.key
    mode: "0600"
```

Add new variable `nebula_certs_dir` pointing to `secrets/nebula/`.

### 5. `cluster/k8s/activitywatch/nebula-certs.sops.yaml`

Leave unchanged for now. It's a k8s Secret — the cert values live inside the
Secret's `stringData`, and Flux needs the full Secret. Could split into a
ConfigMap for certs + Secret for key later, but that's a separate change.

### 6. Update docs

- `cluster/docs/secrets.md`: update "Nebula Certs for Non-Talos Nodes" — certs
  are now plaintext PEM in `secrets/nebula/`, only key in SOPS
- `cluster/docs/bootstrap-dependencies.md`: L1 table — add
  `secrets/nebula/*.crt`

## Files to modify

- `nix/nixos/modules/k8s-worker-sops.nix`
- `ansible/roles/nebula/tasks/main.yml`
- `ansible/atlas.yaml` — add `nebula_certs_dir` variable
- `cluster/docs/secrets.md`
- `cluster/docs/bootstrap-dependencies.md`

## New files

- `secrets/nebula/ca.crt`
- `secrets/nebula/{wyrm2,rugged,iguana,atlas}.crt`

## SOPS files to edit (remove public keys)

- `secrets/wyrm2-nebula.yaml` — remove `nebula_host_cert`, `nebula_ca_cert`
- `secrets/rugged-nebula.yaml` — same
- `secrets/iguana-nebula.yaml` — same
- `secrets/atlas-nebula.yaml` — same
- `secrets/nebula-ca.yaml` — remove `ca_crt`

## Execution order

1. Extract certs to `secrets/nebula/` (requires admin age key on wyrm2)
2. Edit nix modules + ansible role
3. Edit SOPS files to remove public keys
4. Update docs
5. Commit + push
6. Test: `nixos-rebuild build` on wyrm2 (dry build)
7. Deploy: `nixos-rebuild switch` on wyrm2, then rugged/iguana
8. Atlas: `ansible-playbook atlas.yaml --tags nebula`

## Verification

1. `nebula-cert print -path secrets/nebula/wyrm2.crt` — readable without
   decryption
2. `nixos-rebuild build` on wyrm2 — compiles without error
3. `systemctl status nebula` after switch — mesh connected
4. `ping 10.42.0.1` from wyrm2 — lighthouse reachable
