#!/usr/bin/env python3
"""
Specific behavioral requirements for Claude code generation evaluation.

Uses template system to eliminate duplication - each requirement specifies only its unique elements.
"""

from .requirement_templates import RequirementSpec, create_behavioral_requirement

# #1: Exception Handling - Prevents exception-swallowing anti-patterns
EXCEPTION_HANDLING_SPEC = RequirementSpec(
    id="exception_handling",
    name="Exception Handling",
    description="Prevents exception-swallowing anti-patterns like broad exception catches and silent failures",
    evaluation_criteria="Code should catch specific exceptions only and let programming errors crash loudly",
    problematic_patterns=[
        "Broad exception catches (`except Exception:`, `except:`) that hide programming errors",
        "Silent exception swallowing (pass, continue, return default without logging)",
        "Fallback returns that mask actual bugs (return None, return [], etc.)",
        "Test code that catches exceptions and doesn't fail the test"
    ],
    good_patterns=[
        "Specific exception catches with clear handling logic",
        "Let programming errors crash loudly to expose bugs",
        "Proper logging when catching expected exceptions",
        "Clear error recovery with business logic justification"
    ],
    problem_fields={
        "pattern": "The problematic pattern found",
        "line_context": "Relevant code snippet", 
        "reason": "Why this is problematic"
    }
)

# #2: Configuration Hierarchy - Only one level sets defaults
CONFIG_HIERARCHY_SPEC = RequirementSpec(
    id="config_hierarchy", 
    name="Configuration Hierarchy",
    description="Ensures only ONE level in class hierarchies sets default values, preferably at outermost user level or nowhere",
    evaluation_criteria="Defaults should be set only at the outermost user-facing level or in a separate config class, not scattered across hierarchy",
    problematic_patterns=[
        "**Multiple levels setting defaults**: Different classes in inheritance hierarchy setting default values for same/similar parameters",
        "**Scattered defaults**: Default values defined in multiple __init__ methods across the hierarchy",
        "**Implicit defaults**: Hard-coded values deep in the hierarchy that should be configurable", 
        "**Competing defaults**: Parent and child classes setting different defaults for related parameters"
    ],
    good_patterns=[
        "Defaults set ONLY at outermost user-facing level",
        "OR defaults set in separate configuration class/dataclass",
        "OR no defaults at all (explicit is better than implicit)",
        "Clear single source of truth for configuration values"
    ],
    problem_fields={
        "pattern": "The problematic pattern found",
        "classes_involved": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Classes that exhibit this problem"
        },
        "reason": "Why this is problematic",
        "suggestion": "How to fix this issue"
    },
    extra_response_fields={
        "default_locations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string", "description": "Name of class setting defaults"},
                    "parameter": {"type": "string", "description": "Parameter name with default"},
                    "default_value": {"type": "string", "description": "The default value set"}
                },
                "required": ["class_name", "parameter", "default_value"],
                "additionalProperties": False
            },
            "description": "All locations where default values are set"
        }
    }
)

# #3: Nullable Types - Only nullable if null value is sane  
NULLABLE_TYPES_SPEC = RequirementSpec(
    id="nullable_types",
    name="Nullable Types", 
    description="Ensures types are nullable if and only if the null value is sane - prevents meaningless Optional types",
    evaluation_criteria="Parameters should be Optional only when None has clear semantic meaning, not for programming convenience",
    problematic_patterns=[
        "**Unnecessary Optional**: Parameters marked Optional[T] when None doesn't make semantic sense for the function to work",
        "**Missing Optional**: Parameters that should be nullable because None is a valid/meaningful state, but are typed as non-nullable",
        "**Unclear null meaning**: Optional types where it's unclear what None represents or how the function handles it"
    ],
    good_patterns=[
        "Required parameters that must have values are non-nullable (str, int, List[str], etc.)",
        "Parameters where None has clear semantic meaning are Optional (Optional[str] for \"no error message\", Optional[Callable] for \"no callback\")",
        "Clear distinction between \"missing value\" (None) vs \"empty value\" (\"\", [], {})",
        "**Key test**: For each Optional parameter, ask \"Is None a sane value that the function can meaningfully handle?\" If not, it shouldn't be Optional"
    ],
    problem_fields={
        "parameter_name": "Name of parameter with problem",
        "function_or_class": "Function/class where problem occurs",
        "issue_type": "Type of nullable issue found",
        "current_type": "Current type annotation",
        "reason": "Why this is problematic",
        "suggested_fix": "How to fix this issue"
    },
    extra_response_fields={
        "good_examples": {
            "type": "array",
            "items": {
                "type": "object", 
                "properties": {
                    "parameter_name": {"type": "string"},
                    "type_annotation": {"type": "string"},
                    "reason": {"type": "string", "description": "Why this is good nullable usage"}
                },
                "required": ["parameter_name", "type_annotation", "reason"],
                "additionalProperties": False
            },
            "description": "Examples of good nullable type usage in the code"
        }
    }
)

