#!/usr/bin/env python3
"""Test script for Turn.messages implementation with OpenAI Responses API."""

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class Turn:
    """A complete conversational turn in the PromptEngineer."""
    reasoning: list[Any]  # OpenAI reasoning from propose()
    proposed_prompt: str  # The prompt that was proposed
    grades: str  # Grading results from testing the prompt

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Convert turn into OpenAI API message sequence with function calling format."""
        msgs = []

        # First, add all reasoning items (filtered to remove response-only fields)
        for i, reasoning_item in enumerate(self.reasoning):
            print(f"Processing reasoning item {i}: type={type(reasoning_item)}, repr={reasoning_item!r}")
            
            if hasattr(reasoning_item, 'model_dump'):
                # OpenAI SDK object - convert to dict and filter out response-only fields
                msg_dict = reasoning_item.model_dump()
                print(f"Reasoning item {i} model_dump: {msg_dict}")
                
                # Filter out fields that are valid in response but not input (like 'status')
                if 'status' in msg_dict:
                    del msg_dict['status']
                    print(f"Reasoning item {i} after removing status: {msg_dict}")
                msgs.append(msg_dict)
            elif isinstance(reasoning_item, dict):
                # Already a dict - filter status if present
                filtered_dict = {k: v for k, v in reasoning_item.items() if k != 'status'}
                print(f"Reasoning item {i} is dict (filtered): {filtered_dict}")
                msgs.append(filtered_dict)
            else:
                # Unknown format - crash with details
                print(f"Unknown reasoning item format at index {i}: type={type(reasoning_item)}, repr={reasoning_item!r}")
                raise ValueError(f"Unknown reasoning item format: {type(reasoning_item)} - {reasoning_item!r}")

        # Add synthetic function call representing the submit_prompt call
        function_call_msg = {
            "type": "function_call",
            "call_id": f"call_{hash(self.proposed_prompt) % 1000000:06d}",  # Generate consistent ID
            "name": "submit_prompt", 
            "arguments": json.dumps({"prompt": self.proposed_prompt}),
        }
        print(f"Function call message: {function_call_msg}")
        msgs.append(function_call_msg)

        # Add function call output with grading results
        function_output_msg = {
            "type": "function_call_output",
            "call_id": function_call_msg["call_id"],  # Must match the call_id above
            "output": json.dumps({"grading_results": self.grades}),
        }
        print(f"Function output message: {function_output_msg}")
        msgs.append(function_output_msg)

        return msgs


def test_turn_messages():
    """Test Turn.messages with empty reasoning (real reasoning comes from API)."""
    
    # No synthetic reasoning - only real reasoning from API responses is valid
    # For this test, we'll use empty reasoning list
    
    # Create a test turn
    turn = Turn(
        reasoning=[],  # Empty - real reasoning items come from previous API responses
        proposed_prompt="You are a helpful coding assistant. Write clean, well-documented code.",
        grades="Overall Score: 8.5/10\nCorrectness: 9/10 - Code works correctly\nStyle: 8/10 - Good naming and structure",
    )
    
    # Generate messages
    messages = turn.messages
    print(f"\nGenerated {len(messages)} messages:")
    for i, msg in enumerate(messages):
        print(f"Message {i}: {json.dumps(msg, indent=2)}")
    
    # Test with OpenAI API
    client = OpenAI()
    
    # System message + turn messages
    full_input = [{"role": "system", "content": "You are a prompt engineer. Analyze the previous turn and improve the prompt."}, *messages]
    
    print(f"\nFull API input ({len(full_input)} items):")
    for i, item in enumerate(full_input):
        print(f"Input {i}: {json.dumps(item, indent=2)}")
    
    try:
        print("\nMaking OpenAI Responses API call...")
        response = client.responses.create(
            model="o3",
            input=full_input,
        )
        
        print("API call successful!")
        print(f"Response: {response}")
        
        # Extract the response content
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                if hasattr(item, 'type'):
                    print(f"Output item type: {item.type}")
                    if item.type == 'message' and hasattr(item, 'content'):
                        print(f"Message content: {item.content}")
        
    except Exception as e:
        print(f"API call failed: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        raise
    
    return True


if __name__ == "__main__":
    success = test_turn_messages()
    if success:
        print("\n✅ Turn.messages implementation works correctly!")
    else:
        print("\n❌ Turn.messages implementation has issues")