"""Tests for the Claude instruction optimizer."""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import json
from datetime import datetime
from typing import List, Dict, Any

from optimizer import (
    PatternSummarizer, PromptEngineer, ProcessingMode,
    create_openai_request, CodeResult, Grade, ScoreWithRationale, 
    Criterion, GradedCode, SeedTask, Turn, log_message_summary,
    log_openai_request_response, log_anthropic_request_event
)
from optimizer_config import OptimizerConfig
from docker_manager import DockerManager


class TestPatternSummarizer:
    """Test pattern summarization functionality."""
    
    @pytest.mark.asyncio
    async def test_summarize_patterns_basic(self, tmp_path):
        """Test basic pattern summarization."""
        summarizer = PatternSummarizer()
        
        # Create mock rollout results
        mock_results = [
            create_mock_graded_code(
                task="implement sorting",
                overall_score=7.5,
                axes={
                    "type_safety": ScoreWithRationale(score=8, rationale="Good typing"),
                    "robustness": ScoreWithRationale(score=6, rationale="Needs error handling")
                }
            )
        ]
        
        with patch("optimizer.OpenAI") as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client
            
            # Mock the API response
            mock_response = create_mock_pattern_response("Common issues found: lack of error handling")
            mock_client.responses.create.return_value = mock_response
            
            result = await summarizer.summarize_patterns(
                mock_results,
                tmp_path / "openai_log.jsonl"
            )
            
            assert result == "Common issues found: lack of error handling"
            assert mock_client.responses.create.called
            
    @pytest.mark.asyncio
    async def test_summarize_patterns_multiple_tasks(self, tmp_path):
        """Test pattern summarization with multiple tasks."""
        summarizer = PatternSummarizer()
        
        mock_results = [
            create_mock_graded_code("task1", 8.0, {"type_safety": ScoreWithRationale(score=9, rationale="Excellent")}),
            create_mock_graded_code("task2", 5.0, {"type_safety": ScoreWithRationale(score=4, rationale="Poor")}),
            create_mock_graded_code("task3", 6.5, {"type_safety": ScoreWithRationale(score=7, rationale="Good")}),
        ]
        
        with patch("optimizer.OpenAI") as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client
            
            mock_response = create_mock_pattern_response("Mixed results across tasks")
            mock_client.responses.create.return_value = mock_response
            
            result = await summarizer.summarize_patterns(mock_results, tmp_path / "log.jsonl")
            
            # Verify the call included all tasks
            call_args = mock_client.responses.create.call_args
            assert call_args is not None
            request_data = call_args[1] if call_args[1] else call_args[0]
            assert "Task 1:" in str(request_data)
            assert "Task 2:" in str(request_data)
            assert "Task 3:" in str(request_data)


class TestPromptEngineer:
    """Test prompt engineering conversation management."""
    
    def test_initialization_full_rollouts(self):
        """Test PromptEngineer initialization with full rollouts mode."""
        engineer = PromptEngineer(ProcessingMode.FULL_ROLLOUTS)
        
        assert len(engineer._turns) == 0
        assert engineer._processing_mode == ProcessingMode.FULL_ROLLOUTS
        assert "prompt engineer" in engineer._system_message["content"]
        assert "analyze rollouts from coding tasks" in engineer._system_message["content"]
        
    def test_initialization_summary_mode(self):
        """Test PromptEngineer initialization with summary mode."""
        engineer = PromptEngineer(ProcessingMode.SUMMARY)
        
        assert engineer._processing_mode == ProcessingMode.SUMMARY
        assert "pattern summaries and insights" in engineer._system_message["content"]
    
    def test_context_trimming(self):
        """Test that context is trimmed when exceeding token limit."""
        engineer = PromptEngineer()
        
        # Add many turns to exceed token limit
        for i in range(10):
            engineer.add_result(
                reasoning=[create_mock_reasoning(f"Reasoning {i}")],
                function_call_message=create_mock_function_call(f"prompt_{i}"),
                proposed_prompt=f"System prompt version {i}" * 1000,  # Long prompt
                grades=f"Grade results {i}" * 1000  # Long grades
            )
        
        # Force trimming with low token limit
        engineer._trim_context_if_needed(max_tokens=1000)
        
        # Should keep only last 2 turns
        assert len(engineer._turns) == 2
        
    def test_build_grades_message(self):
        """Test building grades message from rollout results."""
        engineer = PromptEngineer()
        
        mock_results = [
            create_mock_graded_code(
                "implement API client",
                7.0,
                {"architecture": ScoreWithRationale(score=8, rationale="Clean separation")}
            ),
            create_mock_graded_code(
                "build parser",
                9.0,
                {"correctness": ScoreWithRationale(score=10, rationale="Perfect implementation")}
            )
        ]
        
        message = engineer.build_grades_message(mock_results)
        
        assert "testing the current system prompt on 2 coding tasks" in message
        assert "implement API client" in message
        assert "build parser" in message
        assert "Overall Grade: 7.0" in message
        assert "Overall Grade: 9.0" in message
        
    @pytest.mark.asyncio
    async def test_propose_prompt(self, tmp_path):
        """Test prompt proposal generation."""
        engineer = PromptEngineer()
        
        # Add initial context
        mock_results = [create_mock_graded_code("test task", 8.0, {})]
        grades_message = engineer.build_grades_message(mock_results)
        engineer._turns.append(Turn(
            reasoning=[],
            function_call_message=create_mock_function_call("initial"),
            proposed_prompt="Initial prompt",
            grades=grades_message
        ))
        
        with patch("optimizer.OpenAI") as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client
            
            # Mock response with reasoning and function call
            mock_response = Mock()
            mock_response.output = [
                create_mock_reasoning("Analyzing the results..."),
                create_mock_function_call_item("submit_prompt", {"prompt": "Improved system prompt"})
            ]
            mock_client.responses.create.return_value = mock_response
            
            reasoning, function_call, prompt = await engineer.propose_prompt(tmp_path / "log.jsonl")
            
            assert len(reasoning) == 1
            assert prompt == "Improved system prompt"
            assert function_call.name == "submit_prompt"


