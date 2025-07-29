"""Generic multi-repository Docker layer management system."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import git
import docker
from dataclasses import dataclass
from dependency_manager import DependencyResolver, TaskDependencies

@dataclass
class RepoSpec:
    """Specification for a repository requirement."""
    url: str
    commit: str
    is_main: bool = False


@dataclass
class TaskConfig:
    """Configuration for a task execution."""
    task_id: str
    prompt: str
    git_repos: Dict[str, RepoSpec]  # url -> RepoSpec
    allowed_tools: List[str]
    internet_needed: bool = False
    dependencies: List[str] = None  # e.g., ["python-data", "rust", "node"]
    
    def __post_init__(self):
        """Set default dependencies if none provided."""
        if self.dependencies is None:
            self.dependencies = ["python"]  # Default to basic Python


class GenericRepoLayerPlanner:
    """Plans optimal Docker layers for multiple repositories."""
    
    def __init__(self, local_repo_cache_dir: str = "~/code/"):
        self.cache_dir = Path(local_repo_cache_dir).expanduser()
        self.docker_client = docker.from_env()
        
    def url_to_repo_name(self, repo_url: str) -> str:
        """Convert repo URL to local directory name."""
        if repo_url.startswith("git@"):
            # git@github.com:openai/openai → openai/openai
            return repo_url.split(":", 1)[1]
        else:
            # https://github.com/openai/openai.git → openai/openai
            parts = repo_url.replace("https://", "").replace(".git", "").split("/")
            return f"{parts[1]}/{parts[2]}"

    def url_to_mount_name(self, repo_url: str) -> str:
        """Convert repo URL to container mount name."""
        if repo_url.startswith("git@"):
            # git@github.com:openai/openai → git@github.com:openai
            host_and_org = repo_url.split(":")[0] + ":" + repo_url.split(":")[1].split("/")[0]
            return host_and_org
        else:
            # https://github.com/openai/openai.git → github.com/openai  
            parts = repo_url.replace("https://", "").replace(".git", "").split("/")
            return f"{parts[0]}/{parts[1]}"
            
    def find_local_repo_path(self, repo_url: str) -> Path:
        """Find local checkout path for repo URL."""
        repo_name = self.url_to_repo_name(repo_url)
        local_path = self.cache_dir / repo_name
        
        if not local_path.exists():
            raise ValueError(f"Local repo not found: {local_path}")
            
        return local_path

    def extract_repo_requirements(self, configs: List[TaskConfig]) -> Dict[str, Set[str]]:
        """Extract all repo+commit pairs needed across tasks."""
        repo_commits = defaultdict(set)
        
        for config in configs:
            for repo_url, repo_spec in config.git_repos.items():
                repo_commits[repo_url].add(repo_spec.commit)
                
        return {repo: commits for repo, commits in repo_commits.items()}

    def find_merge_bases_for_repo(self, repo: git.Repo, commits: List[str]) -> Dict[Tuple[str, str], str]:
        """Find merge-base for each pair of commits in a repository."""
        merge_bases = {}
        
        for i, commit_a in enumerate(commits):
            for commit_b in commits[i+1:]:
                try:
                    mb = repo.merge_base(commit_a, commit_b)
                    if mb:
                        merge_bases[(commit_a, commit_b)] = str(mb[0])
                except git.exc.GitCommandError:
                    # Commits might not have common ancestor
                    continue
                    
        return merge_bases

    def plan_repo_layers(self, repo_url: str, needed_commits: List[str]) -> Dict:
        """Plan minimal layers for one repository."""
        
        local_path = self.find_local_repo_path(repo_url)
        repo = git.Repo(local_path)
        
        repo_name = self.url_to_repo_name(repo_url)
        mount_name = self.url_to_mount_name(repo_url) 
        
        # Find merge bases for optimization
        merge_bases = self.find_merge_bases_for_repo(repo, needed_commits)
        
        # Plan layer structure
        base_layer = f"git-{repo_name.replace('/', '-')}-base"
        mount_path = f"/git/{mount_name}"
        
        # Build layer tree (simplified for now - can add merge-base optimization later)
        layers = []
        
        # Base layer
        layers.append({
            "type": "base",
            "image_tag": base_layer,
            "parent": None,
            "commit": None,
            "repo_url": repo_url,
            "mount_path": mount_path
        })
        
        # Commit-specific layers
        for commit in needed_commits:
            commit_layer = f"git-{repo_name.replace('/', '-')}-{commit[:7]}"
            layers.append({
                "type": "commit", 
                "image_tag": commit_layer,
                "parent": base_layer,  # Simplified - could optimize with merge-base
                "commit": commit,
                "repo_url": repo_url,
                "mount_path": mount_path
            })
        
        return {
            "repo_url": repo_url,
            "local_path": local_path,
            "mount_name": mount_name,
            "mount_path": mount_path,
            "layers": layers
        }

    def plan_all_repo_layers(self, task_configs: List[TaskConfig]) -> Dict[str, Dict]:
        """Plan optimal layers for all repos across all tasks."""
        
        repo_requirements = self.extract_repo_requirements(task_configs)
        layer_plans = {}
        
        for repo_url, commits in repo_requirements.items():
            layer_plans[repo_url] = self.plan_repo_layers(repo_url, list(commits))
            
        return layer_plans


class GenericLayerBuilder:
    """Builds Docker layers using Python Docker SDK."""
    
    def __init__(self):
        self.docker_client = docker.from_env()
        
    def image_exists(self, image_tag: str) -> bool:
        """Check if Docker image exists locally."""
        try:
            self.docker_client.images.get(image_tag)
            return True
        except docker.errors.ImageNotFound:
            return False
            
    def build_repo_base_layer(self, repo_url: str, plan: Dict) -> str:
        """Build base layer for repository using Python Docker SDK."""
        
        base_image_tag = plan["layers"][0]["image_tag"]
        
        if self.image_exists(base_image_tag):
            print(f"Base layer {base_image_tag} already exists")
            return base_image_tag
            
        print(f"Building base layer: {base_image_tag}")
        
        # Build arguments
        buildargs = {
            "BASE_IMAGE": "claude-dev:latest",
            "REPO_URL": repo_url,
            "REPO_MOUNT_NAME": plan["mount_name"], 
            "LOCAL_REPO_PATH": str(plan["local_path"])
        }
        
        # Build base layer
        image, build_logs = self.docker_client.images.build(
            path=".",
            dockerfile="Dockerfile.repo-base",
            tag=base_image_tag,
            buildargs=buildargs,
            rm=True
        )
        
        # Print build logs
        for log in build_logs:
            if 'stream' in log:
                print(log['stream'].strip())
                
        return base_image_tag
        
    def build_commit_layer(self, layer_info: Dict, plan: Dict, is_main_repo: bool = False) -> str:
        """Build commit-specific layer."""
        
        image_tag = layer_info["image_tag"]
        
        if self.image_exists(image_tag):
            print(f"Commit layer {image_tag} already exists")
            return image_tag
            
        print(f"Building commit layer: {image_tag} for commit {layer_info['commit']}")
        
        # Build arguments
        buildargs = {
            "PARENT_IMAGE": layer_info["parent"],
            "TARGET_COMMIT": layer_info["commit"],
            "REPO_MOUNT_PATH": plan["mount_path"],
            "IS_MAIN_REPO": "true" if is_main_repo else "false"
        }
        
        # Build commit layer
        image, build_logs = self.docker_client.images.build(
            path=".",
            dockerfile="Dockerfile.repo-commit", 
            tag=image_tag,
            buildargs=buildargs,
            rm=True
        )
        
        # Print build logs
        for log in build_logs:
            if 'stream' in log:
                print(log['stream'].strip())
                
        return image_tag
        
    def build_repo_layer_chain(self, repo_url: str, plan: Dict, main_repo_commits: Set[str] = None) -> List[str]:
        """Build complete layer chain for one repository."""
        
        built_images = []
        main_repo_commits = main_repo_commits or set()
        
        # Build base layer first
        base_image = self.build_repo_base_layer(repo_url, plan)
        built_images.append(base_image)
        
        # Build commit layers
        for layer_info in plan["layers"]:
            if layer_info["type"] == "commit":
                is_main = layer_info["commit"] in main_repo_commits
                commit_image = self.build_commit_layer(layer_info, plan, is_main)
                built_images.append(commit_image)
                
        return built_images
        
    def build_all_repo_layers(self, layer_plans: Dict[str, Dict], task_configs: List[TaskConfig]) -> Dict[str, List[str]]:
        """Build Docker layers for all repositories."""
        
        # Find which commits need main repo linking
        main_repo_commits = {}
        for config in task_configs:
            for repo_url, repo_spec in config.git_repos.items():
                if repo_spec.is_main:
                    if repo_url not in main_repo_commits:
                        main_repo_commits[repo_url] = set()
                    main_repo_commits[repo_url].add(repo_spec.commit)
        
        built_images = {}
        
        for repo_url, plan in layer_plans.items():
            print(f"\n=== Building layers for {repo_url} ===")
            main_commits = main_repo_commits.get(repo_url, set())
            images = self.build_repo_layer_chain(repo_url, plan, main_commits)
            built_images[repo_url] = images
            
        return built_images


def resolve_task_image(task_config: TaskConfig, layer_plans: Dict[str, Dict]) -> str:
    """Resolve task to appropriate Docker image with dependencies and repos."""
    
    # Initialize dependency resolver
    resolver = DependencyResolver()
    
    # If task has repositories, use repo-specific image
    if task_config.git_repos:
        # Find the main repo or first repo
        main_repo = None
        first_repo = None
        
        for repo_url, repo_spec in task_config.git_repos.items():
            if first_repo is None:
                first_repo = repo_url
            if repo_spec.is_main:
                main_repo = repo_url
                break
                
        target_repo = main_repo or first_repo
        
        if target_repo and target_repo in layer_plans:
            plan = layer_plans[target_repo]
            repo_spec = task_config.git_repos[target_repo]
            
            # Find commit-specific layer
            for layer_info in plan["layers"]:
                if layer_info.get("commit") == repo_spec.commit:
                    return layer_info["image_tag"]
    
    # No repositories: resolve based on dependencies only
    task_deps = TaskDependencies(dependencies=task_config.dependencies)
    return resolver.resolve_dependencies(task_deps.dependencies)