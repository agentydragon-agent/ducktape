If the repository have a `README.md`, read it and refer to it.
If there is `CLAUDE.md` or `CODEX.md`, read it and follow it.

## References

I am happy to allow you to fire HTTP queries for testing. If useful for testing etc., just fire them right away without asking.
Also start servers, experiment, etc.

### References folder

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

## Python

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

### Optionals and Type Hints

NEVER use `Optional[str]`, `Optional[X]` etc. Replace with `str | None`, `X | None`, etc. - newer Python style of optionals. For example:

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

## Style

Follow PEP 8.

Imports go at the top of files. Always put imports at top of file except possibly if required to break import loops or typing. Not into functions etc.

Never use `getattr`/`setattr` unless absolutely necessary - as in there literally *is no way* to do things differenly.

Use `pathlib` for manipulating paths, not `os.path`.

Before finishing, clear up your code, remove unused imports, code etc. and run `black`.

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

Good:
    for key, value in {
        "category": category,
        "goal_type": goal_type,
        "target_value": target_value,
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

## Testing

Test files should be located in the same directory as the module they're testing, with the name pattern `test_*.py`.

When writing unit test, make them be pytest tests, not executable files with __main__ section.

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

```python
# Wrong - unnecessarily verbose:
assert_that(user, has_property("name", contains_string("John")))

# Right - clearer and more direct:
assert_that(user.name, contains_string("John"))
```

The rule of thumb is: if you're just doing a single test on an object and it's a basic equality/truthiness check, use standard assertions. Use Hamcrest when you need its matchers to simplify complex assertions.

If you notice you'd like to test your changes (which is of course highly encouraged), rather than writing one-off
blobs of throwaway Python, feel free to suggest creating a new actual test file.

* if you do `logger.error/warning/...` inside exc handler it auto sets `exc_info=True` => `e` gets auto displayed => `": {e}"` in log message is unnecessary as `e` already auto printed

## Code Patterns

* Inline walrus operator `:=` can be used to simplify checks and assignments, e.g.:
    ```python
    # Instead of:
    missing = configured - available_interfaces
    if missing:
        logger.warning(f"Configured interfaces not found: {', '.join(sorted(missing))}")
    
    # Prefer:
    if missing := configured - available_interfaces:
        logger.warning(f"Configured interfaces not found: {', '.join(sorted(missing))}")
    ```

* When you know an attribute ALWAYS exists, do NOT use `hasattr()`. For example:
    ```python
    # Wrong:
    def format_sensor_name(self, piece: HardwarePiece, sensor_type: str) -> str:
        if hasattr(piece, 'get_display_name'):
            return f"Temperature {piece.get_display_name()}"
        return f"Temperature {piece.hardware_id}"

    # Right:
    def format_sensor_name(self, piece: HardwarePiece, sensor_type: str) -> str:
        return f"Temperature {piece.get_display_name()}"
    ```

* Exception Handling: NEVER swallow exceptions silently. When handling hardware discovery or sensor reading, ALWAYS propagate or log errors explicitly. For example, the code snippet you showed is BAD because it silently ignores potential errors during hardware discovery. Instead, handle specific exceptions, log them, or re-raise if appropriate.

Specific note about hardware/sensor discovery: 
```python
async def discover_hardware(self) -> List[HardwarePiece]:
    """Discover available temperature sensors."""
    try:
        pieces_by_key: Dict[Tuple[str, str], TemperaturePiece] = {}
        
        try:
            sensor_temps = psutil.sensors_temperatures()
        except Exception as e:
            logger.error(f"Failed to retrieve temperature sensors: {e}")
            raise  # Re-raise to indicate discovery failure

        # ...

        pieces = list(pieces_by_key.values())
        if pieces:
            labels = [f"{p.chip_name}:{p.label or 'unlabeled'}" for p in pieces]
            logger.debug(f"Discovered {len(pieces)} temperature sensors: {', '.join(labels)}")
        else:
            logger.warning("No temperature sensors found")

        return pieces
    except Exception as e:
        logger.error(f"Unexpected error during hardware discovery: {e}")
        raise
```

## URL and Parameter Handling

do not assemble URLs with plain string concat, e.g. `[f"{k}={v}" for k, v in params.items()]`. use some existing library that auto-wraps escaping etc.; apply *generally* for *all* formats that need escaping/similar.

## CLI and Shell Tools

I have ripgrep installed ('rg'). feel free to use it.

## Using PyHamcrest for Matching

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

## PyHamcrest Specific Notes

in pyhamcrest, when looking for whether a sequence contains *one* element which meets some properties, use *has_item*.

DO NOT do:
```python
xs = [x for x in capture_updates if x.unique_id == "bluetooth_enabled"]
assert any(x.state == True and x.icon == "mdi:bluetooth" for x in xs)
```

or:
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

instead, *do* do this:
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

## HTML Templating

as soon as you start doing nontrivial html operations/concatting, switch from manual html stitching to jinja2 or other templating engine that contextually makes sense. For example:

```python
def render_html_page(title: str, content: str, active_page: str = "index") -> str:
    """Render HTML page with common structure and navigation menu."""
    menu_items = [("index", "Home")] + [(page, page.capitalize()) for page in MARKDOWN_PAGES]
    
    menu_html = '<nav class="menu">\n'
    for page_id, page_title in menu_items:
        url = "/" if page_id == "index" else f"/{page_id}"
        active_class = ' class="active"' if page_id == active_page else ""
        menu_html += f'    <a href="{url}"{active_class}>{page_title}</a>\n'
    menu_html += '</nav>\n'
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="/style.css">
</head>
<body>
{menu_html}
{content}
</body>
</html>"""

# This is already a level of complexity above the point where you should have switched to jinja2 or similar.
```

## Avoiding One-off Variables

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

## Variable Naming Convention

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