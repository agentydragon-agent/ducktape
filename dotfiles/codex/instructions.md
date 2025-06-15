If the repository have a `README.md`, read it and refer to it.
If there is `CLAUDE.md` or `CODEX.md`, read it and follow it.

# References folder

You might see a folder like `references/` in the repo. If you do, do not edit anything in the folder. But the folder will
contain copied source code artifacts that may be useful to you to implement what you're doing. Look around and use `references/`
for reference.

Refer to it.

It should contain `references/fetch.sh` - a shell script to fetch the reference information.

If you're fetching new reference information on your own, add it to `references/fetch.sh`.
Feel free to add to it whatever references you may find useful.
It's intended to run at `./fetch.sh` from `references/`.

Likewise, feel free to run the script and edit/update/add to it.

All the actual reference files (e.g. 3rd party repos, documentation etc.) should be `gitignore`'d -
the only thing under version control in `references/` should be the `fetch.sh` script.

# Internet use OK

Feel free fire HTTP queries for testing, fetching documentation, source code for reference, etc.
*Especially* to add to the `references/` folder.

If useful for testing etc., just fire them right away without asking. Also start servers, experiment, etc.

# One-off Scripts and Throwaway Tests

if you're writing a one-off script - like say a one-off test of some behavior, a tool to only invoke once for some cleanup and then never again, etc:

name and place it in the filesystem so that its hnature as a *throwaway* *one-off* script is VERY CLEAR.

for example:

*   BAD: `test_notification_correctness.py`
    * when you are just tesitng the behvaavior of some API to only run it once, and learn about it, and then never to run it again
*   BETTER: `throwaway/test_notification_correctness.py`
*   EVEN BETTER `throwaway/2000-01-02/test_notification_correctness.py` PLUS add header at top of file like `# THIS IS JUST A ONE-OFF THROWAWAY SCRIPT`

this is to prevent polluting repositories with tons of accumulating cruft and helpers and one-off tests in highly frequented locations like repo root

# General across languages

## No trailing whitespace

Do not leave around trailing whitespace in files. If you have an empty line, that empty line should not contain indentation whitespace.
Apply something like this to all your code files:

    sed -i 's/[[:space:]]\+$//' filename

## Aggressive DRY

Be relatively aggressively DRY. Even in e.g. Ansible playbooks, use variables for shared paths etc.
Reuse code when possible. Reuse *code patterns* when possible - for that purpose, some things you
can do include e.g., write decorators, context managers, etc.

### Particular case: loop

Use loops to avoid repeating the same code block, for example:

Wrong:

```
if category is not None:
    habit_data["category"] = category

if goal_type is not None:
    habit_data["goal_type"] = goal_type

if target_value is not None:
    habit_data["target_value"] = target_value
```

Good:

```
for key, value in {
    "category": category,
    "goal_type": goal_type,
    "target_value": target_value,
}.items():
    if value is not None:
        habit_data[key] = value
```

### Particular case: No redundant special cases for empty structures

Do not implement redundant special cases for empty lists/dicts/structures if they do not change behavior.

DO NOT DO:

```python
def fn(x: list[int]):
    if not xs:      # <-- BAD - redundant, deleting this block neither changes behavior nor runtime
        return '<>'
   
    x = '<'
    for i, n in enumerate(xs):
        if i > 0:
            x += ' '
        x += str(n)
    x += '>'
    return x
```

Here the first 2 lines of the function are *redundant* because they do not change behavior and neither are they an optimization.

CORRECTED:

```python
def fn(x: list[int]):
    x = '<'
    for i, n in enumarate(xs):
        if i > 0:
            x += ' '
        x += str(n)
    x += '>'
    return x
```

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

NEVER swallow exceptions silently. ALWAYS propagate or AT LEAST log errors explicitly.

Handle specific exceptions, log them, or re-raise if appropriate.

## Early bail-out

Use early bail-out pattern. Including making functions to enable using it when it makes things nicer.

For example, DO NOT do:

```python
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
```

Instead, DO:

```python
if not condition:
    xyzzy()
    raise Error(...)
foo()
bar()
baz()
foobar()
...
```

DO NOT do:

```python
async def _handle_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
    """Handle interfaces being removed (e.g., adapter disappearing)."""
    if path == self._adapter_path and "org.bluez.Adapter1" in interfaces:
        logger.warning(f"Bluetooth adapter removed: {path}")
        # Clean up adapter
        if self._adapter_properties_iface:
            self._adapter_properties_iface.off_properties_changed(self._handle_adapter_properties_changed)
        self._adapter_path = None
        # ... bunch more code in this branch, nothing outside it ...
```

Instead, DO:

```python
async def _handle_interfaces_removed(self, path: str, interfaces: list[str]) -> None:
    """Handle interfaces being removed (e.g., adapter disappearing)."""
    if path != self._adapter_path or "org.bluez.Adapter1" not in interfaces:
        return  # Early bail-out if not the adapter we're interested in
    logger.warning(f"Bluetooth adapter removed: {path}")
    # Clean up adapter
    if self._adapter_properties_iface:
        self._adapter_properties_iface.off_properties_changed(self._handle_adapter_properties_changed)
    self._adapter_path = None
    ...
```

This just saved us an indentation level.
This can be especially nice in helper functions.

## Document current state, NOT change you're making

If you make a change, don't leave behind comments like e.g. `# This used to work this way but we changed it to work this other way`
if you got rid of the old thing. You would not leave that around on a say piece of code on GitHub. It's not helpful to reader to know
about this historical detail. Just document current state.

If you applied a fix because something wasn't working, don't keep the broken non-working
version around "for backward compatibility". It was broken. It has no value.

## DO NOT assemble non-plaintext by string concatantion (e.g., URL parameters)

do not assemble URLs with plain string concat, e.g. `[f"{k}={v}" for k, v in params.items()]`. use some existing library that auto-wraps escaping etc.; apply *generally* for *all* formats that need escaping/similar.

This applies *generally* to *ANY* format that is NOT actually plaintext and cannot be in full generality
*ALWAYS* made by plain string concat. DO NOT assemble by manual string concat, either: JSON, text protobufs, SQL, etc etc etc.

## CLI and Shell Tools

I have ripgrep installed ('rg'). feel free to use it.

## Avoid One-off Variables

Avoid creating one-off variables that are used only once and add unnecessary lines. For example:

```python
async def update_sensors(self, updates: list[SensorUpdate]):
    """Send batched sensor updates.
    
    Note: SensorUpdate is designed to map 1:1 to the API format.
    """
    await self._post_webhook({
        "type": "update_sensor_states",
        "data": [update.dict(exclude_none=True) for update in updates]
    })
```

Instead of creating a `data` variable that is used only once, directly pass the inline-constructed dictionary to the method.

## Self-describing variable names - e.g., units, "is it an IP or a MAC address", etc.

try to make sure variables are clear about the unit / type of thing they're expecting.

instead of:
```python
bluetooth_devices: list[str]
timeout: int
```

prefer:
```python
bluetooth_device_macs: list[str]
timeout_secs: int
```

of course with timeout specifically it would be even better to just use `datetime.timedelta` and then it's fine to just call it 'timeout' because type inherently encodes unit

# Python

## Style

Follow PEP 8.

Imports go at the top of files. Always put imports at top of file except possibly if required to break import loops or typing. Not into functions etc.

Never use `getattr`/`setattr` unless absolutely necessary - as in there literally *is no way* to do things differenly.

Before finishing, clear up your code, remove unused imports, code etc. and run `black`.

## Target modern Python

Write targetting the Python version that's installed. Use its available features to their full extent where they make sense and
don't make code worse:

