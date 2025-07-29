#!/usr/bin/env python3
"""Utility to prep and start a container for a specific task without killing it.

Usage:
    python prep_task_container.py <task_id>
    
Example:
    python prep_task_container.py my_coding_task
"""

import sys
import argparse
import asyncio
from pathlib import Path
from task_context import TaskContainer
from config import OptimizerConfig

async def prep_and_start_container(task_id: str) -> str:
    """Prepare and start a container for the given task.
    
    Args:
        task_id: ID of the task to prepare container for
        
    Returns:
        str: Container ID of the running container
    """
    print(f"🚀 Preparing container for task: {task_id}")
    
    try:
        # Load configuration
        config = OptimizerConfig.from_file()
        
        # Create task container
        task_container = TaskContainer(task_id, config)
        print(f"✅ Found task: {task_id}")
        
        # Create working directory for this container
        base_dir = Path("./task_containers")
        base_dir.mkdir(exist_ok=True)
        
        container_dir = base_dir / f"task_{task_id}"
        container_dir.mkdir(exist_ok=True)
        
        print(f"📁 Working directory: {container_dir}")
        print(f"🐳 Using Docker image: claude-task-{task_id}")
        
        # Start container (keeps running until manually stopped)
        container_id = await task_container.start(container_dir)
        
        print(f"✅ Container started: {container_id[:12]}")
        print("✅ Container setup completed")
        
        print(f"""
🎉 Container ready for task: {task_id}

📋 Container Details:
   ID: {container_id}
   Working Dir: {container_dir}

🔗 Connect to container:
   docker exec -it {container_id} bash

⚠️  Note: Container will remain running until manually stopped.
   To stop: docker stop {container_id}
   Or call: await task_container.stop()
""")
        
        return container_id
        
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ Error loading task: {e}")
        return None
    except Exception as e:
        print(f"❌ Error setting up container: {e}")
        # TaskContext handles its own cleanup in start() method
        return None

def main():
    parser = argparse.ArgumentParser(
        description="Prep and start container for a specific task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s my_coding_task
  %(prog)s python_web_scraper
        """
    )
    
    parser.add_argument(
        "task_id",
        help="ID of the task to prepare container for"
    )
    
    args = parser.parse_args()
    
    container_id = asyncio.run(prep_and_start_container(args.task_id))
    
    if container_id:
        print(f"Container ID: {container_id}")
        sys.exit(0)
    else:
        print("Failed to start container")
        sys.exit(1)

if __name__ == "__main__":
    main()