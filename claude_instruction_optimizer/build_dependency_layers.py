#!/usr/bin/env python3
"""Build all Docker dependency layers and per-task images with proper tags using buildx caching."""

import subprocess
import sys
import time
import yaml
import tempfile
from pathlib import Path
from typing import List, Optional, Dict

def run_command(cmd: List[str], description: str, step: int, total: int) -> bool:
    """Run a command with nice progress display and real-time output."""
    print(f"[{step}/{total}] {description}")
    print(f"🔨 Command: {' '.join(cmd[:3])} ... {cmd[-1]}")
    
    start_time = time.time()
    try:
        # Run command with real-time output streaming (capture both stdout and stderr)
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
            text=True, bufsize=1, universal_newlines=True
        )
        
        # Stream output in real-time with progress updates
        import select
        last_line = ""
        all_output = []
        
        while True:
            # Check if process is done
            if process.poll() is not None:
                # Get any remaining output
                stdout_remaining = process.stdout.read()
                stderr_remaining = process.stderr.read()
                if stdout_remaining:
                    all_output.append(("stdout", stdout_remaining))
                if stderr_remaining:
                    all_output.append(("stderr", stderr_remaining))
                break
                
            # Read available output
            output = process.stdout.readline()
            if output:
                all_output.append(("stdout", output))
                line = output.strip()
                if line and not line.startswith('#') and 'cache' not in line.lower():
                    if len(line) > 80:
                        line = line[:77] + "..."
                    last_line = line
                    elapsed = time.time() - start_time
                    print(f"\r   🔄 [{elapsed:6.1f}s] {last_line}", end="", flush=True)
        
        if process.returncode == 0:
            elapsed = time.time() - start_time
            print(f"\r   ✅ Complete in {elapsed:.1f}s" + " " * 60)  # Clear the line
            return True
        else:
            elapsed = time.time() - start_time
            print(f"\r   ❌ Failed after {elapsed:.1f}s" + " " * 60)
            
            # Show error output for debugging
            print(f"\n   📋 Error details:")
            if last_line:
                print(f"      Last: {last_line}")
            
            # Show stderr output (errors)
            stderr_lines = []
            stdout_lines = []
            for source, content in all_output:
                if source == "stderr" and content.strip():
                    stderr_lines.extend(content.strip().split('\n'))
                elif source == "stdout" and content.strip():
                    stdout_lines.extend(content.strip().split('\n'))
            
            # Show last few stderr lines (most important)
            if stderr_lines:
                print(f"      STDERR:")
                for line in stderr_lines[-3:]:  # Last 3 stderr lines
                    if line.strip():
                        print(f"        {line.strip()}")
            
            # Show last few stdout lines if no stderr
            if not stderr_lines and stdout_lines:
                print(f"      STDOUT:")
                for line in stdout_lines[-3:]:  # Last 3 stdout lines
                    if line.strip():
                        print(f"        {line.strip()}")
                
            return False
            
    except Exception as e:
        print(f"\r   ❌ Error: {e}")
        return False

def build_docker_image(
    tag: str, 
    description: str,
    step: int = 1, 
    total: int = 1,
    dockerfile: Optional[str] = None,
    target: Optional[str] = None,
    build_args: Optional[Dict[str, str]] = None,
    platform: Optional[str] = None,
    context: str = "."
) -> bool:
    """Shared helper for building Docker images with verbose progress and cache fallback."""
    
    print(f"🔍 Build details:")
    print(f"   🎯 Tag: {tag}")
    print(f"   📝 Description: {description}")
    if dockerfile:
        print(f"   📄 Dockerfile: {dockerfile}")
    if target:
        print(f"   🎯 Target: {target}")
    if platform:
        print(f"   🖥️  Platform: {platform}")
    if build_args:
        print(f"   🔧 Build args: {build_args}")
    
    # Build base command
    cmd_base = ["docker", "buildx", "build"]
    
    if dockerfile:
        cmd_base.extend(["-f", dockerfile])
    if target:
        cmd_base.extend(["--target", target])
    if build_args:
        for key, value in build_args.items():
            cmd_base.extend(["--build-arg", f"{key}={value}"])
    if platform:
        cmd_base.extend(["--platform", platform])
        
    cmd_base.extend(["-t", tag])
    
    # Try with cache first
    cmd_with_cache = cmd_base + [
        "--cache-from", "type=local,src=.docker-cache",
        "--cache-to", "type=local,dest=.docker-cache,mode=max",
        "--load",
        context
    ]
    
    if run_command(cmd_with_cache, f"Building {description}", step, total):
        return True
    
    print("   ⚠️  Cache failed, retrying without cache...")
    
    # Fallback without cache
    cmd_no_cache = cmd_base + ["--load", context]
    return run_command(cmd_no_cache, f"Building {description} (no cache)", step, total)