* `match` statement
* `:=` assignment operator
* `X | Y` instead of `Union[X | Y]`
* `X | None` instead of `Optional[X]`
* `f"{var=}"` instead of `f"var={var}"` (use this one basically always whenever that's the string you are producing)
* `str.removeprefix`, `str.removesuffix` instead of slicing - safer
* `dict1 | dict2` (unino), `dict1 & dict2` (intersection) and ditto for `set`s
* `zoneinfo` builtin library

Use `pathlib` for manipulating paths, not `os.path`.

### NEVER use `typing.List`, `Union`, `Optional`, ... -- replace with new syntax sugar

NEVER use `Optional[str]`, `Optional[X]` etc.
Replace with newer style: `str | None`, `X | None`, etc.

DO NOT write:

* `variable: List[int]`
* `variable: Union[str, int]`
* `variable: Optional[str]`

DO write:

* `variable: list[int]`
* `variable: str | int`
* `variable: str | None`


```python
# Wrong:
class Foo:
    ab: Optional[str]  # For encryption
    cd: str
    ef: Optional[str]

# Right:
class Foo:
    ab: str | None  # For encryption
    cd: str
    ef: str | None
```


## Referencing same class

Use `typing.Self` or `from __future__ import annotations` for referencing the same class in type hints:

    class X:
        def foo(self) -> Self:
            return self

Do not use name of class as a string for this.

## Walrus operator

Inline walrus operator `:=` can be used to simplify checks and assignments, e.g.:

```python
# Instead of:
missing = configured - available_interfaces
if missing:
    logger.warning(f"Interfaces not found: {', '.join(sorted(missing))}")

# Prefer:
if missing := configured - available_interfaces:
    logger.warning(f"Interfaces not found: {', '.join(sorted(missing))}")
```

## Code Patterns

### EXTREMELY STRONGLY AVOID `hasattr` / `getattr` / `setattr`

One particular example, NEVER use those when you can already KNOW an attribute ALWAYS exists
because you control all the definition/use sites:

WRONG:

```python
def format_sensor_name(self, piece: HardwarePiece, sensor_type: str) -> str:
    if hasattr(piece, 'get_display_name'):
        return f"Temperature {piece.get_display_name()}"
    return f"Temperature {piece.hardware_id}"
```

OK:

```python
def format_sensor_name(self, piece: HardwarePiece, sensor_type: str) -> str:
    return f"Temperature {piece.get_display_name()}"
```

## HTML Templating

As soon as you start doing nontrivial html operations/concatting, switch from manual html stitching to jinja2 or other templating engine that contextually makes sense.

BAD: already **WAY TOO COMPLEX** for manual html stitching - **AND** prone to escaping issues:

```python
menu_html = '<nav class="menu">\n'
for page_id, page_title in menu_items:
    url = "/" if page_id == "index" else f"/{page_id}"
    active_class = ' class="active"' if page_id == active_page else ""
    menu_html += f'    <a href="{url}"{active_class}>{page_title}</a>\n'
menu_html += '</nav>\n'
html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>{content}</body>
</html>"""
```

This should have switched to jinja2 about 10 minutes ago already.

## Logging

if you do `logger.error/warning/...` inside exc handler it auto sets `exc_info=True` => `e` gets auto displayed => `": {e}"` in log message is unnecessary as `e` already auto printed

Test files should be located in the same directory as the module they're testing, with the name pattern `test_*.py`.

When writing unit test, make them be pytest tests, **NOT** executable files with __main__ section.

### PyHamcrest

Use pyhamcrest when testing sensor collections or complex matching scenarios. For example:

```python
# Instead of multiple `.next()` and assert calls:
assert_that(sensors, has_items(
    has_properties(unique_id="battery_level", state=50.0, icon="mdi:battery-50"),
    has_properties(unique_id="battery_state", state="discharging", icon="mdi:battery-minus"),
    has_properties(unique_id="battery_power", state=-10.0, unit_of_measurement="W", device_class=DeviceClass.POWER),
    has_properties(unique_id="battery_time_to_empty", state=3600, unit_of_measurement="s", device_class=DeviceClass.DURATION),
    has_properties(unique_id="battery_time_to_full", state=7200, unit_of_measurement="s", device_class=DeviceClass.DURATION),
))
```

This approach provides more readable and concise assertions, making it easier to verify complex object collections.

When looking for whether a sequence contains *one* element which meets some properties, use *has_item*.

DO NOT do:

```python
xs = [x for x in capture_updates if x.unique_id == "bluetooth_enabled"]
assert any(x.state == True and x.icon == "mdi:bluetooth" for x in xs)
```

ALSO DO NOT DO:

```python
from hamcrest import assert_that, has_items, has_properties
assert_that(
    capture_updates,
    has_items(
        has_properties(
            unique_id="bluetooth_enabled",
            state=True,
            icon="mdi:bluetooth"
        )
    )
)
```

Instead, DO do this:

```python
from hamcrest import assert_that, has_item, has_properties
assert_that(
    capture_updates,
    has_item(
        has_properties(
            unique_id="bluetooth_enabled",
            state=True,
            icon="mdi:bluetooth"
        )
    )
)
```

### When to use PyHamcrest vs standard assertions

Use standard Python assertions for basic checks that don't benefit from Hamcrest's matchers:

```python
# Use standard assertions when Hamcrest doesn't add value:
assert value == 200
assert user.name == "John"
assert foo is True
assert not bar
assert len(items) > 0
```

Use PyHamcrest when it makes the assertion more clear, expressive, or when you're doing complex checks:

```python
# Use Hamcrest for these cases:
# String content checking
assert_that(text, contains_string("success"))

# Dictionary content validation
assert_that(data, has_entries(status="ok", count=greater_than(0)))

# Multiple conditions
assert_that(
    response.text,
    all_of(
        contains_string("success"),
        contains_string("data")
    )
)
```

Access properties directly when using Hamcrest instead of using has_property when it doesn't add value:

WRONG - unnecessarily verbose:

```python
assert_that(user, has_property("name", contains_string("John")))
```

RIGHT - clearer and more direct:

```python
assert_that(user.name, contains_string("John"))
```

The rule of thumb is: if you're just doing a single test on an object and it's a basic equality/truthiness check, use standard assertions. Use Hamcrest when you need its matchers to simplify complex assertions.

If you notice you'd like to test your changes (which is of course highly encouraged), rather than writing one-off
blobs of throwaway Python, feel free to suggest creating a new actual test file.
