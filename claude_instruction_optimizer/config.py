"""Configuration management for the Claude instruction optimizer."""

import os
import json
from pathlib import Path
from typing import Set, Dict, List, Optional
from pydantic import BaseModel, Field


class RolloutConfig(BaseModel):
    """Configuration for coding agent rollouts."""
    max_parallel: int = Field(description="Maximum concurrent rollouts")
    max_turns: int = Field(description="Maximum conversation turns per rollout")
    bash_timeout_ms: int = Field(description="Timeout for bash commands")

class PromptEngineerConfig(BaseModel):
    """Configuration for prompt engineering."""
    model: str = Field(description="Model to use for prompt engineering")
    reasoning_effort: str = Field(description="Reasoning effort level")

class GraderConfig(BaseModel):
    """Configuration for code grading."""
    model: str = Field(description="Model to use for grading")
    reasoning_effort: str = Field(description="Reasoning effort level")

class SummarizerConfig(BaseModel):
    """Configuration for summarization tasks."""
    model: str = Field(description="Model to use for summarization")
    max_tokens: int = Field(description="Max tokens for responses")

class TokenConfig(BaseModel):
    """Token management configuration."""
    max_response_tokens: int = Field(description="Tokens reserved for response generation")
    reasoning_buffer_tokens: int = Field(description="Tokens reserved for reasoning")
    max_context_tokens: int = Field(description="Maximum input tokens")
    max_files_tokens: int = Field(description="Maximum tokens for file content in API calls")

class TruncationConfig(BaseModel):
    """File content truncation configuration.""" 
    max_file_size_grading: int = Field(description="Max file size in bytes before truncation for grading (affects what grader sees)")
    max_file_size_pattern_analysis: int = Field(description="Max file size in bytes before truncation for pattern analysis (affects prompt engineering)")
    log_message_length: int = Field(description="Max length for truncating log messages")

class DockerLayerConfig(BaseModel):
    """Configuration for a single Docker layer."""
    image_tag: str = Field(description="Docker image tag")
    depends_on: List[str] = Field(default_factory=list, description="Layer dependencies")
    capabilities: List[str] = Field(default_factory=list, description="New capabilities this layer adds")

class ExternalImageConfig(BaseModel):
    """Configuration for external/proprietary Docker images."""
    base_image: str = Field(description="Base image name/tag from external registry")
    source: str = Field(description="Source identifier (e.g., 'azure_cr', 'external_registry')")
    description: str = Field(description="Human-readable description of this image")
    add_claude: bool = Field(default=True, description="Whether to layer Claude Code on top of this image")
    platform: Optional[str] = Field(default=None, description="Docker platform (e.g., 'linux/amd64', 'linux/arm64')")

class DockerConfig(BaseModel):
    """Configuration for Docker image management."""
    layers: Dict[str, DockerLayerConfig] = Field(default_factory=dict, description="Regular Docker layers configuration")
    external_images: Dict[str, ExternalImageConfig] = Field(default_factory=dict, description="External/proprietary images configuration")
    
    def get_provides(self, layer_name: str) -> List[str]:
        """Get all capabilities that a layer provides (including inherited ones)."""
        if layer_name not in self.layers:
            return []
        
        layer = self.layers[layer_name]
        provides = list(layer.capabilities)
        
        # Add capabilities from dependencies
        for dep in layer.depends_on:
            provides.extend(self.get_provides(dep))
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(provides))
    
    def get_build_order(self) -> List[str]:
        """Get layers in build order using topological sort."""
        from collections import deque, defaultdict
        
        # Build dependency graph
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        
        # Initialize all layers with 0 in-degree
        for layer_name in self.layers:
            in_degree[layer_name] = 0
        
        # Build the graph
        for layer_name, layer in self.layers.items():
            for dep in layer.depends_on:
                if dep not in self.layers:
                    raise ValueError(f"Layer '{layer_name}' depends on unknown layer '{dep}'")
                graph[dep].append(layer_name)
                in_degree[layer_name] += 1
        
        # Kahn's algorithm for topological sort
        queue = deque([layer for layer, degree in in_degree.items() if degree == 0])
        result = []
        
        while queue:
            layer = queue.popleft()
            result.append(layer)
            
            for neighbor in graph[layer]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if len(result) != len(self.layers):
            raise ValueError("Circular dependency detected in Docker layers")
        
        return result

class OptimizerConfig(BaseModel):
    """Central configuration for the optimizer."""
    
    # Pre-task setup script configuration
    pre_task_setup_script: str | None = Field(description="Path to global pre-task setup script (runs outside container with docker access)")
    seeds_file: str = Field(default="seeds.yaml", description="Path to seeds YAML file containing tasks")
    graders_file: str = Field(default="graders_consolidated.yaml", description="Path to graders YAML file containing task graders")
    
    # Component configurations
    rollouts: RolloutConfig = Field(description="Rollout execution configuration")
    prompt_engineer: PromptEngineerConfig = Field(description="Prompt engineering configuration")
    grader: GraderConfig = Field(description="Code grading configuration")
    summarizer: SummarizerConfig = Field(description="Summarization configuration")
    tokens: TokenConfig = Field(description="Token management configuration")
    truncation: TruncationConfig = Field(description="File and message truncation configuration")
    docker: DockerConfig = Field(default_factory=DockerConfig, description="Docker image management configuration")
    
    # File filtering
    exclude_dirs: Set[str] = Field(description="Directories to exclude from file gathering")
    exclude_extensions: Set[str] = Field(description="File extensions to exclude from file gathering") 
    exclude_files: Set[str] = Field(description="Specific files to exclude from file gathering")
    
    class Config:
        """Pydantic configuration."""
        validate_assignment = True
        extra = "forbid"
    
    @classmethod
    def from_file(cls, config_path: str | Path | None = None) -> "OptimizerConfig":
        """Load configuration from YAML file.
        
        Args:
            config_path: Path to config file. If None, looks for config.yaml in current directory.
            
        Returns:
            OptimizerConfig instance
        """
        if config_path is None:
            config_path = Path.cwd() / "config.yaml"
        else:
            config_path = Path(config_path)
            
        if not config_path.exists():
            # Return default configuration if file doesn't exist
            return cls()
        
        import yaml
        with open(config_path) as f:
            config_data = yaml.safe_load(f)
            
        return cls(**config_data)