def build_layer(target: str, tag: str, step: int, total: int) -> bool:
    """Build a single Docker layer with buildx caching."""
    return build_docker_image(
        tag=tag,
        description=f"{target} → {tag}",
        step=step,
        total=total,
        target=target
    )

def setup_buildx_builder():
    """Set up buildx builder that supports caching."""
    print("🔧 Setting up buildx builder with cache support...")
    
    # Check if claude-builder already exists and is running
    try:
        result = subprocess.run([
            "docker", "buildx", "inspect", "claude-builder"
        ], check=True, capture_output=True, text=True)
        
        if "docker-container" in result.stdout and "running" in result.stdout:
            print("   ✅ Using existing claude-builder (docker-container driver)")
            # Switch to use the existing builder
            subprocess.run(["docker", "buildx", "use", "claude-builder"], 
                          check=True, capture_output=True)
            return True
    except subprocess.CalledProcessError:
        pass  # Builder doesn't exist, we'll create it
    
    # Remove existing builder if it exists (but in a broken state)
    subprocess.run(["docker", "buildx", "rm", "claude-builder"], 
                  check=False, capture_output=True)
    
    # Create a new builder instance with docker-container driver (supports caching)
    try:
        result = subprocess.run([
            "docker", "buildx", "create", 
            "--name", "claude-builder",
            "--driver", "docker-container",
            "--use"
        ], check=True, capture_output=True, text=True)
        print("   ✅ Created claude-builder with docker-container driver")
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Failed to create builder: {e}")
        raise RuntimeError("Failed to create buildx builder with caching support. Buildx with docker-container driver is required.")
    
    # Bootstrap the builder
    try:
        subprocess.run(["docker", "buildx", "inspect", "--bootstrap"], 
                      check=True, capture_output=True)
        print("   ✅ Builder ready")
        return True
    except subprocess.CalledProcessError:
        print("   ❌ Builder bootstrap failed")
        raise RuntimeError("Failed to bootstrap buildx builder. Builder setup is required for caching.")

