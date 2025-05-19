# Gatelet

Service that lets LLMs access real-time and historical information relevant to the user, providing a browsable interface focused on Home Assistant integration.

### Core Components

1. **Server** - FastAPI-based web service that:
   - Receives and stores webhooks in PostgreSQL
   - Provides browsable interface optimized for LLMs
   - Retrieves and presents Home Assistant data 
   - Offers multiple authentication methods
   - Includes admin interface for humans

2. **Reporter** - Python scripts that:
   - Send event data to the server
   - Can be installed on laptops and other devices

## Development Setup

## LLM-Friendly Design

Designed for current LLM constraints (as of May 2025), particularly OpenAI scheduled tasks with o3 model:

- Navigation entirely link-based (no forms, inputs, or JavaScript)
- Authentication via URL paths or challenge-response
- All functionality accessible via GET requests
- Self-describing interfaces guide LLMs on service usage

### OpenAI o3 Model Constraints

- Can execute Python code but cannot access URLs computed in Python
- Can only navigate to URLs explicitly given by users or links from pages
- Cannot use cookies or maintain browser state between page loads
- Cannot execute JavaScript or submit forms

## Authentication Methods

Gatelet supports multiple authentication methods:

1. **Key in Path** - Simple authentication by including key in URL path
   - Usage model: User provides direct URL with embedded key (http://server/k/SECRET_KEY/)
   - Example: `/k/{key}/` 

2. **Challenge-Response** - Secure authentication using nonce challenges
   - Usage model: User provides base URL and secret key separately
   - LLM visits base URL, receives challenge, computes answer with Python
   - Server presents multiple link options (no URL computation needed)
   - LLM selects correct link from options based on computation
   - Incorrect selection invalidates the challenge
   - Success grants session with time-limited links

3. **Human Admin Authentication** - Standard username/password for human administrators
   - Uses cookies for session management
   - Provides access to logs, session management, and key administration

## Authentication and Session Terms

- **Pre-Shared Key (PSK)**: Secret value known to both server and LLM, never transmitted directly
- **Challenge**: Unique problem requiring PSK to solve, regenerated for each authentication attempt
- **Nonce**: Single-use random value ensuring challenges can't be replayed
  - Includes embedded timestamp to ensure freshness
  - Server tracks used nonces to prevent replay attacks
  - Server rejects nonces older than a configured time window
- **Session**: Authenticated period allowing access to protected resources
  - **Session Token**: Unique identifier embedded in page links
  - **Session Extension**: Every link clicked extends session by 5 minutes
  - **Session Duration Cap**: Maximum 1-hour lifetime even with continuous use
  - **Session Expiration**: Occurs after 5 minutes of inactivity

## Features

### Webhooks
- Receive and store webhooks from various sources
- View webhook history with pagination
- Optional encryption for sensitive data

### Home Assistant Integration
- Current state of configured entities
- Historical state changes for discrete entities
- Trend data for continuous sensors (temperature, humidity, etc.)

### Session Management
- Challenge-based authentication for LLMs
- Time-limited tokens with automatic extension
- Human admin interface for viewing sessions, managing keys, and monitoring logs

## Implementation Plan

The project will be implemented in phases:

1. **Phase 1**: Webhooks with Key-in-Path Authentication
   - Create package structure
   - Implement basic webhook receiving and storage
   - Implement key-in-path authentication

2. **Phase 2**: Challenge-Response Authentication
   - Design challenge-response authentication mechanism
   - Implement session management for LLMs
   - Add time-limited tokens with extension mechanism

3. **Phase 3**: Home Assistant Integration
   - Add Home Assistant API client
   - Create entity state display
   - Implement history views for different entity types

4. **Phase 4**: Human Admin Interface
   - Add human authentication
   - Create admin dashboard
   - Implement key management

## Current Status

The repository contains the initial FastAPI server with database models,
key-in-path authentication and webhook endpoints. Challenge-response login,
Home Assistant integration and the human admin interface are not yet
implemented. See `TODO.md` in the repository root for the remaining tasks.
