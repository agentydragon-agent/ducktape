"""Generic task dependency management system for optimal Docker layer selection."""

from dataclasses import dataclass
from typing import Dict, List, Set, Optional
import yaml
from pathlib import Path

@dataclass
class TaskDependencies:
    """Generic dependency specification for a task."""
    dependencies: List[str]  # e.g., ["python-data", "rust", "node"] 
    
    def __post_init__(self):
        """Normalize dependency names."""
        # Ensure all dependencies are lowercase for consistency
        self.dependencies = [dep.lower() for dep in self.dependencies]

class DependencyResolver:
    """Resolves task dependencies to optimal Docker images using configurable mappings."""
    
    def __init__(self, dependency_config_path: Optional[str] = None):
        """Initialize with dependency configuration."""
        self.config = self._load_dependency_config(dependency_config_path)
    
    def _load_dependency_config(self, config_path: Optional[str]) -> Dict:
        """Load dependency configuration from YAML file."""
        # Use provided path or default to dependency_config.yaml
        config_file = config_path or "dependency_config.yaml"
        
        if not Path(config_file).exists():
            raise FileNotFoundError(f"Dependency configuration file not found: {config_file}")
            
        with open(config_file) as f:
            return yaml.safe_load(f)
    
    def resolve_dependencies(self, dependencies: List[str], task_id: str) -> str:
        """Resolve dependency list to per-task Docker image."""
        if not dependencies:
            dependencies = ["system"]  # Default to system-base
        
        # Validate dependencies are available
        self._validate_dependencies(dependencies)
        
        # Always return per-task image name
        return f"claude-dev:task-{task_id}"
    
    def _validate_dependencies(self, dependencies: List[str]) -> None:
        """Validate that all dependencies are known."""
        available_deps = set()
        for layer_info in self.config["layers"].values():
            available_deps.update(layer_info.get("provides", []))
        
        unknown_deps = set(dependencies) - available_deps
        if unknown_deps:
            raise ValueError(f"Unknown dependencies: {unknown_deps}. Available: {sorted(available_deps)}")
    
    # Aliases removed - dependencies are specified directly
    
    def _find_minimal_providing_layer(self, dependencies: List[str]) -> str:
        """Find the layer with lowest build_order that provides all dependencies."""
        layers = self.config["layers"]
        
        # Find layers that provide all required dependencies
        suitable_layers = []
        for layer_name, layer_info in layers.items():
            provided = set(layer_info.get("provides", []))
            required = set(dependencies)
            
            if required.issubset(provided):
                suitable_layers.append((layer_name, layer_info))
        
        if not suitable_layers:
            # Fallback to highest layer if no match found
            print(f"⚠️ Warning: No layer provides all dependencies {dependencies}, using highest layer")
            return max(layers.values(), key=lambda x: x["build_order"])["image_tag"]
        
        # Return the layer with lowest build order (most minimal)
        minimal_layer = min(suitable_layers, key=lambda x: x[1]["build_order"])
        return minimal_layer[1]["image_tag"]
    
    def _get_minimal_image(self) -> str:
        """Get the most minimal image (lowest build order)."""
        layers = self.config["layers"]
        minimal_layer = min(layers.values(), key=lambda x: x["build_order"])
        return minimal_layer["image_tag"]
    
    def analyze_dependencies_across_tasks(self, task_deps: List[TaskDependencies]) -> Dict:
        """Analyze dependency usage across all tasks for optimization insights."""
        image_usage = {}
        dependency_usage = {}
        
        for deps in task_deps:
            # Track image usage
            image_tag = self.resolve_dependencies(deps.dependencies)
            image_usage[image_tag] = image_usage.get(image_tag, 0) + 1
            
            # Track individual dependency usage
            for dep in deps.dependencies:
                dependency_usage[dep] = dependency_usage.get(dep, 0) + 1
        
        # Sort by usage frequency
        sorted_images = sorted(image_usage.items(), key=lambda x: x[1], reverse=True)
        sorted_deps = sorted(dependency_usage.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "image_usage": image_usage,
            "dependency_usage": dependency_usage,
            "image_priority": sorted_images,
            "dependency_priority": sorted_deps,
            "most_common_image": sorted_images[0][0] if sorted_images else None,
            "most_common_dependency": sorted_deps[0][0] if sorted_deps else None,
            "total_tasks": len(task_deps)
        }
    
    def get_available_dependencies(self) -> Dict[str, List[str]]:
        """Get all available dependencies organized by layer."""
        result = {}
        for layer_name, layer_info in self.config["layers"].items():
            result[layer_name] = layer_info.get("provides", [])
        return result
    
    # Aliases removed - use direct dependency specification
    
    def generate_task_dockerfile(self, task_id: str, dependencies: List[str], 
                                 git_repos: Dict = None) -> str:
        """Generate Dockerfile for a specific task - usually just inherits from optimal base layer."""
        if not dependencies:
            dependencies = ["system"]
            
        # Find the minimal layer that provides all dependencies
        base_layer = self._find_minimal_providing_layer(dependencies)
        
        # Simple Dockerfile that inherits from optimal base
        dockerfile_lines = [
            f"# Per-task image for: {task_id}",
            f"# Dependencies: {', '.join(dependencies)}",
            f"FROM {base_layer}",
            "",
            f"LABEL task_id=\"{task_id}\"",
            f"LABEL dependencies=\"{','.join(dependencies)}\"",
            "",
            "WORKDIR /workspace",
            "",
            "# Task-specific customizations can be added here in the future"
        ]
        
        return "\n".join(dockerfile_lines)
    
    def _get_layers_for_dependencies(self, dependencies: List[str]) -> List[str]:
        """Get the minimal set of layers needed for the given dependencies."""
        required_layers = set()
        
        for dep in dependencies:
            # Find which layer provides this dependency
            for layer_name, layer_info in self.config["layers"].items():
                if dep in layer_info.get("provides", []):
                    required_layers.add(layer_name)
                    break
        
        return list(required_layers)
    
    def _get_layer_build_order(self, layer_name: str) -> int:
        """Get build order for a layer."""
        return self.config["layers"][layer_name].get("build_order", 999)

def parse_task_dependencies(task_data: Dict) -> TaskDependencies:
    """Parse task dependency specification from YAML task data."""
    if "dependencies" not in task_data:
        # Default: basic Python environment for backward compatibility
        return TaskDependencies(dependencies=["python"])
    
    deps = task_data["dependencies"]
    
    # Handle different input formats
    if isinstance(deps, str):
        return TaskDependencies(dependencies=[deps])
    elif isinstance(deps, list):
        return TaskDependencies(dependencies=deps)
    else:
        raise ValueError(f"Invalid dependencies format: {deps}. Must be string or list of strings.")