def load_dependency_config(config_path: str = "config.yaml"):
    """Load dependency configuration from main config YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")
    
    with open(config_file) as f:
        full_config = yaml.safe_load(f)
        
    # Extract docker section
    if "docker" not in full_config:
        raise ValueError(f"No 'docker' section found in {config_file}")
        
    return full_config["docker"]

def build_external_image_with_claude(base_image: str, target_tag: str, platform: Optional[str] = None) -> bool:
    """Build external image layered with Claude Code."""
    dockerfile_path = Path("Dockerfile.external")
    
    if not dockerfile_path.exists():
        raise FileNotFoundError(f"External Dockerfile not found: {dockerfile_path}")
    
    return build_docker_image(
        tag=target_tag,
        description=f"External {target_tag} from {base_image}",
        dockerfile=str(dockerfile_path),
        build_args={"BASE_IMAGE": base_image},
        platform=platform
    )

def sync_yaml_to_database(config):
    """Load and sync YAML files to database.
    
    Args:
        config: OptimizerConfig instance with seeds_file and other YAML paths
        
    Returns:
        yaml_loader: Configured YAML loader instance
    """
    print("📥 Loading YAML files and syncing to database...")
    
    try:
        # Import here to avoid circular imports
        from database import init_database
        from yaml_loader import load_yaml_files
        from logging_utils import DualOutputLogging
        
        # Initialize database first
        init_database()
        
        # Setup logging
        DualOutputLogging.setup_logging()
        logger = DualOutputLogging.get_logger()
        
        # Load YAML files from config (not hardcoded)
        seeds_file = config.seeds_file
        graders_file = config.graders_file
        
        yaml_loader = load_yaml_files(seeds_file, graders_file) 
        sync_stats = yaml_loader.load_and_sync_all()
        logger.info("YAML sync completed", **sync_stats)
        print(f"   ✅ Synced {sync_stats.get('tasks_synced', 0)} tasks to database")
        
        return yaml_loader
        
    except Exception as e:
        print(f"❌ Failed to sync YAML to database: {e}")
        sys.exit(1)

def build_task_image(task_db, docker_config) -> bool:
    """Build Docker image for a specific task based on its dependencies."""
    task_id = task_db.task_id
    dependencies = task_db.dependencies_list
    docker_image_tag = task_db.docker_image_tag
    
    print(f"🏗️  Building task image: {docker_image_tag}")
    print(f"   Task: {task_id}")
    print(f"   Dependencies: {dependencies or ['none']}")
    
    # Determine the base layers to include
    layers_to_include = []
    
    # Check external images first
    for dep in dependencies:
        if dep in docker_config.external_images:
            # Use external image as base
            base_image = f"claude-dev:{dep}"
            break
    else:
        # Use regular layers - find the most specific layer that satisfies dependencies
        for dep in reversed(dependencies):  # Start with most specific
            if dep in docker_config.layers:
                base_image = docker_config.layers[dep].image_tag
                break
        else:
            # No specific dependencies, use base development image
            base_image = "claude-dev:latest"
    
    # Create dockerfile content for this task
    dockerfile_content = f'''FROM {base_image}

# Task-specific setup
ENV TASK_ID="{task_id}"
ENV TASK_DEPENDENCIES="{','.join(dependencies)}"

# Task metadata
LABEL task.id="{task_id}"
LABEL task.dependencies="{','.join(dependencies)}"
LABEL task.image_tag="{docker_image_tag}"

# Additional task-specific setup could go here
# (e.g., pre-installing packages, setting up environment)

WORKDIR /workspace
CMD ["sleep", "infinity"]
'''
    
    # Use temporary file context manager for dockerfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.dockerfile', delete=False) as temp_file:
        temp_file.write(dockerfile_content)
        temp_dockerfile = temp_file.name
    
    try:
        return build_docker_image(
            tag=docker_image_tag,
            description=f"Task {task_id}",
            dockerfile=temp_dockerfile
        )
    finally:
        # Clean up temp dockerfile
        Path(temp_dockerfile).unlink(missing_ok=True)

def build_all_task_images(yaml_loader, docker_config):
    """Build Docker images for all tasks in the database."""
    print(f"\n🎯 Building per-task Docker images...")
    
    try:
        # Get active tasks from database (like optimizer.py)
        from database import get_db_session
        
        with get_db_session() as session:
            seed_tasks_db = yaml_loader.get_active_seed_tasks(session)
            
            if not seed_tasks_db:
                print("   ⚠️  No active tasks found in database")
                return 0
                
            print(f"   Found {len(seed_tasks_db)} active tasks to build images for")
            
            success_count = 0
            for i, task_db in enumerate(seed_tasks_db, 1):
                print(f"\n📦 Task {i}/{len(seed_tasks_db)}: {task_db.task_id}")
                
                if build_task_image(task_db, docker_config):
                    success_count += 1
                else:
                    print(f"❌ Failed to build image for task: {task_db.task_id}")
                    sys.exit(1)
            
            print(f"\n✅ Built {success_count}/{len(seed_tasks_db)} task images")
            return success_count
            
    except Exception as e:
        print(f"❌ Error building task images: {e}")
        return 0

def main():
    """Build all dependency layers and per-task images."""
    print("🐳 === Building Claude Development Environment Dependency Layers & Task Images ===\n")
    
    # Step 1: Load configuration using pydantic
    print("📋 Loading configuration...")
    try:
        from config import OptimizerConfig
        full_config = OptimizerConfig.from_file()
        layers_config = full_config.docker.layers
        external_images = full_config.docker.external_images
        print(f"   ✅ Loaded config with {len(layers_config)} layers and {len(external_images)} external images")
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        sys.exit(1)
    
    # Step 2: Sync YAML to database  
    yaml_loader = sync_yaml_to_database(full_config)
    
    # Show how many tasks are now active
    from database import get_db_session
    with get_db_session() as session:
        active_tasks = yaml_loader.get_active_seed_tasks(session)
        print(f"   📋 Active tasks in database: {len(active_tasks)}")
        for task in active_tasks:
            print(f"      - {task.task_id} ({task.dependencies_list})")
    
    # Set up buildx builder first - must succeed for caching to work
    setup_buildx_builder()
    print()
    
    # Build layers in topological order (dependencies first)
    build_order_list = full_config.docker.get_build_order()
    layers = []
    for layer_name in build_order_list:
        layer_info = layers_config[layer_name]
        image_tag = layer_info.image_tag
        capabilities = layer_info.capabilities
        description = f"{layer_name} ({', '.join(capabilities[:3])}{'...' if len(capabilities) > 3 else ''})"
        layers.append((layer_name, image_tag, description))
    
    build_layers = layers  # Already in correct order from get_build_order()
    
    total_steps = len(build_layers) + 1  # +1 for final image
    
    print(f"📋 Building {total_steps} Docker images with optimal caching\n")
    
    # Build each layer
    success_count = 0
    total_start_time = time.time()
    
    for i, (layer_name, image_tag, description) in enumerate(build_layers, 1):
        print(f"📦 Layer {i}: {description}")
        if build_layer(layer_name, image_tag, i, total_steps):
            success_count += 1
            print()
        else:
            print(f"❌ Build failed at layer {i}/{total_steps}")
            sys.exit(1)
    
    # Build final full image
    print(f"📦 Final Image: Complete development environment")
    if build_docker_image(
        tag="claude-dev:latest",
        description="Complete development environment",
        step=total_steps,
        total=total_steps
    ):
        success_count += 1
        print()
    else:
        print("❌ Failed to build final image")
        sys.exit(1)
    
    # Build external images with Claude layering
    for ext_name, ext_config in external_images.items():
        if ext_config.add_claude:
            print(f"📦 External Image: {ext_name} + Claude Code")
            base_image = ext_config.base_image
            target_tag = f"claude-dev:{ext_name}"
            
            platform = getattr(ext_config, 'platform', None)
            if build_external_image_with_claude(base_image, target_tag, platform):
                success_count += 1
                print(f"   ✅ Built {target_tag} from {base_image}")
                print()
            else:
                print(f"❌ Failed to build {target_tag} - base image not available")
                sys.exit(1)
    
    # Build per-task images
    task_images_built = build_all_task_images(yaml_loader, full_config.docker)
    success_count += task_images_built
    
    total_elapsed = time.time() - total_start_time
    
    print("=" * 60)
    print(f"🎉 BUILD COMPLETE - {success_count} images built")
    print(f"⏱️  Total time: {total_elapsed:.1f} seconds")
    
    # Show available images with sizes
    print(f"\n📊 Available dependency images:")
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "table {{.Repository}}:{{.Tag}}\t{{.Size}}"],
            capture_output=True, text=True, check=True
        )
        
        lines = result.stdout.strip().split('\n')
        print(f"   {lines[0]}")  # Header
        for line in lines[1:]:
            if 'claude-dev' in line:
                print(f"   {line}")
                
    except subprocess.CalledProcessError:
        print("   Could not list Docker images")
    
    print(f"\n🚀 Next step: python3 optimizer.py")
    print("=" * 60)

if __name__ == "__main__":
    main()