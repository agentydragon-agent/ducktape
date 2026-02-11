---
title: Investigation Setup
description: Set up structured investigations
variables:
  - investigation_id
  - title
  - goal
  - initial_evidence
  - methodology
  - timestamp
category: Investigation
---

# Investigation Setup

**Investigation ID**: {investigation_id}
**Title**: {title}
**Started**: {timestamp}

## Goal

{goal}

## Initial Evidence

{initial_evidence}

## Methodology

{methodology}

## Investigation Framework

### 1. Define Scope

- Clear boundaries of what to investigate
- What's explicitly out of scope
- Success criteria for the investigation
- Time and resource constraints

### 2. Evidence Collection

- **Primary sources**: Direct observations, logs, code
- **Secondary sources**: Documentation, comments, issues
- **Interviews**: Stakeholder perspectives
- **Experiments**: Reproducible tests

### 3. Analysis Techniques

- **Timeline reconstruction**: When did events occur?
- **Causal analysis**: What led to what?
- **Pattern recognition**: Are there recurring themes?
- **Anomaly detection**: What stands out as unusual?

### 4. Documentation Standards

- Record all evidence with timestamps
- Link claims to supporting evidence
- Note confidence levels for findings
- Track open questions and unknowns

### 5. Validation Process

- Cross-reference multiple sources
- Test hypotheses with experiments
- Seek contradictory evidence
- Peer review findings

## Evidence Format

```markdown
### [Timestamp] Evidence Type
- **Source**: Where this came from
- **Content**: What was found
- **Relevance**: How it relates to the goal
- **Confidence**: High/Medium/Low
- **Notes**: Additional context
```

## Investigation Checklist

- [ ] Scope clearly defined
- [ ] Initial evidence catalogued
- [ ] Investigation plan created
- [ ] Evidence gathering in progress
- [ ] Analysis completed
- [ ] Findings documented
- [ ] Conclusions validated
- [ ] Report finalized

## Common Investigation Pitfalls

- **Confirmation bias**: Only looking for supporting evidence
- **Incomplete data**: Drawing conclusions from partial information
- **Correlation/causation**: Assuming relationships without proof
- **Missing context**: Not understanding the full picture
- **Anchoring**: Over-weighting initial findings
