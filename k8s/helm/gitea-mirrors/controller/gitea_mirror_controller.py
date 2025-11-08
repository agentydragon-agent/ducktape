#!/usr/bin/env python3
"""
Simple Kubernetes controller for GiteaMirror CRDs.
Watches for GiteaMirror resources and manages corresponding Gitea repositories.
"""

import logging
import os
import re
import sys
from typing import Any, Optional

import httpx
import kopf
from kubernetes import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Gitea configuration from environment
GITEA_URL = os.getenv("GITEA_URL", "http://gitea-mirrors.gitea.svc.cluster.local:3000")
GITEA_TOKEN = os.getenv("GITEA_TOKEN")
GITEA_USER = os.getenv("GITEA_USER", "gitea_admin")


def derive_repo_name(url: str) -> str:
    """Derive repository name from URL."""
    # Remove protocol
    url = re.sub(r"^https?://", "", url)
    # Remove common git hosts
    url = re.sub(r"^(github\.com|gitlab\.com|bitbucket\.org)/", "", url)
    # Replace slashes with dashes
    url = url.replace("/", "-")
    # Remove .git suffix
    url = re.sub(r"\.git$", "", url)
    return url.lower()


async def gitea_api_call(
    method: str, path: str, json_data: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Make an API call to Gitea."""
    headers = {
        "Authorization": f"token {GITEA_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=method,
            url=f"{GITEA_URL}/api/v1{path}",
            headers=headers,
            json=json_data,
        )

        if response.status_code >= 400:
            raise Exception(
                f"Gitea API error: {response.status_code} - {response.text}"
            )

        return response.json() if response.content else {}


async def repo_exists(name: str) -> bool:
    """Check if a repository exists in Gitea."""
    try:
        await gitea_api_call("GET", f"/repos/{GITEA_USER}/{name}")
        return True
    except Exception:
        return False


async def create_mirror(name: str, url: str, interval: str, private: bool = False):
    """Create a mirror repository in Gitea."""
    # Create the repository
    repo_data = {
        "name": name,
        "description": f"Mirror of {url}",
        "private": private,
        "auto_init": False,
    }

    repo = await gitea_api_call("POST", "/user/repos", repo_data)

    # Configure as mirror
    mirror_data = {
        "clone_addr": url,
        "interval": interval,
        "mirror": True,
        "private": private,
        "wiki": False,
    }

    await gitea_api_call("POST", f"/repos/{GITEA_USER}/{name}/mirror", mirror_data)

    # Trigger initial sync
    await gitea_api_call("POST", f"/repos/{GITEA_USER}/{name}/mirror-sync")

    return repo


async def update_mirror_interval(name: str, interval: str):
    """Update mirror sync interval."""
    await gitea_api_call(
        "PATCH", f"/repos/{GITEA_USER}/{name}", {"mirror_interval": interval}
    )


async def delete_mirror(name: str):
    """Delete a mirror repository from Gitea."""
    await gitea_api_call("DELETE", f"/repos/{GITEA_USER}/{name}")


@kopf.on.create("gitea.io", "v1alpha1", "giteamirrors")
async def create_handler(spec, name, namespace, patch, **kwargs):
    """Handle GiteaMirror creation."""
    url = spec["url"]
    interval = spec.get("interval", "6h")
    private = spec.get("private", False)

    # Derive repository name
    repo_name = derive_repo_name(url)

    logger.info(f"Creating mirror: {name} -> {repo_name} from {url}")

    try:
        # Check if repository already exists
        if await repo_exists(repo_name):
            logger.info(f"Repository {repo_name} already exists, updating interval")
            await update_mirror_interval(repo_name, interval)
            patch.status["state"] = "updated"
        else:
            # Create new mirror
            await create_mirror(repo_name, url, interval, private)
            patch.status["state"] = "created"

        patch.status["message"] = f"Mirror {repo_name} configured successfully"
        patch.status["repoName"] = repo_name

    except Exception as e:
        logger.error(f"Failed to create mirror {name}: {e}")
        patch.status["state"] = "error"
        patch.status["message"] = str(e)
        raise


@kopf.on.update("gitea.io", "v1alpha1", "giteamirrors")
async def update_handler(spec, old, new, name, namespace, patch, **kwargs):
    """Handle GiteaMirror updates."""
    # Check if interval changed
    old_interval = old["spec"].get("interval", "6h")
    new_interval = new["spec"].get("interval", "6h")

    if old_interval != new_interval:
        repo_name = derive_repo_name(spec["url"])
        logger.info(
            f"Updating mirror interval for {repo_name}: {old_interval} -> {new_interval}"
        )

        try:
            await update_mirror_interval(repo_name, new_interval)
            patch.status["message"] = f"Updated interval to {new_interval}"
        except Exception as e:
            logger.error(f"Failed to update mirror {name}: {e}")
            patch.status["state"] = "error"
            patch.status["message"] = str(e)
            raise


@kopf.on.delete("gitea.io", "v1alpha1", "giteamirrors")
async def delete_handler(spec, name, namespace, **kwargs):
    """Handle GiteaMirror deletion."""
    repo_name = derive_repo_name(spec["url"])

    logger.info(f"Deleting mirror: {name} -> {repo_name}")

    try:
        if await repo_exists(repo_name):
            await delete_mirror(repo_name)
            logger.info(f"Deleted mirror repository {repo_name}")
        else:
            logger.info(f"Repository {repo_name} does not exist, nothing to delete")
    except Exception as e:
        logger.error(f"Failed to delete mirror {name}: {e}")
        # Don't raise - let the resource be deleted anyway


@kopf.on.timer("gitea.io", "v1alpha1", "giteamirrors", interval=3600)
async def sync_timer(spec, name, namespace, patch, **kwargs):
    """Periodic sync trigger (every hour)."""
    repo_name = derive_repo_name(spec["url"])

    try:
        # Trigger sync
        await gitea_api_call("POST", f"/repos/{GITEA_USER}/{repo_name}/mirror-sync")

        # Get last update time
        repo = await gitea_api_call("GET", f"/repos/{GITEA_USER}/{repo_name}")

        patch.status["lastSync"] = repo.get("mirror_updated", "unknown")
        patch.status["state"] = "syncing"

    except Exception as e:
        logger.warning(f"Failed to sync mirror {name}: {e}")


def main():
    """Main entry point for the controller."""
    # Load Kubernetes config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

    # Check for Gitea token
    if not GITEA_TOKEN:
        logger.error("GITEA_TOKEN environment variable is required")
        sys.exit(1)

    # Run the operator
    kopf.run()


if __name__ == "__main__":
    main()
