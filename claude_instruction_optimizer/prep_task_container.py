#!/usr/bin/env python3
"""Interactive container setup for testing containerized Claude execution.

This script sets up a container for a specific task and drops you into an interactive
shell where you can test the containerized Claude directly.

Usage:
    python prep_task_container.py [task_id]
    
Examples:
    python prep_task_container.py test-task
    python prep_task_container.py my-debugging-task
    
Inside the container shell, you can run:
    claude -p "check whether you're on a real machine or in a container"
    claude -p "what files are in the current directory?"
    claude -p "create a simple Python script and run it"
"""

import asyncio
import sys
import subprocess
from pathlib import Path

from config import OptimizerConfig
from task_claude import task_claude


async def main():
    """Interactive container setup for testing."""
    if len(sys.argv) > 1:
        task_id = sys.argv[1]
    else:
        task_id = "test-task"
        
    config = OptimizerConfig.from_file()
    test_output_dir = Path.cwd() / "test_container_output" / task_id
    test_output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"🐳 Setting up container for task: {task_id}")
    print(f"📁 Output directory: {test_output_dir}")
    
    try:
        async with task_claude(task_id, config, test_output_dir) as client:
            print("✅ Container ready with PATH isolation active")
            print(f"🔐 Container ID: {client.container_id}")
            print()
            print("🚀 Launching interactive Claude session...")
            print("💡 Try these commands:")
            print("   claude -p 'check whether you're on a real machine or in a container'")
            print("   claude -p 'what files are in the current directory?'")
            print("   claude -p 'create a test Python file and show me its contents'")
            print("   claude -p 'run a bash command to show the environment'")
            print()
            print("📝 All files you create will be copied to the host output directory")
            print("🚪 Type 'exit' to close the container and return to host")
            print("-" * 60)
            
            # Interactive mode - spawn shell with containerized claude in PATH
            result = subprocess.run([
                "docker", "exec", "-it", client.container_id,
                "/bin/bash"
            ])
            
            if result.returncode != 0:
                print(f"⚠️  Interactive session ended with code {result.returncode}")
            else:
                print("✨ Interactive session completed successfully")
                
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error during container setup: {e}")
        raise
        
    print("🧹 Container cleaned up automatically")
    print(f"📂 Check output files in: {test_output_dir}")


if __name__ == "__main__":
    asyncio.run(main())