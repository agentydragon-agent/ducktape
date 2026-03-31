#!/bin/bash
# KVM AMD stall test matrix — creates VMs, soaks, collects artifacts.
# Run from wyrm2. Requires SSH access to atlas (root@10.2.0.2).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ATLAS="root@10.2.0.2"
RESULTS_DIR="$SCRIPT_DIR/results/$(date +%Y%m%d-%H%M%S)"
VMID=9901
SOAK_SECONDS=300
BOOT_WAIT=90
TALOSCTL="${TALOSCTL:-/tmp/claude-1001/talosctl}"
TALOSCONFIG="${TALOSCONFIG:-$SCRIPT_DIR/../../cluster/terraform/main/talosconfig.yml}"
SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub 2>/dev/null || cat ~/.ssh/id_rsa.pub 2>/dev/null)"
COLLECT_SCRIPT="$SCRIPT_DIR/collect_guest_data.sh"

# Image URLs
TALOS_SCHEMATIC="ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515"
declare -A IMAGE_URLS=(
	[talos-v1.11.6]="factory.talos.dev/image/$TALOS_SCHEMATIC/v1.11.6/nocloud-amd64.qcow2"
	[talos-v1.12.3]="factory.talos.dev/image/$TALOS_SCHEMATIC/v1.12.3/nocloud-amd64.qcow2"
	[arch-cloud]="geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2"
	[fedora-42]="download.fedoraproject.org/pub/fedora/linux/releases/42/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-42-1.1.x86_64.qcow2"
)

mkdir -p "$RESULTS_DIR"
echo "Results directory: $RESULTS_DIR"

log() { echo "[$(date +%H:%M:%S)] $*"; }

ensure_image() {
	local name=$1
	local url=${IMAGE_URLS[$name]}
	ssh "$ATLAS" "test -f /tmp/kvm-test-$name.qcow2 || wget -q -O /tmp/kvm-test-$name.qcow2 'https://$url'"
}

setup_cloud_init() {
	local extra_args=${1:-}
	local runcmd=""
	if [[ -n "$extra_args" ]]; then
		runcmd="runcmd:
  - sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=\"/GRUB_CMDLINE_LINUX_DEFAULT=\"$extra_args /' /etc/default/grub
  - grub-mkconfig -o /boot/grub/grub.cfg
  - reboot"
	fi
	ssh "$ATLAS" "cat > /var/lib/vz/snippets/kvm-test-ci.yaml << 'CIEOF'
#cloud-config
users:
  - name: test
    ssh_authorized_keys:
      - $SSH_PUBKEY
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
packages:
  - stress-ng
$runcmd
CIEOF"
}

create_vm() {
	local image=$1
	local is_talos=false
	[[ "$image" == talos-* ]] && is_talos=true

	log "Creating VM $VMID with image $image..."
	local ci_args=""
	if ! $is_talos; then
		ci_args="--cicustom user=local:snippets/kvm-test-ci.yaml --ipconfig0 ip=dhcp"
	fi

	ssh "$ATLAS" "
    qm create $VMID --name kvm-stall-test --memory 4096 --cores 4 --cpu host \
      --bios ovmf --machine q35 --vga virtio --net0 virtio,bridge=vmbr4,firewall=0 \
      --scsihw virtio-scsi-single --balloon 0 --onboot 0 --ostype l26 \
      --efidisk0 local-zfs:1,efitype=4m,pre-enrolled-keys=0 \
      $ci_args
    qm importdisk $VMID /tmp/kvm-test-$image.qcow2 local-zfs
    qm set $VMID --scsi0 local-zfs:vm-${VMID}-disk-1,discard=on,iothread=1,ssd=1 --boot order=scsi0
    qm start $VMID
  " 2>&1 | grep -v 'transferred\|parse error'
	log "VM $VMID started."
}

destroy_vm() {
	log "Destroying VM $VMID..."
	ssh "$ATLAS" "qm stop $VMID 2>/dev/null; sleep 2; qm destroy $VMID --purge 2>/dev/null" || true
}

