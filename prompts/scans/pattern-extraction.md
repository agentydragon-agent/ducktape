# Scan: Pattern Extraction with Language Features

**Goal**: Use language features to extract and deduplicate repetitive patterns, whatever the language allows.

**Priority**: High

## General Principle

When you see a pattern repeated, don't just copy-paste - **extract it using appropriate language features**:

- **Generics/Type Parameters**: For types that vary but structure is same
- **Higher-Order Functions**: For algorithms that vary but flow is same
- **Decorators**: For cross-cutting concerns (logging, timing, auth, etc.)
- **Abstract Base Classes**: For interface patterns with shared behavior
- **Protocols/Structural Typing**: For duck-typed patterns
- **Context Managers**: For setup/teardown patterns
- **Metaclasses**: For class-level patterns (rare, use sparingly)
- **Factory Functions**: For complex object construction patterns

The key insight: **If the pattern exists, the language probably has a feature to express it once.**

## Example 1: Generics for Repetitive Data Structures

### Bad: Copy-Paste Pattern

```python
class ResponseListModel(BaseModel):
    items: list[ResponseRecordModel]
    limit: int
    offset: int
    total: int


class FrameListModel(BaseModel):
    items: list[FrameRecordModel]
    limit: int
    offset: int
    total: int


class UserListModel(BaseModel):
    items: list[UserModel]
    limit: int
    offset: int
    total: int
```

**Pattern**: Same structure (items, pagination fields), different item type.

### Good: Generic Type Parameter

```python
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedList(BaseModel, Generic[T]):
    """Generic paginated list response."""

    items: list[T]
    total: int
    limit: int
    offset: int


# Usage - fully typed!
@app.get("/api/responses", response_model=PaginatedList[ResponseRecordModel])
async def list_responses(...) -> PaginatedList[ResponseRecordModel]:
    return PaginatedList(items=..., total=..., limit=..., offset=...)
```

**Benefits**: DRY, type safety, consistency, single source of truth.

## Example 2: Higher-Order Functions for Algorithmic Patterns

### Bad: Copy-Paste Algorithm

```python
def process_users():
    users = fetch_users()
    for user in users:
        try:
            validate_user(user)
            transform_user(user)
            save_user(user)
        except Exception as e:
            log_error(f"User processing failed: {e}")

def process_orders():
    orders = fetch_orders()
    for order in orders:
        try:
            validate_order(order)
            transform_order(order)
            save_order(order)
        except Exception as e:
            log_error(f"Order processing failed: {e}")
```

**Pattern**: Fetch, iterate, try-except, validate-transform-save.

### Good: Higher-Order Function

```python
from typing import Callable, TypeVar

T = TypeVar("T")


def process_items(
    fetch: Callable[[], list[T]],
    validate: Callable[[T], None],
    transform: Callable[[T], None],
    save: Callable[[T], None],
    item_name: str,
) -> None:
    items = fetch()
    for item in items:
        try:
            validate(item)
            transform(item)
            save(item)
        except Exception as e:
            log_error(f"{item_name} processing failed: {e}")


# Usage
process_items(fetch_users, validate_user, transform_user, save_user, "User")
process_items(fetch_orders, validate_order, transform_order, save_order, "Order")
```

## Example 3: Decorators for Cross-Cutting Concerns

### Bad: Copy-Paste Logging/Timing

```python
async def fetch_user(user_id: int):
    start = time.time()
    logger.info(f"Fetching user {user_id}")
    try:
        result = await db.get_user(user_id)
        logger.info(f"Fetched user {user_id} in {time.time() - start:.2f}s")
        return result
    except Exception as e:
        logger.error(f"Failed to fetch user {user_id}: {e}")
        raise


async def fetch_order(order_id: int):
    start = time.time()
    logger.info(f"Fetching order {order_id}")
    try:
        result = await db.get_order(order_id)
        logger.info(f"Fetched order {order_id} in {time.time() - start:.2f}s")
        return result
    except Exception as e:
        logger.error(f"Failed to fetch order {order_id}: {e}")
        raise
```

**Pattern**: Log start, time execution, log completion, catch and log errors.

### Good: Decorator

