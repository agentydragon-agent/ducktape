#!/bin/bash

# VM Screenshot Script for Claude Code
# Takes screenshot of Proxmox VM and converts to viewable PNG format

if [ $# -ne 1 ]; then
  echo "Usage: $0 <VM_ID>"
  echo "Example: $0 106"
  exit 1
fi

VM_ID="$1"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TEMP_PPM="/tmp/vm${VM_ID}-${TIMESTAMP}.ppm"
FINAL_PNG="/tmp/vm${VM_ID}-current.png"

# Step 1: Take screenshot via SSH to Proxmox host
echo "Taking screenshot of VM ${VM_ID}..."
ssh root@atlas "echo 'screendump ${TEMP_PPM}' | qm monitor ${VM_ID}"

if [ $? -ne 0 ]; then
  echo "Error: Failed to take screenshot of VM ${VM_ID}"
  exit 1
fi

# Step 2: Copy screenshot to local machine
echo "Copying screenshot to local machine..."
scp root@atlas:${TEMP_PPM} ${TEMP_PPM}

if [ $? -ne 0 ]; then
  echo "Error: Failed to copy screenshot from Proxmox host"
  exit 1
fi

# Step 3: Convert PPM to PNG using local imagemagick
echo "Converting to PNG format..."
convert ${TEMP_PPM} ${FINAL_PNG}

if [ $? -ne 0 ]; then
  echo "Error: Failed to convert image. Is imagemagick installed?"
  echo "Install with: sudo apt-get install imagemagick"
  exit 1
fi

# Step 4: Clean up temporary files
rm -f ${TEMP_PPM}
ssh root@atlas "rm -f ${TEMP_PPM}" 2>/dev/null

echo "Screenshot saved to: ${FINAL_PNG}"
echo "Use Claude Code Read tool to view: ${FINAL_PNG}"