# #4: Enum Types - Use proper enums instead of strings
ENUM_TYPES_SPEC = RequirementSpec(
    id="enum_types",
    name="Enum Types",
    description="Ensures enumerations use proper enum types instead of string literals or constants",
    evaluation_criteria="Fixed sets of values should be defined as Python enums, not string literals or magic constants",
    problematic_patterns=[
        "**String literal enums**: Using raw strings like \"active\", \"inactive\", \"pending\" instead of enum values",
        "**Magic constants**: Hard-coded string/int constants that represent fixed choices", 
        "**Inconsistent values**: Same conceptual enum represented differently in different places",
        "**Missing enum imports**: Not importing enum module when enums would be appropriate"
    ],
    good_patterns=[
        "Using Python's enum.Enum for fixed sets of values",
        "Consistent enum usage across related functions",
        "Type hints that reference enum classes",
        "Clear enum value names that are self-documenting"
    ],
    problem_fields={
        "location": "Where the problem occurs",
        "issue_type": "Type of enum issue found",
        "current_usage": "Current problematic usage",
        "reason": "Why this is problematic",
        "suggested_fix": "How to fix with proper enum"
    },
    extra_response_fields={
        "good_examples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "enum_name": {"type": "string"},
                    "usage_context": {"type": "string"},
                    "reason": {"type": "string", "description": "Why this is good enum usage"}
                },
                "required": ["enum_name", "usage_context", "reason"],
                "additionalProperties": False
            },
            "description": "Examples of good enum usage in the code"
        }
    }
)

# #5: No Barrel Re-exports - Direct imports only
NO_BARREL_REEXPORTS_SPEC = RequirementSpec(
    id="no_barrel_reexports",
    name="No Barrel Re-exports",
    description="Prevents barrel re-export patterns in __init__.py files unless justified for library API convenience",
    evaluation_criteria="__init__.py files should NOT re-export symbols from submodules unless this is a library for wide reuse with clear user convenience justification",
    problematic_patterns=[
        "**Barrel re-exports**: __init__.py files that import from submodules and re-export via __all__",
        "**Convenience imports**: from .module import Class then putting Class in __all__",
        "**API flattening**: Making internal module structure invisible through re-exports",
        "**Lazy organization**: Using __init__.py re-exports instead of proper direct imports"
    ],
    good_patterns=[
        "Empty __init__.py files or files with just docstrings",
        "Direct imports: from package.module import SpecificClass", 
        "Clear module boundaries that users import from directly",
        "**ONLY ACCEPTABLE if BOTH conditions met**: (1) This is a library for wide reuse by external users, (2) Clear comment explaining user convenience and API stability rationale"
    ],
    problem_fields={
        "file_path": "Path to problematic __init__.py",
        "reexported_items": "List of items being re-exported",
        "source_modules": "Source modules being imported from",
        "reason": "Why this barrel re-export is problematic",
        "suggested_fix": "How to fix with direct imports"
    },
    extra_response_fields={
        "justification_check": {
            "type": "object",
            "properties": {
                "is_library_for_reuse": {"type": "boolean", "description": "Is this a library intended for wide external reuse?"},
                "has_convenience_comment": {"type": "boolean", "description": "Does it have a comment explaining user convenience?"},
                "acceptable_reexport": {"type": "boolean", "description": "Is this an acceptable library convenience re-export?"}
            },
            "required": ["is_library_for_reuse", "has_convenience_comment", "acceptable_reexport"],
            "additionalProperties": False
        }
    }
)

