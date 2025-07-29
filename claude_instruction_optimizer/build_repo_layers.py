#!/usr/bin/env python3
"""Build script for generic repository Docker layers."""

import yaml
from pathlib import Path
from generic_repo_manager import (
    TaskConfig, RepoSpec, GenericRepoLayerPlanner, GenericLayerBuilder
)
from dependency_manager import parse_task_dependencies


def load_task_configs(config_file: Path = Path("seeds.yaml")) -> list[TaskConfig]:
    """Load task configurations from YAML file - requires new format."""
    
    with open(config_file) as f:
        config = yaml.safe_load(f)
    
    # Only accept list format with required fields
    if not isinstance(config, list):
        raise ValueError(f"YAML file must contain a list of tasks, got {type(config)}")
    
    task_configs = []
    
    for task_data in config:
        # Validate required fields
        if 'git_repos' not in task_data:
            raise ValueError(f"Task {task_data.get('id', 'unknown')} missing required 'git_repos' field")
        if 'allowed_tools' not in task_data:
            raise ValueError(f"Task {task_data.get('id', 'unknown')} missing required 'allowed_tools' field") 
        if 'internet_needed' not in task_data:
            raise ValueError(f"Task {task_data.get('id', 'unknown')} missing required 'internet_needed' field")
        
        # Convert git_repos to RepoSpec objects - only new format supported
        git_repos = {}
        for repo_url, repo_config in task_data["git_repos"].items():
            if not isinstance(repo_config, dict):
                raise ValueError(f"Task {task_data['id']}: repo config for {repo_url} must be dict with 'commit' and 'main' fields, got {type(repo_config)}")
            if 'commit' not in repo_config:
                raise ValueError(f"Task {task_data['id']}: repo config for {repo_url} missing required 'commit' field")
            if 'main' not in repo_config:
                raise ValueError(f"Task {task_data['id']}: repo config for {repo_url} missing required 'main' field")
            
            git_repos[repo_url] = RepoSpec(
                url=repo_url,
                commit=repo_config["commit"],
                is_main=repo_config["main"]  # No .get() - enforce explicit value
            )
        
        # Parse dependencies
        dependencies = parse_task_dependencies(task_data)
        
        task_config = TaskConfig(
            task_id=task_data["id"],
            prompt=task_data["prompt"],
            git_repos=git_repos,
            allowed_tools=task_data["allowed_tools"],
            internet_needed=task_data["internet_needed"],
            dependencies=dependencies.dependencies
        )
        
        task_configs.append(task_config)
    
    return task_configs


def main():
    """Main build script."""
    
    print("=== Loading task configurations ===")
    task_configs = load_task_configs()
    
    print(f"Found {len(task_configs)} tasks")
    
    # Extract unique repositories
    all_repos = set()
    for config in task_configs:
        all_repos.update(config.git_repos.keys())
    
    print(f"Repositories needed: {sorted(all_repos)}")
    
    print("\n=== Planning optimal layers ===")
    planner = GenericRepoLayerPlanner()
    layer_plans = planner.plan_all_repo_layers(task_configs)
    
    for repo_url, plan in layer_plans.items():
        print(f"\n{repo_url}:")
        print(f"  Local path: {plan['local_path']}")
        print(f"  Mount path: {plan['mount_path']}")
        print(f"  Layers: {len(plan['layers'])}")
        for layer in plan['layers']:
            print(f"    - {layer['image_tag']} ({layer['type']})")
    
    print("\n=== Building Docker layers ===")
    builder = GenericLayerBuilder()
    built_images = builder.build_all_repo_layers(layer_plans, task_configs)
    
    print("\n=== Build Summary ===")
    total_images = 0
    for repo_url, images in built_images.items():
        print(f"{repo_url}: {len(images)} images")
        total_images += len(images)
    
    print(f"Total images built: {total_images}")
    
    print("\n=== Task Image Resolution ===")
    from generic_repo_manager import resolve_task_image
    from dependency_manager import DependencyResolver, TaskDependencies
    
    resolver = DependencyResolver()
    
    # Show all tasks (both with and without repos) and their resolved images
    for config in task_configs:
        image_tag = resolve_task_image(config, layer_plans)
        deps_str = ', '.join(config.dependencies) if config.dependencies else 'default'
        print(f"{config.task_id}:")
        print(f"  Dependencies: [{deps_str}]")
        print(f"  Docker Image: {image_tag}")
        print()
    
    print("=== Dependency Analysis ===")
    all_task_deps = [TaskDependencies(dependencies=config.dependencies) for config in task_configs]
    analysis = resolver.analyze_dependencies_across_tasks(all_task_deps)
    
    print(f"Most common image: {analysis['most_common_image']}")
    print(f"Most common dependency: {analysis['most_common_dependency']}")
    print("\nImage usage distribution:")
    for image, count in analysis['image_priority']:
        print(f"  {image}: {count} tasks")
    print("\nDependency usage distribution:")
    for dep, count in analysis['dependency_priority'][:10]:  # Top 10
        print(f"  {dep}: {count} tasks")


if __name__ == "__main__":
    main()