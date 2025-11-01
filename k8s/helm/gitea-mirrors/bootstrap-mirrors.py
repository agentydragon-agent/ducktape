#!/usr/bin/env python3

import os
import sys
import time
import yaml
from pathlib import Path

from adgn.mcp.gitea_mirror.server import (
    MirrorConfig,
    _ensure_mirror,
    _trigger_sync,
    _wait_for_update,
    _resolve_owner,
    _derive_repo_name,
)

def load_mirrors_list():
    """Load the list of repositories to mirror from bootstrap-mirrors.yaml"""
    yaml_path = Path(__file__).parent / "bootstrap-mirrors.yaml"
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data.get('mirrors', [])

def bootstrap_mirror(cfg: MirrorConfig, url: str):
    """Create and sync a single mirror"""
    try:
        owner = _resolve_owner(cfg.base_url, cfg.token)
        repo = _derive_repo_name(url)
        
        print(f"Creating mirror: {url} -> {owner}/{repo}")
        
        # Ensure the mirror exists
        _ensure_mirror(cfg, url, owner, repo)
        
        # Trigger sync
        print(f"  Triggering sync...")
        _trigger_sync(cfg, owner, repo)
        
        # Wait for update
        print(f"  Waiting for update...")
        repo_data = _wait_for_update(cfg, owner, repo)
        
        print(f"  ✓ Mirror ready: {owner}/{repo} (updated: {repo_data.mirror_updated})")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False

def main():
    # Get configuration from environment or use defaults for local Gitea
    base_url = os.environ.get('GITEA_BASE_URL', 'http://gitea-mirrors.gitea-mirrors.svc.cluster.local:3000')
    token = os.environ.get('GITEA_TOKEN')
    
    if not token:
        print("Error: GITEA_TOKEN environment variable not set")
        print("Please set it to a Gitea access token with write:repository scope")
        sys.exit(1)
    
    # Create config
    cfg = MirrorConfig(
        base_url=base_url,
        token=token,
        poll_interval_secs=2.0,
        poll_timeout_secs=60.0
    )
    
    # Load mirrors list
    mirrors = load_mirrors_list()
    print(f"Found {len(mirrors)} repositories to mirror")
    
    # Bootstrap each mirror
    success_count = 0
    failed_count = 0
    
    for url in mirrors:
        if bootstrap_mirror(cfg, url):
            success_count += 1
        else:
            failed_count += 1
        
        # Small delay between mirrors to avoid overwhelming the API
        time.sleep(1)
    
    # Summary
    print(f"\n=== Summary ===")
    print(f"Successfully created: {success_count} mirrors")
    if failed_count > 0:
        print(f"Failed: {failed_count} mirrors")
        sys.exit(1)
    else:
        print("All mirrors created successfully!")

if __name__ == "__main__":
    main()