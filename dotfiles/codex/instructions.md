Read README.md for reference files to use.

I am happy to allow you to fire HTTP queries for testing. If useful for testing etc., just fire them right away without asking.

Write targetting the Python version that's installed. Use its available features
(e.g. `match` statement, assignment operator, ...) when appropriate.

## Style

Follow PEP 8.

Imports go at the top of files. Not into functions etc.

Avoid `getattr`/`setattr` unless absolutely necessary.

Use `pathlib` for manipulating paths, not `os.path`.

Before finishing, clear up your code, remove unused imports, code etc. and run `black`.

Use the new assignment-type f-strings: instead of e.g. f"foo var={var} bar", write f"foo {var=} bar".

## Not trailing whitespace

Do not leave around trailing whitespace in files. If you have an empty line, that empty line should not contain indentation whitespace.

Apply something like this to all your code files:

    sed -i 's/[[:space:]]\+$//' filename

## Aggressive DRY

Be relatively aggressively DRY. Even in e.g. Ansible playbooks, use variables for shared paths etc.
Reuse code when possible. Reuse *code patterns* when possible - for that purpose, some things you
can do include e.g., write decorators, context managers, etc.

### Example: loop

Wrong:
    # Add optional parameters
    if category is not None:
        habit_data["category"] = category

    if goal_type is not None:
        habit_data["goal_type"] = goal_type

    if target_value is not None:
        habit_data["target_value"] = target_value

    if frequency is not None:
        habit_data["frequency"] = frequency

    if frequency_config is not None:
        habit_data["frequency_config"] = frequency_config

Good:
    for key, value in {
        "category": category,
        "goal_type": goal_type,
        "target_value": target_value,
        "frequency": frequency,
        "frequency_config": frequency_config,
    }.items():
        if value is not None:
            habit_data[key] = value

## No broad try-catch, no swallowing errors

Do not write broad try-catch, like `try: ... except Exception: ...`.
If you need to catch exceptions, catch specific ones.
If you need to catch multiple exceptions, use a tuple.
This is only allowed at a very outer level like when you need to catch any possible
uncaught exception you might have run into while handling some request and need to
return it as a HTTP error 500. Or when you're doing something that *MUST* be
very magical and there is no other way.

If you ever do something like this:

    try:
        ...
    except Exception as e:
        pass

I will be very very unhapy and you should feel ashamed of yourself. There might be some
very rare reasons to do that every once in a blue moon, but if they happen, they deserve
a very detailed explanatory comment about why exactly this is okay here and why it won't
ever unintentionaly swallow fun things like `KeyboardInterrupt` or `SystemExit` or `SyntaxError`
and why this is the best possible solution and why you cannot in any way instead write a precise
filter for the specific types of errors you intentionally want to swallow.

## Early bail-out

Use early bail-out pattern. Including making functions to enable using it when it makes things nicer.
For example, do not do:

    if condition:
        foo()
        bar()
        baz()
        foobar()
        xyzzyfoo()
        ...
    else:
        xyzzy()
        faise Error(...)

Instead, do:

    if not condition:
        xyzzy()
        raise Error(...)
    foo()
    bar()
    baz()
    foobar()
    ...

This can be especially nice in helper functions.

## Document current state

If you make a change, don't leave behind comments like e.g. `# This used to work this way but we changed it to work this other way`
if you got rid of the old thing. You would not leave that around on a say piece of code on GitHub. It's not helpful to reader to know
about this historical detail. Just document current state.

If you applied a fix because something wasn't working, don't keep the broken non-working
version around "for backward compatibility". It was broken. It has no value.

## Referencing same class

Use `typing.Self` or `from __future__ import annotations` for referencing the same class in type hints:

    class X:
        def foo(self) -> Self:
            return self

Do not use name of class as a string for this.