class TestOptimizerConfig:
    """Test configuration management."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = OptimizerConfig()
        
        assert config.openai_model == "o3"
        assert config.reasoning_effort == "high"
        assert config.bash_timeout_ms == 10000
        assert config.max_parallel_rollouts == 8
        assert "__pycache__" in config.exclude_dirs
        assert ".pyc" in config.exclude_extensions
        
    def test_custom_config(self):
        """Test custom configuration values."""
        config = OptimizerConfig(
            openai_model="gpt-4",
            max_parallel_rollouts=16,
            truncation_length=100
        )
        
        assert config.openai_model == "gpt-4"
        assert config.max_parallel_rollouts == 16
        assert config.truncation_length == 100
        
    def test_config_validation(self):
        """Test configuration validation."""
        with pytest.raises(ValueError):
            # Extra fields not allowed
            OptimizerConfig(invalid_field="value")


class TestDockerManager:
    """Test Docker management functionality."""
    
    def test_docker_manager_init(self):
        """Test DockerManager initialization."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            manager = DockerManager()
            assert manager.docker_path == "/usr/bin/docker"
            assert not manager.is_setup
            
    def test_docker_not_found(self):
        """Test error when Docker is not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Docker is required"):
                DockerManager()
                
    def test_setup_wrapper(self, tmp_path):
        """Test Docker wrapper setup."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            manager = DockerManager()
            
            # Create mock wrapper script
            wrapper_source = tmp_path / "docker_claude_wrapper.sh"
            wrapper_source.write_text("#!/bin/bash\necho 'wrapper'")
            
            # Setup wrapper
            wrapper_path = manager.setup_wrapper(tmp_path, wrapper_source)
            
            assert wrapper_path.exists()
            assert wrapper_path.name == "claude"
            assert manager.is_setup
            assert str(tmp_path / "bin") in os.environ["PATH"]
            
    def test_cleanup(self, tmp_path):
        """Test PATH restoration on cleanup."""
        original_path = os.environ.get("PATH", "")
        
        with patch("shutil.which", return_value="/usr/bin/docker"):
            manager = DockerManager()
            
            wrapper_source = tmp_path / "wrapper.sh"
            wrapper_source.write_text("#!/bin/bash")
            
            manager.setup_wrapper(tmp_path, wrapper_source)
            modified_path = os.environ["PATH"]
            
            manager.cleanup()
            
            assert os.environ["PATH"] == original_path
            assert not manager.is_setup
            assert modified_path != original_path