```python
import functools
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def log_and_time(func: Callable[..., T]) -> Callable[..., T]:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        logger.info(f"Calling {func.__name__} with {args}, {kwargs}")
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start
            logger.info(f"{func.__name__} completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed: {e}")
            raise

    return wrapper


# Usage - clean!
@log_and_time
async def fetch_user(user_id: int):
    return await db.get_user(user_id)


@log_and_time
async def fetch_order(order_id: int):
    return await db.get_order(order_id)
```

## Example 4: Context Managers for Setup/Teardown

### Bad: Copy-Paste Resource Management

```python
async def process_with_lock():
    await lock.acquire()
    try:
        await do_work()
    finally:
        await lock.release()


async def process_with_transaction():
    tx = await db.begin()
    try:
        await do_work()
        await tx.commit()
    except:
        await tx.rollback()
        raise
```

**Pattern**: Acquire resource, try-finally to release.

### Good: Context Manager

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def acquire_lock(lock):
    await lock.acquire()
    try:
        yield
    finally:
        await lock.release()


@asynccontextmanager
async def transaction(db):
    tx = await db.begin()
    try:
        yield tx
        await tx.commit()
    except:
        await tx.rollback()
        raise


# Usage
async def process_with_lock():
    async with acquire_lock(lock):
        await do_work()


async def process_with_transaction():
    async with transaction(db) as tx:
        await do_work()
```

## Example 5: Abstract Base Classes for Interface Patterns

### Bad: Duplicated Interface Implementation

```python
class FileStorage:
    def save(self, key: str, data: bytes) -> None:
        self._validate_key(key)
        self._validate_data(data)
        # ... actual file saving

    def _validate_key(self, key: str) -> None:
        if not key or "/" in key:
            raise ValueError("Invalid key")

    def _validate_data(self, data: bytes) -> None:
        if not data:
            raise ValueError("Empty data")


class S3Storage:
    def save(self, key: str, data: bytes) -> None:
        self._validate_key(key)
        self._validate_data(data)
        # ... actual S3 upload

    def _validate_key(self, key: str) -> None:  # DUPLICATED
        if not key or "/" in key:
            raise ValueError("Invalid key")

    def _validate_data(self, data: bytes) -> None:  # DUPLICATED
        if not data:
            raise ValueError("Empty data")
```

**Pattern**: Common validation logic across implementations.

### Good: Abstract Base Class

```python
from abc import ABC, abstractmethod


class Storage(ABC):
    def save(self, key: str, data: bytes) -> None:
        self._validate_key(key)
        self._validate_data(data)
        self._do_save(key, data)

    def _validate_key(self, key: str) -> None:
        if not key or "/" in key:
            raise ValueError("Invalid key")

    def _validate_data(self, data: bytes) -> None:
        if not data:
            raise ValueError("Empty data")

    @abstractmethod
    def _do_save(self, key: str, data: bytes) -> None:
        """Subclasses implement actual storage."""
        pass


class FileStorage(Storage):
    def _do_save(self, key: str, data: bytes) -> None:
        # Just implement storage, validation is inherited
        with open(f"storage/{key}", "wb") as f:
            f.write(data)


class S3Storage(Storage):
    def _do_save(self, key: str, data: bytes) -> None:
        # Just implement storage, validation is inherited
        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=data)
```

## Detection Strategy

1. **Look for repeated structure** - same fields, same flow, same setup/teardown
2. **Identify what varies** - type? algorithm? resource? validation?
3. **Choose appropriate language feature**:
   - **Structure varies by type?** → Generics
   - **Algorithm varies?** → Higher-order function
   - **Cross-cutting concern?** → Decorator
   - **Setup/teardown pattern?** → Context manager
   - **Shared interface with common behavior?** → Abstract base class
4. **Extract the pattern** using that feature
5. **Verify** - code should be shorter, clearer, more maintainable

## When Extraction is Not Worth It

- **One-off code** - No duplication yet
- **Genuinely different** - Coincidental similarity, not actual pattern
- **Over-abstraction** - Would make code harder to understand
- **Performance critical** - Profiled hotpath where abstraction costs too much

## References

- [Don't Repeat Yourself (DRY)](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself)
- [Rule of Three](https://en.wikipedia.org/wiki/Rule_of_three_(computer_programming))
- [Abstraction Principle](https://en.wikipedia.org/wiki/Abstraction_principle_(computer_programming))
