---
title: Metadata Validation
description: Validate metadata structure and content
variables:
  - file_path
  - expected_version
  - validation_rules
  - timestamp
category: Validation
---

# Metadata Validation

**File**: {file_path}
**Expected Version**: {expected_version}
**Validation Time**: {timestamp}

## Validation Rules

{validation_rules}

## Validation Protocol

### 1. Structure Validation

- Check file exists and is readable
- Verify file format (JSON, YAML, etc.)
- Validate against schema if available
- Check required fields are present

### 2. Content Validation

- Verify data types match expectations
- Check value ranges and constraints
- Validate references and relationships
- Ensure consistency across fields

### 3. Version Compatibility

- Check metadata version field
- Verify compatibility with expected version
- Handle version migration if needed
- Document any compatibility issues

### 4. Business Logic Validation

- Apply domain-specific rules
- Check cross-field dependencies
- Validate against external systems
- Ensure data makes semantic sense

### 5. Error Reporting

- Clear, actionable error messages
- Include path to problematic data
- Suggest fixes where possible
- Categorize errors by severity

## Common Metadata Issues

### Structure Problems

- Missing required fields
- Extra unexpected fields
- Wrong data types
- Malformed syntax

### Content Problems

- Invalid enum values
- Out-of-range numbers
- Broken references
- Inconsistent data

### Version Problems

- Version mismatch
- Missing version field
- Incompatible changes
- Migration failures

## Validation Output Format

```json
{{
  "valid": true/false,
  "version": "detected_version",
  "errors": [
    {{
      "path": "field.subfield[0]",
      "error": "validation error description",
      "severity": "error|warning|info",
      "suggestion": "how to fix"
    }}
  ],
  "warnings": [],
  "info": []
}}
```

## Best Practices

- Validate early and often
- Provide helpful error messages
- Support graceful degradation
- Log validation results
- Monitor validation failures
