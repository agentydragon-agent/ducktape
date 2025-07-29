#!/usr/bin/env python3
"""Build all Docker dependency layers with proper tags using buildx caching."""

import subprocess
import sys
import time
import yaml
from pathlib import Path
from typing import List, Optional

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

def build_layer(target: str, tag: str, step: int, total: int) -> bool:
    """Build a single Docker layer with buildx caching."""
    cmd = [
        "docker", "buildx", "build",
        "--target", target,
        "-t", tag,
        "--cache-from", "type=local,src=.docker-cache",
        "--cache-to", "type=local,dest=.docker-cache,mode=max",
        "--load",
        "."
    ]
    return run_command(cmd, f"Building {target} → {tag}", step, total)

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

def load_dependency_config(config_path: str = "dependency_config.yaml"):
    """Load dependency configuration from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Dependency configuration file not found: {config_file}")
    
    with open(config_file) as f:
        return yaml.safe_load(f)

def main():
    """Build all dependency layers in order."""
    print("🐳 === Building Claude Development Environment Dependency Layers ===\n")
    
    # Load configuration
    print("📋 Loading dependency configuration...")
    try:
        config = load_dependency_config()
        layers_config = config["layers"]
        print(f"   Found {len(layers_config)} layers in dependency_config.yaml")
    except Exception as e:
        print(f"❌ Failed to load dependency configuration: {e}")
        sys.exit(1)
    
    # Set up buildx builder first - must succeed for caching to work
    setup_buildx_builder()
    print()
    
    # Build layers in order specified by build_order
    layers = []
    for layer_name, layer_info in layers_config.items():
        build_order = layer_info.get("build_order", 999)
        image_tag = layer_info["image_tag"]
        provides = layer_info.get("provides", [])
        description = f"{layer_name} ({', '.join(provides[:3])}{'...' if len(provides) > 3 else ''})"
        layers.append((build_order, layer_name, image_tag, description))
    
    # Sort by build order
    layers.sort(key=lambda x: x[0])
    build_layers = [(name, tag, desc) for _, name, tag, desc in layers]
    
    total_steps = len(build_layers) + 1  # +1 for final image
    
    print(f"📋 Building {total_steps} Docker images with optimal caching\n")
    
    # Build each layer
    success_count = 0
    total_start_time = time.time()
    
    for i, (target, tag, description) in enumerate(build_layers, 1):
        print(f"📦 Layer {i}: {description}")
        if build_layer(target, tag, i, total_steps):
            success_count += 1
            print()
        else:
            print(f"❌ Build failed at layer {i}/{total_steps}")
            sys.exit(1)
    
    # Build final full image
    print(f"📦 Final Image: Complete development environment")
    cmd = [
        "docker", "buildx", "build",
        "-t", "claude-dev:latest",
        "--cache-from", "type=local,src=.docker-cache",
        "--cache-to", "type=local,dest=.docker-cache,mode=max",
        "--load",
        "."
    ]
    
    if run_command(cmd, "Building claude-dev:latest", total_steps, total_steps):
        success_count += 1
        print()
    else:
        print("❌ Failed to build final image")
        sys.exit(1)
    
    total_elapsed = time.time() - total_start_time
    
    print("=" * 60)
    print(f"🎉 BUILD COMPLETE - {success_count}/{total_steps} images built")
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
    
    print(f"\n🚀 Next step: python3 load_seed_tasks_enhanced.py")
    print("=" * 60)

if __name__ == "__main__":
    main()