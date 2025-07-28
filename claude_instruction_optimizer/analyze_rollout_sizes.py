#!/usr/bin/env python3
"""
Analyze rollout sizes from inner_agent_log.jsonl to estimate context capacity.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any
import tiktoken

def analyze_rollout_logs(log_path: Path) -> Dict[str, Any]:
    """Analyze rollout logs to estimate token usage."""
    
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return {}
    
    # Initialize tiktoken encoder (using gpt-4o model for consistency)
    enc = tiktoken.encoding_for_model("gpt-4o")
    
    rollouts = []
    skipped_lines = 0
    
    with open(log_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                rollout = json.loads(line.strip())
                rollouts.append(rollout)
            except json.JSONDecodeError as e:
                skipped_lines += 1
                print(f"Warning: Skipped malformed JSON line {line_num}: {e}")
                continue
    
    if skipped_lines > 0:
        print(f"Warning: Skipped {skipped_lines} malformed lines in log file")
    
    if not rollouts:
        print("No rollouts found in log file")
        return {}
    
    # Analyze each rollout
    rollout_stats = []
    
    for rollout in rollouts:
        # Extract key fields
        task = rollout.get('task', '')
        code = rollout.get('code', '')
        messages = rollout.get('messages', [])
        
        # Calculate token counts
        task_tokens = len(enc.encode(task))
        code_tokens = len(enc.encode(code))
        
        # Messages token count (serialized)
        messages_str = json.dumps(messages)
        messages_tokens = len(enc.encode(messages_str))
        
        # Total rollout size
        total_tokens = task_tokens + code_tokens + messages_tokens
        
        rollout_stats.append({
            'task_tokens': task_tokens,
            'code_tokens': code_tokens, 
            'messages_tokens': messages_tokens,
            'total_tokens': total_tokens,
            'task_id': rollout.get('agent_id', 'unknown'),
            'iteration': rollout.get('iteration', 1)
        })
    
    # Calculate statistics
    total_tokens_list = [r['total_tokens'] for r in rollout_stats]
    code_tokens_list = [r['code_tokens'] for r in rollout_stats]
    messages_tokens_list = [r['messages_tokens'] for r in rollout_stats]
    
    stats = {
        'total_rollouts': len(rollout_stats),
        'token_stats': {
            'total_tokens': {
                'min': min(total_tokens_list),
                'max': max(total_tokens_list),
                'avg': sum(total_tokens_list) / len(total_tokens_list),
                'median': sorted(total_tokens_list)[len(total_tokens_list)//2]
            },
            'code_tokens': {
                'min': min(code_tokens_list),
                'max': max(code_tokens_list),
                'avg': sum(code_tokens_list) / len(code_tokens_list),
                'median': sorted(code_tokens_list)[len(code_tokens_list)//2]
            },
            'messages_tokens': {
                'min': min(messages_tokens_list),
                'max': max(messages_tokens_list),
                'avg': sum(messages_tokens_list) / len(messages_tokens_list),
                'median': sorted(messages_tokens_list)[len(messages_tokens_list)//2]
            }
        },
        'rollout_details': rollout_stats
    }
    
    return stats

def estimate_context_capacity(stats: Dict[str, Any], context_limit: int = 200000) -> Dict[str, Any]:
    """Estimate how many rollouts can fit in context."""
    
    if not stats:
        return {}
    
    avg_rollout_size = stats['token_stats']['total_tokens']['avg']
    max_rollout_size = stats['token_stats']['total_tokens']['max']
    median_rollout_size = stats['token_stats']['total_tokens']['median']
    
    # Estimate capacity (leaving room for system message and prompt engineering overhead)
    overhead_tokens = 5000  # Conservative estimate for system message + PE overhead
    usable_context = context_limit - overhead_tokens
    
    capacity_estimates = {
        'context_limit': context_limit,
        'overhead_tokens': overhead_tokens,
        'usable_context': usable_context,
        'avg_rollout_size': avg_rollout_size,
        'max_rollout_size': max_rollout_size,
        'median_rollout_size': median_rollout_size,
        'estimated_capacity': {
            'by_average': int(usable_context // avg_rollout_size),
            'by_median': int(usable_context // median_rollout_size),
            'conservative_max': int(usable_context // max_rollout_size)
        }
    }
    
    return capacity_estimates

def main():
    if len(sys.argv) > 1:
        log_path = Path(sys.argv[1])
    else:
        # Find most recent log
        output_dirs = list(Path("agent_output").glob("*"))
        if not output_dirs:
            print("No agent_output directories found")
            return
        
        latest_dir = max(output_dirs, key=lambda p: p.name)
        log_path = latest_dir / "inner_agent_log.jsonl"
    
    print(f"Analyzing rollouts from: {log_path}")
    print("=" * 60)
    
    # Analyze rollouts
    stats = analyze_rollout_logs(log_path)
    
    if not stats:
        return
    
    # Print rollout analysis
    print(f"Total rollouts analyzed: {stats['total_rollouts']}")
    print()
    print("Token usage per rollout:")
    print(f"  Total tokens - Min: {stats['token_stats']['total_tokens']['min']:,}, "
          f"Max: {stats['token_stats']['total_tokens']['max']:,}, "
          f"Avg: {stats['token_stats']['total_tokens']['avg']:,.0f}, "
          f"Median: {stats['token_stats']['total_tokens']['median']:,.0f}")
    print(f"  Code tokens - Min: {stats['token_stats']['code_tokens']['min']:,}, "
          f"Max: {stats['token_stats']['code_tokens']['max']:,}, "
          f"Avg: {stats['token_stats']['code_tokens']['avg']:,.0f}")
    print(f"  Messages tokens - Min: {stats['token_stats']['messages_tokens']['min']:,}, "
          f"Max: {stats['token_stats']['messages_tokens']['max']:,}, "
          f"Avg: {stats['token_stats']['messages_tokens']['avg']:,.0f}")
    print()
    
    # Estimate context capacity for different limits
    for context_limit in [128000, 200000, 1000000]:  # 128k, 200k, 1M tokens
        capacity = estimate_context_capacity(stats, context_limit)
        print(f"Context limit: {context_limit:,} tokens")
        print(f"  Usable context: {capacity['usable_context']:,} tokens")
        print(f"  Estimated capacity:")
        print(f"    By average rollout size: {capacity['estimated_capacity']['by_average']} rollouts")
        print(f"    By median rollout size: {capacity['estimated_capacity']['by_median']} rollouts") 
        print(f"    Conservative (max size): {capacity['estimated_capacity']['conservative_max']} rollouts")
        print()

if __name__ == "__main__":
    main()