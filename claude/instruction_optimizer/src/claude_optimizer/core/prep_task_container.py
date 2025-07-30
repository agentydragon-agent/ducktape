#!/usr/bin/env python3
"""Sets up a container for a specific task and drops you into an interactive shell.

Usage:
    python prep_task_container.py [task_id]

Inside the container shell, you can run:
    claude -p "check whether you're on a real machine or in a container"
"""

import asyncio
import json
from pathlib import Path

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.core.containerized_claude import task_claude
from claude_optimizer.database.models import SeedTask, get_db_session, init_database


async def main():
    """Interactive container setup for testing."""
    config = OptimizerConfig.from_file()

    init_database()

    with get_db_session() as session:
        task_db = session.query(SeedTask).filter(SeedTask.is_active is True).first()
        task_id = task_db.task_id
        task = task_db.prompt

    test_output_dir = Path.cwd() / "test_container_output" / task_id
    test_output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"🐳 Setting up container for task: {task_id}, output directory: {test_output_dir}",
    )

    async with task_claude(task_id, config, test_output_dir, task) as client:
        # Setup system prompt (this starts container and runs pre-task scripts)
        print("🔧 Starting container and running pre-task scripts...")
        await client.setup_system_prompt("You are a helpful assistant.")

        print(f"✅ Container ready: {client.container_id}")
        print("   cat /workspace/.claude/settings.json  # Check Claude settings")
        print("   /usr/local/bin/claude --version   # Test Claude CLI")
        msg = {"type": "user", "message": {"role": "user", "content": "hello"}}
        print(
            f"   echo {json.dumps(msg)!r} | /usr/local/bin/claude --input-format stream-json --output-format stream-json",
        )
        print("-" * 60)

        # Interactive mode - spawn shell with containerized claude in PATH
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", "-it", client.container_id, "/bin/bash",
        )
        await process.wait()

    print("🧹 Container cleaned up automatically. Check outputs: {test_output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
