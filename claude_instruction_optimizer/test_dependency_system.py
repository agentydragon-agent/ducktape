#!/usr/bin/env python3
"""Test script to demonstrate the generic dependency system."""

from dependency_manager import DependencyResolver, TaskDependencies, parse_task_dependencies

def main():
    """Test the dependency resolution system."""
    print("=== Generic Task Dependency System Demo ===\n")
    
    # Initialize resolver
    resolver = DependencyResolver()
    
    # Test different dependency specifications
    test_cases = [
        {
            "name": "Minimal task (just system tools)",
            "dependencies": ["minimal"]
        },
        {
            "name": "Rust-only development", 
            "dependencies": ["rust"]
        },
        {
            "name": "Python data science",
            "dependencies": ["data-science"]  # Uses alias
        },
        {
            "name": "Full-stack development",
            "dependencies": ["python-complete", "node", "ruby"]
        },
        {
            "name": "Multi-language project",
            "dependencies": ["python-data", "rust", "go"]
        },
        {
            "name": "Custom combination",
            "dependencies": ["python-core", "typescript"]
        }
    ]
    
    print("1. Dependency Resolution Examples:\n")
    
    for case in test_cases:
        task_deps = TaskDependencies(dependencies=case["dependencies"])
        image = resolver.resolve_dependencies(task_deps.dependencies)
        print(f"Task: {case['name']}")
        print(f"  Dependencies: {case['dependencies']}")
        print(f"  Resolved to: {image}")
        print()
    
    print("2. Available Dependencies by Layer:\n")
    available = resolver.get_available_dependencies()
    for layer, deps in available.items():
        print(f"{layer}:")
        print(f"  Provides: {', '.join(deps)}")
        print()
    
    print("3. Available Aliases:\n")
    aliases = resolver.get_available_aliases()
    for alias, expansions in aliases.items():
        print(f"{alias}: {expansions}")
    print()
    
    # Simulate task analysis
    all_tasks = [TaskDependencies(dependencies=case["dependencies"]) for case in test_cases]
    
    print("4. Cross-Task Analysis:\n")
    analysis = resolver.analyze_dependencies_across_tasks(all_tasks)
    
    print(f"Most common image: {analysis['most_common_image']}")
    print(f"Most common dependency: {analysis['most_common_dependency']}")
    print("\nImage usage:")
    for image, count in analysis['image_priority']:
        print(f"  {image}: {count} tasks")
    print("\nDependency usage:")
    for dep, count in analysis['dependency_priority']:
        print(f"  {dep}: {count} tasks")
    
    print("\n5. YAML Task Format Examples:\n")
    
    example_tasks = [
        {
            "id": "rust_trading_system",
            "prompt": "Build a high-frequency trading system in Rust...",
            "dependencies": ["rust"],
            "git_repos": {},
            "internet_needed": False,
            "allowed_tools": ["Read", "Write", "Edit", "Bash"]
        },
        {
            "id": "python_ml_pipeline", 
            "prompt": "Create a machine learning data pipeline...",
            "dependencies": "data-science",  # Single string format
            "git_repos": {},
            "internet_needed": False,
            "allowed_tools": ["Read", "Write", "Edit", "Bash"]
        },
        {
            "id": "web_app_fullstack",
            "prompt": "Build a React frontend with FastAPI backend...", 
            "dependencies": ["python-core", "node"],
            "git_repos": {},
            "internet_needed": True,
            "allowed_tools": ["Read", "Write", "Edit", "Bash"]
        }
    ]
    
    for task in example_tasks:
        deps = parse_task_dependencies(task)
        image = resolver.resolve_dependencies(deps.dependencies)
        print(f"Task: {task['id']}")
        print(f"  Dependencies: {deps.dependencies}")
        print(f"  Docker image: {image}")
        print()

if __name__ == "__main__":
    main()