class TestHelperFunctions:
    """Test helper functions."""
    
    def test_create_openai_request(self):
        """Test OpenAI request creation."""
        request = create_openai_request(
            "o3",
            [{"role": "user", "content": "test"}],
            [{"type": "function", "name": "test_func"}],
            {"type": "auto"}
        )
        
        assert request["model"] == "o3"
        assert request["input"] == [{"role": "user", "content": "test"}]
        assert request["reasoning"]["effort"] == "high"
        
    def test_create_openai_request_custom_reasoning(self):
        """Test OpenAI request with custom reasoning effort."""
        request = create_openai_request(
            "o3",
            [],
            [],
            {"type": "none"},
            reasoning_effort="medium"
        )
        
        assert request["reasoning"]["effort"] == "medium"
        
    def test_log_openai_request_response(self, tmp_path):
        """Test OpenAI API logging."""
        log_path = tmp_path / "openai_log.jsonl"
        
        request = {"model": "o3", "input": []}
        response = Mock()
        response.model_dump.return_value = {"output": "test"}
        
        log_openai_request_response(log_path, request, response)
        
        # Verify log was written
        assert log_path.exists()
        with log_path.open() as f:
            log_entry = json.loads(f.readline())
            assert log_entry["request"] == request
            assert log_entry["response"]["output"] == "test"
            assert "timestamp" in log_entry
            
    def test_log_anthropic_request_event(self, tmp_path):
        """Test Anthropic API logging."""
        log_path = tmp_path / "anthropic_log.jsonl"
        
        request = {"prompt": "test", "options": {}}
        event = "test_event"
        
        log_anthropic_request_event(log_path, request, event)
        
        assert log_path.exists()
        with log_path.open() as f:
            log_entry = json.loads(f.readline())
            assert log_entry["request"] == request
            assert log_entry["event"] == "test_event"


class TestMessageLogging:
    """Test message logging functionality."""
    
    def test_log_system_message(self, caplog):
        """Test logging of system messages."""
        from optimizer import SystemMessage
        
        msg = SystemMessage(subtype="test_subtype", content="test")
        with patch("optimizer.logger") as mock_logger:
            log_message_summary(msg, agent_id=1)
            
            # Verify logger was called correctly
            mock_logger.bind.assert_called_with(agent_id=1, message_type="SystemMessage")
            
    def test_log_assistant_message_with_tools(self, caplog):
        """Test logging of assistant messages with tool usage."""
        from optimizer import AssistantMessage, TextBlock, ToolUseBlock
        
        msg = AssistantMessage(content=[
            TextBlock(text="Using tool"),
            ToolUseBlock(id="123", name="test_tool", input={"param": "value"})
        ])
        
        with patch("optimizer.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            log_message_summary(msg, agent_id=2)
            
            # Should log tool usage
            mock_logger.info.assert_called()
            call_args = [call[0][0] for call in mock_logger.info.call_args_list]
            assert "Tool usage" in call_args


# Helper functions for creating mock objects
def create_mock_graded_code(task: str, overall_score: float, axes: Dict[str, ScoreWithRationale]) -> GradedCode:
    """Create a mock GradedCode object for testing."""
    return GradedCode(
        code_result=CodeResult(
            task=task,
            agent_id=1,
            timestamp=datetime.utcnow().isoformat(),
            messages=[],
            files=[{"path": "test.py", "content": "# test code"}]
        ),
        grade=Grade(
            task=task,
            agent_id=1,
            axes=axes,
            overall_score=overall_score,
            overall_rationale="Test rationale",
            timestamp=datetime.utcnow().isoformat()
        )
    )


def create_mock_pattern_response(text: str):
    """Create a mock OpenAI response for pattern analysis."""
    from optimizer import ResponseOutputMessage, ResponseOutputText
    
    mock_response = Mock()
    mock_response.output = [
        ResponseOutputMessage(
            type="message",
            content=[
                ResponseOutputText(text=text)
            ]
        )
    ]
    return mock_response


def create_mock_reasoning(content: str):
    """Create mock reasoning item."""
    from optimizer import ResponseReasoningItem
    
    mock = Mock(spec=ResponseReasoningItem)
    mock.content = content
    mock.model_dump.return_value = {"content": content}
    return mock


def create_mock_function_call(prompt: str):
    """Create mock function call message."""
    from optimizer import ResponseFunctionToolCall
    
    mock = Mock(spec=ResponseFunctionToolCall)
    mock.name = "submit_prompt"
    mock.arguments = json.dumps({"prompt": prompt})
    mock.call_id = "call_123"
    mock.model_dump.return_value = {
        "name": "submit_prompt",
        "arguments": mock.arguments,
        "call_id": "call_123"
    }
    return mock


def create_mock_function_call_item(name: str, args: dict):
    """Create mock function call item."""
    from optimizer import ResponseFunctionToolCallItem
    
    mock = Mock(spec=ResponseFunctionToolCallItem)
    mock.type = "function_call"
    mock.name = name
    mock.arguments = json.dumps(args)
    mock.call_id = "call_456"
    return mock


# Fixtures
@pytest.fixture
def mock_openai_client():
    """Provide a mock OpenAI client."""
    with patch("optimizer.OpenAI") as mock:
        yield mock.return_value
        
        
@pytest.fixture
def mock_config():
    """Provide a test configuration."""
    return OptimizerConfig(
        max_parallel_rollouts=2,
        bash_timeout_ms=5000,
        truncation_length=50
    )