# #6: Complete Migration - When user requests X→Y migration, leave only Y
NO_COMPATIBILITY_SPEC = RequirementSpec(
    id="no_compatibility",
    name="Complete Migration",
    description="When user explicitly requests migration/replacement from system X to system Y, implement ONLY system Y without compatibility layers",
    evaluation_criteria="If user says 'switch from X to Y', 'migrate from X to Y', 'replace X with Y', result must be pure Y, NOT 'try: Y; except: X'. Does NOT apply to 'add support for Y'",
    problematic_patterns=[
        "**Defensive fallbacks after migration request**: Using try/except to fall back to old system when user said to migrate/switch/replace",
        "**Compatibility wrappers after replacement request**: Keeping old API alongside new one when user asked to replace X with Y",
        "**Migration hesitancy**: Comments like 'keep old X for compatibility' when user explicitly said to migrate to Y",
        "**Dual implementations after switch request**: Both old and new systems active when user said 'switch from X to Y'"
    ],
    good_patterns=[
        "When user says 'migrate from X to Y', implement pure Y with no X fallbacks",
        "When user says 'switch from X to Y', completely replace X with Y",
        "When user says 'replace X with Y', remove X entirely and use only Y",
        "**Non-migration context**: When user says 'add support for Y', it's OK to have both X and Y coexist"
    ],
    problem_fields={
        "migration_context": "What the user explicitly requested (e.g., 'migrate from X to Y')",
        "old_system_remnants": "Where old system X still exists after migration request",
        "new_system_location": "Where new system Y is implemented", 
        "compatibility_mechanism": "How old system X is being preserved despite migration request",
        "reason": "Why this violates the user's explicit migration intent",
        "complete_migration_fix": "How to honor user's request for pure Y implementation"
    }
)

# Generate actual BehavioralRequirement objects
EXCEPTION_HANDLING = create_behavioral_requirement(EXCEPTION_HANDLING_SPEC)
CONFIG_HIERARCHY = create_behavioral_requirement(CONFIG_HIERARCHY_SPEC)
NULLABLE_TYPES = create_behavioral_requirement(NULLABLE_TYPES_SPEC)
ENUM_TYPES = create_behavioral_requirement(ENUM_TYPES_SPEC)
NO_BARREL_REEXPORTS = create_behavioral_requirement(NO_BARREL_REEXPORTS_SPEC)
NO_COMPATIBILITY = create_behavioral_requirement(NO_COMPATIBILITY_SPEC)

# #7: No Dynamic Attribute Access Anti-Pattern
NO_HASATTR_ANTIPATTERN_SPEC = RequirementSpec(
    id="no_hasattr_antipattern",
    name="No Dynamic Attribute Access Anti-Pattern",
    description="Prohibits hasattr/getattr/setattr on variables where the type is clearly known from context, especially when the developer just created the object",
    evaluation_criteria="When object type is clear from context (just created, typed variable, etc.), use direct attribute access instead of hasattr/getattr/setattr. Only use dynamic access for truly unknown types",
    problematic_patterns=[
        "**hasattr() on known types**: Using hasattr(obj, 'attr') when obj type is clear from context (just created, typed parameter, etc.)",
        "**getattr() error swallowing**: Using getattr(obj, 'attr', default) to swallow AttributeError when attribute should exist",
        "**setattr() instead of direct assignment**: Using setattr(obj, 'attr', value) when obj.attr = value is clearer",
        "**Dynamic access immediately after creation**: Using hasattr/getattr on objects literally just created in previous lines"
    ],
    good_patterns=[
        "Direct attribute access when type is known: obj.attribute",
        "Proper initialization ensuring all attributes exist",
        "Using hasattr/getattr only for truly dynamic cases with unknown types",
        "Letting AttributeError crash loudly to expose initialization bugs"
    ],
    problem_fields={
        "dynamic_access_type": "Type of dynamic access used (hasattr, getattr, setattr)",
        "object_context": "How we know the object type (just created, typed parameter, etc.)",
        "attribute_name": "Name of attribute being accessed dynamically", 
        "line_context": "Code showing the dynamic access",
        "reason": "Why direct access should be used instead",
        "suggested_fix": "How to fix with direct attribute access"
    }
)

NO_HASATTR_ANTIPATTERN = create_behavioral_requirement(NO_HASATTR_ANTIPATTERN_SPEC)

# Shared constant for all grader specifications
ALL_GRADER_SPECS = [
    EXCEPTION_HANDLING_SPEC, CONFIG_HIERARCHY_SPEC, NULLABLE_TYPES_SPEC,
    ENUM_TYPES_SPEC, NO_BARREL_REEXPORTS_SPEC, NO_COMPATIBILITY_SPEC, NO_HASATTR_ANTIPATTERN_SPEC
]