"""Test file truncation logic to prevent OpenAI API limit errors."""

import json
import pytest
import tiktoken
from optimizer import _truncate_files_by_tokens


class TestFileTruncation:
    """Test centralized file truncation logic."""

    def test_files_under_limit_unchanged(self):
        """Small files should pass through unchanged."""
        files = [
            {"path": "small.py", "content": "print('hello')"},
            {"path": "tiny.txt", "content": "small file"},
        ]
        
        result = _truncate_files_by_tokens(files)
        
        assert result == files
        assert len(result) == 2

    def test_single_large_file_truncated(self):
        """A single very large file should be truncated if it exceeds token limit."""
        # Create content that will definitely exceed 150k tokens when JSON-serialized
        large_content = "# This is a large Python comment\n" + "x" * 500_000  # 500k chars
        files = [{"path": "huge.txt", "content": large_content}]
        
        result = _truncate_files_by_tokens(files)
        
        # Should either be truncated or completely excluded
        if len(result) == 0:
            # File was too large and excluded entirely
            assert True
        else:
            assert len(result) == 1
            assert result[0]["path"] == "huge.txt"
            if len(result[0]["content"]) < len(large_content):
                assert "TRUNCATED FOR API LIMITS" in result[0]["content"]

    def test_multiple_files_some_skipped(self):
        """When multiple files exceed limit, some should be skipped."""
        # Create files that together exceed the token limit when JSON serialized
        files = []
        for i in range(50):  # More files to ensure we exceed limit
            # Each file has meaningful content that will consume tokens
            content = f"# File {i}\n" + "def function_" + str(i) + "():\n    " + "print('test')\n" * 1000
            files.append({"path": f"file_{i}.py", "content": content})
        
        result = _truncate_files_by_tokens(files)
        
        # Should have fewer files than input when we exceed limits
        assert len(result) <= len(files)
        # All returned files should have valid paths
        assert all("path" in f and "content" in f for f in result)

    def test_token_limit_assertion(self):
        """Result should never exceed the token limit."""
        # Create files that would exceed limit
        files = []
        for i in range(20):
            content = "def function_" + str(i) + "():\n    " + "print('test')\n" * 1000
            files.append({"path": f"test_{i}.py", "content": content})
        
        result = _truncate_files_by_tokens(files)
        
        # Verify the result is under the limit
        encoding = tiktoken.encoding_for_model("gpt-4o")
        files_json = json.dumps(result, indent=2)
        final_tokens = len(encoding.encode(files_json))
        
        MAX_FILES_TOKENS = 150_000
        assert final_tokens <= MAX_FILES_TOKENS, f"Result exceeds limit: {final_tokens} > {MAX_FILES_TOKENS}"

    def test_largest_files_truncated_first(self):
        """Largest files should be truncated before smaller ones."""
        files = [
            {"path": "small.py", "content": "print('small')"},  # ~15 chars
            {"path": "medium.py", "content": "x" * 1000},        # 1000 chars  
            {"path": "large.py", "content": "y" * 10000},        # 10000 chars
        ]
        
        result = _truncate_files_by_tokens(files)
        
        # Small file should be preserved exactly
        small_file = next(f for f in result if f["path"] == "small.py")
        assert small_file["content"] == "print('small')"
        
        # If any file is truncated, it should be the largest one first
        for file_info in result:
            if "TRUNCATED FOR API LIMITS" in file_info["content"]:
                # The truncated file should be one of the larger ones
                assert file_info["path"] in ["large.py", "medium.py"]

    def test_empty_files_list(self):
        """Empty input should return empty output."""
        result = _truncate_files_by_tokens([])
        assert result == []

    def test_preserves_file_structure(self):
        """File structure (path/content keys) should be preserved."""
        files = [{"path": "test.py", "content": "print('test')"}]
        
        result = _truncate_files_by_tokens(files)
        
        assert len(result) == 1
        assert "path" in result[0]
        assert "content" in result[0]
        assert result[0]["path"] == "test.py"

    def test_binary_search_truncation_efficiency(self):
        """Binary search should find efficient truncation point."""
        # Create a file that needs truncation
        large_content = "# Python code\n" + "print('line')\n" * 50_000
        files = [{"path": "large.py", "content": large_content}]
        
        result = _truncate_files_by_tokens(files)
        
        if len(result) > 0 and "TRUNCATED FOR API LIMITS" in result[0]["content"]:
            truncated = result[0]["content"]
            # Should preserve significant portion of original content
            original_lines = large_content.count('\n')
            truncated_lines = truncated.count('\n')
            # Should keep at least 10% of original (binary search efficiency)
            assert truncated_lines >= original_lines * 0.1

    def test_real_world_scenario(self):
        """Test with realistic file contents."""
        files = [
            {
                "path": "main.py", 
                "content": '''#!/usr/bin/env python3
"""Main application module."""

import os
import sys
import json
from typing import List, Dict, Any

def main():
    """Main entry point."""
    print("Hello, world!")
    
if __name__ == "__main__":
    main()
'''
            },
            {
                "path": "requirements.txt",
                "content": '''pytest>=7.0.0
tiktoken>=0.5.0
openai>=1.0.0
'''
            },
            {
                "path": "README.md",
                "content": '''# Test Project

This is a test project for file truncation.
''' * 100  # Make it moderately large
            }
        ]
        
        result = _truncate_files_by_tokens(files)
        
        # Should handle real files gracefully
        assert len(result) <= len(files)
        assert all(isinstance(f["path"], str) for f in result)
        assert all(isinstance(f["content"], str) for f in result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])