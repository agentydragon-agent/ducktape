"""Prompt improvement workflow components.

Agent-based alternative to GEPA's improvement operator. Uses lazy database
querying to scale to 10-50 examples (vs GEPA's 3-5) with lower context consumption.

Key components:
- token_budget_handler: Token budget enforcement with progressive warnings
- reminder_handler: Periodic reminders for improvement progress
- improve_agent: Main orchestrator workflow
"""
