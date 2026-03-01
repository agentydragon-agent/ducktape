# Home Assistant Token Privileges Research

Research date: 2026-03-01. Based on source code analysis of
<https://github.com/home-assistant/core> at HEAD.

## Summary

Home Assistant has a **granular permission engine** that supports per-entity,
per-device, per-area, and per-domain access control with read/control/edit
actions. However, **tokens cannot be scoped** — they always inherit their
user's full permissions. And in practice, only 3 hardcoded groups exist
(admin, user, read-only), with no UI or API to create custom groups with
custom policies. The fine-grained policy system is largely unused.

## Token Types

3 token types exist (`homeassistant/auth/models.py`):

| Type                      | Created by        | Expires |
| ------------------------- | ----------------- | ------- |
| `normal`                  | OAuth2 login flow | 90 days |
| `system`                  | Internal services | Never   |
| `long_lived_access_token` | User via UI       | Never   |

`RefreshToken` has no `scope` field. All tokens inherit user permissions.

## Permission Model

```
Owner (is_owner=True)
  └─ OwnerPermissions → allows everything

User (is_owner=False)
  └─ Groups (list)
       └─ Each Group has a PolicyType dict
            └─ Merged (most-permissive-wins) → PolicyPermissions
```

### System Groups

| Group     | ID                 | Policy                              |
| --------- | ------------------ | ----------------------------------- |
| Admin     | `system-admin`     | `{entities: True}`                  |
| Users     | `system-users`     | `{entities: True}` (same as admin!) |
| Read Only | `system-read-only` | `{entities: {all: {read: True}}}`   |

No API exists to create custom groups with custom policies.

## Policy Schema (the engine that exists but is underexposed)

```python
{
    "entities": {
        # Blanket rule for all entities
        "all": {"read": True, "control": False, "edit": False},

        # Per-domain (light, switch, sensor, etc.)
        "domains": {
            "light": {"read": True, "control": True},
            "switch": {"read": True}
        },

        # Per-area (kitchen, bedroom, etc.)
        "area_ids": {
            "<area-uuid>": {"read": True, "control": True}
        },

        # Per-device
        "device_ids": {
            "<device-uuid>": {"read": True, "control": True}
        },

        # Per-entity (highest priority)
        "entity_ids": {
            "light.kitchen": True,
            "switch.dangerous": {"read": True}  # read-only
        }
    }
}
```

### Targeting Granularities (checked in priority order)

1. `entity_ids` — exact entity ID match
2. `device_ids` — entity's parent device (via entity registry)
3. `area_ids` — device's area (via entity registry → device registry)
4. `domains` — entity ID prefix (`light.`, `switch.`, etc.)
5. `all` — blanket fallback

First matching level wins.

### Permission Actions

| Action    | Meaning                                      |
| --------- | -------------------------------------------- |
| `read`    | View entity state                            |
| `control` | Call services targeting entity               |
| `edit`    | Edit entity metadata (name, area assignment) |

### Enforcement Points

- **REST API** (`components/api/__init__.py`):
  - `GET /api/states` filters by `check_entity(id, "read")`
  - `GET /api/states/{id}` checks `POLICY_READ`
  - `POST /api/states/{id}` requires admin
- **WebSocket API** (`components/websocket_api/commands.py`):
  - `subscribe_events` for `STATE_CHANGED` checks per-entity read permission on each event
  - Non-admins restricted to `SUBSCRIBE_ALLOWLIST` event types
  - `get_states` filters by entity read permission
- **Service calls** (`helpers/service.py`):
  - `verify_domain_control` checks `POLICY_CONTROL` for target entities

### Policy Merging

When a user belongs to multiple groups, policies merge recursively with
most-permissive-wins: `True` > `dict` > `None`.

## What's NOT Supported

| Feature                       | Status |
| ----------------------------- | ------ |
| Token-level scoping           | No     |
| Per-service scoping           | No     |
| Per-automation/script scoping | No     |
| Time-based permissions        | No     |
| Conditional/contextual perms  | No     |
| Rate limiting per user/token  | No     |
| Custom groups via UI/API      | No     |

## Practical Implications

To get restricted access, you must:

1. Create a separate HA user
2. Assign them to the "Read Only" group (the only non-full-access group)
3. Create a long-lived access token for that user

This gives read-only access to ALL entities. There is no way through the
standard UI to restrict to specific entities, areas, or domains. The
granular policy engine exists in code but has no management interface.

## Key Source Files

| File                                                 | Purpose                               |
| ---------------------------------------------------- | ------------------------------------- |
| `homeassistant/auth/models.py`                       | User, RefreshToken, Group models      |
| `homeassistant/auth/permissions/__init__.py`         | Permission classes                    |
| `homeassistant/auth/permissions/entities.py`         | Entity permission schema & lookups    |
| `homeassistant/auth/permissions/const.py`            | `POLICY_READ/CONTROL/EDIT` constants  |
| `homeassistant/auth/permissions/system_policies.py`  | Admin/User/ReadOnly policy defs       |
| `homeassistant/auth/permissions/merge.py`            | Policy merging logic                  |
| `homeassistant/auth/permissions/types.py`            | PolicyType, CategoryType type aliases |
| `homeassistant/components/api/__init__.py`           | REST API permission enforcement       |
| `homeassistant/components/websocket_api/commands.py` | WebSocket permission enforcement      |
| `homeassistant/components/config/auth.py`            | User management WebSocket API         |