get_vm_ip() {
	# Get IP from DHCP lease or qm agent
	local ip
	ip=$(ssh "$ATLAS" "qm guest cmd $VMID network-get-interfaces 2>/dev/null" |
		python3 -c "
import json, sys
data = json.load(sys.stdin)
for iface in data:
    for addr in iface.get('ip-addresses', []):
        ip = addr.get('ip-address', '')
        if ip.startswith('10.2.') and addr.get('ip-address-type') == 'ipv4':
            print(ip); exit()
" 2>/dev/null || true)
	echo "$ip"
}

screenshot() {
	local out=$1
	ssh "$ATLAS" "
    echo 'screendump /tmp/vm${VMID}-console.ppm' | qm monitor $VMID >/dev/null 2>&1
    sleep 1
    python3 -c \"from PIL import Image; Image.open('/tmp/vm${VMID}-console.ppm').save('/tmp/vm${VMID}-console.png')\"
  " 2>/dev/null
	scp "$ATLAS:/tmp/vm${VMID}-console.png" "$out/console.png" 2>/dev/null || true
}

collect_cloud() {
	local ip=$1 out=$2
	log "Collecting data from cloud VM at $ip..."
	scp -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
		"$COLLECT_SCRIPT" "test@$ip:/tmp/collect.sh" 2>/dev/null
	ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
		"test@$ip" "chmod +x /tmp/collect.sh && sudo /tmp/collect.sh /tmp/test-results" 2>/dev/null
	scp -o StrictHostKeyChecking=no -r \
		"test@$ip:/tmp/test-results/*" "$out/" 2>/dev/null
}

collect_talos() {
	local ip=$1 out=$2
	log "Collecting data from Talos VM at $ip..."
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" dmesg >"$out/dmesg.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" read /proc/interrupts >"$out/interrupts.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" read /proc/cmdline >"$out/cmdline.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" read /proc/cpuinfo >"$out/cpuinfo.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" read /proc/softirqs >"$out/softirqs.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" read /proc/meminfo >"$out/meminfo.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" read /proc/stat >"$out/stat.txt" 2>/dev/null || true
	"$TALOSCTL" --insecure -e "$ip" -n "$ip" version >"$out/version.txt" 2>/dev/null || true
	# Summary
	echo "NMI counts:" >"$out/summary.txt"
	grep NMI "$out/interrupts.txt" >>"$out/summary.txt" 2>/dev/null || true
	echo "RCU stalls: $(grep -c 'rcu.*stall\|RCU.*stall' "$out/dmesg.txt" 2>/dev/null || echo 0)" >>"$out/summary.txt"
	echo "NMI messages: $(grep -ci nmi "$out/dmesg.txt" 2>/dev/null || echo 0)" >>"$out/summary.txt"
}

run_test() {
	local test_id=$1 image=$2 guest_args=${3:-} workload=${4:-idle}
	local out="$RESULTS_DIR/$test_id"
	mkdir -p "$out"

	log "=== TEST: $test_id (image=$image, args=$guest_args, workload=$workload) ==="

	# Save test config
	cat >"$out/test_config.json" <<-EOF
		{
		  "test_id": "$test_id",
		  "image": "$image",
		  "guest_args": "$guest_args",
		  "workload": "$workload",
		  "soak_seconds": $SOAK_SECONDS,
		  "host_halt_poll_ns": "$(ssh "$ATLAS" cat /sys/module/kvm/parameters/halt_poll_ns 2>/dev/null)",
		  "host_kernel": "$(ssh "$ATLAS" uname -r 2>/dev/null)",
		  "host_cmdline": "$(ssh "$ATLAS" cat /proc/cmdline 2>/dev/null)",
		  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		}
	EOF

	local is_talos=false
	[[ "$image" == talos-* ]] && is_talos=true

	# Setup cloud-init with optional extra kernel args
	if ! $is_talos; then
		setup_cloud_init "$guest_args"
	fi

	ensure_image "$image"
	create_vm "$image"

	local boot_wait=$BOOT_WAIT
	# Extra wait if guest needs to reboot for kernel args
	[[ -n "$guest_args" ]] && ! $is_talos && boot_wait=$((boot_wait + 60))

	log "Waiting ${boot_wait}s for boot..."
	sleep "$boot_wait"

	# Get VM IP
	local ip
	if $is_talos; then
		# Talos gets DHCP on vmbr4
		ip=$(ssh "$ATLAS" "qm guest cmd $VMID network-get-interfaces 2>/dev/null | python3 -c \"
import json,sys
for i in json.load(sys.stdin):
 for a in i.get('ip-addresses',[]):
  ip=a.get('ip-address','')
  if ip.startswith('10.2.') and a.get('ip-address-type')=='ipv4': print(ip); exit()
\"" 2>/dev/null || true)
	else
		ip=$(get_vm_ip)
	fi

	if [[ -z "$ip" ]]; then
		log "WARNING: Could not determine VM IP, trying console screenshot only"
		screenshot "$out"
		echo "NO_IP" >"$out/error.txt"
		destroy_vm
		return
	fi
	log "VM IP: $ip"

	# Start workload
	if [[ "$workload" == "stress" ]] && ! $is_talos; then
		log "Starting stress-ng..."
		ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
			"test@$ip" "nohup stress-ng --cpu 4 --vm 2 --vm-bytes 256M --timeout ${SOAK_SECONDS}s > /tmp/stress.log 2>&1 &" 2>/dev/null || true
	fi

	log "Soaking for ${SOAK_SECONDS}s..."
	sleep "$SOAK_SECONDS"

	# Collect data
	if $is_talos; then
		collect_talos "$ip" "$out"
	else
		collect_cloud "$ip" "$out"
		# Also grab stress log
		scp -o StrictHostKeyChecking=no \
			"test@$ip:/tmp/stress.log" "$out/stress_log.txt" 2>/dev/null || true
	fi

	# Screenshot
	screenshot "$out"

	# Print summary
	log "--- Results for $test_id ---"
	cat "$out/summary.txt" 2>/dev/null || true
	log "---"

	destroy_vm
}

# ============================================================================
# TEST MATRIX
# ============================================================================

log "Starting test matrix. Results: $RESULTS_DIR"
log "Host: $(ssh "$ATLAS" uname -r 2>/dev/null)"
log "halt_poll_ns: $(ssh "$ATLAS" cat /sys/module/kvm/parameters/halt_poll_ns 2>/dev/null)"
log ""

# Phase 1: Guest kernel isolation (current host config)
run_test "t01-talos-6.12-idle" "talos-v1.11.6" "" "idle"
run_test "t02-talos-6.18-idle" "talos-v1.12.3" "" "idle"
run_test "t03-fedora-6.14-idle" "fedora-42" "" "idle"
run_test "t04-fedora-6.14-stress" "fedora-42" "" "stress"
run_test "t05-arch-6.19-idle" "arch-cloud" "" "idle"
run_test "t06-arch-6.19-stress" "arch-cloud" "" "stress"
run_test "t07-arch-6.19-tsa-off" "arch-cloud" "tsa=off" "stress"
run_test "t08-arch-6.19-mitigations-off" "arch-cloud" "mitigations=off" "stress"

# Print final summary
log ""
log "=== FINAL SUMMARY ==="
for d in "$RESULTS_DIR"/*/; do
	test_id=$(basename "$d")
	nmi_count=$(grep -c 'NMI' "$d/dmesg.txt" 2>/dev/null || echo "?")
	stall_count=$(grep -ci 'rcu.*stall' "$d/dmesg.txt" 2>/dev/null || echo "?")
	kernel=$(head -1 "$d/version.txt" 2>/dev/null | awk '{print $3}' || echo "?")
	echo "$test_id  kernel=$kernel  nmis=$nmi_count  stalls=$stall_count"
done
log "Done. Full artifacts in $RESULTS_DIR"
