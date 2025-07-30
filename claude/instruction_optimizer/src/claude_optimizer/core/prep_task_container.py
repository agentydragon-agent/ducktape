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
import subprocess
from pathlib import Path

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.core.containerized_claude import task_claude
from claude_optimizer.database.models import init_database


async def main():
    """Interactive container setup for testing."""
    config = OptimizerConfig.from_file()

    # Initialize database (required for task lookup)
    print("🗃️  Initializing database...")
    init_database()

    # Get a random task from the database
    from claude_optimizer.database.models import SeedTask, get_db_session

    with get_db_session() as session:
        task_db = session.query(SeedTask).filter(SeedTask.is_active is True).first()
        if not task_db:
            print("❌ No active tasks found in database")
            return
        task_id = task_db.task_id

    test_output_dir = Path.cwd() / "test_container_output" / task_id
    test_output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"🐳 Setting up container for task: {task_id}, output directory: {test_output_dir}",
    )

    async with task_claude(task_id, config, test_output_dir) as client:
        # Setup system prompt (this starts container and runs pre-task scripts)
        print("🔧 Starting container and running pre-task scripts...")
        await client.setup_system_prompt(
            "You are a helpful assistant for debugging containerized Claude.",
        )

        print(f"✅ Container fully ready: {client.container_id}")
        print()
        print("🔧 Debug authentication chain:")
        print("   which az                          # Check Azure CLI")
        print("   az --version                      # Azure CLI version")
        print("   ls -la /usr/local/bin/creds-script # Check credential script")
        print("   cat /workspace/.aws/config        # Check AWS config")
        print("   cat /workspace/.claude/settings.json  # Check Claude settings")
        print("   /usr/local/bin/claude --version   # Test Claude CLI")
        print(
            '   echo \'{"type": "user", "message": {"role": "user", "content": "hello"}}\' | /usr/local/bin/claude --input-format stream-json --output-format stream-json',
        )
        print("-" * 60)

        # Interactive mode - spawn shell with containerized claude in PATH
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", "-it", client.container_id, "/bin/bash"
        )
        await process.wait()

    print("🧹 Container cleaned up automatically. Check outputs: {test_output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
