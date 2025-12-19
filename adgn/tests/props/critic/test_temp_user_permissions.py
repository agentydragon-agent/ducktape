"""Progressive tests to isolate temp user permission issues.

These tests systematically narrow down why test_critic_http_mode_submit_with_issues
fails with "permission denied for table reported_issues".

Test progression:
1. Phase 1: Direct connection (no Docker) - isolates Docker-specific issues
2. Phase 2: Permission visibility - verifies grants actually happen
3. Phase 3: Container environment - verifies correct env vars and routing
4. Phase 4: Minimal Docker INSERT - simplest failing case

Run with: pytest tests/props/critic/test_temp_user_permissions.py -v
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastmcp.client import Client
import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from adgn.props.critic.critic import CriticAgentEnvironment
from adgn.props.critic.user_manager import CriticUserManager
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import ReportedIssue
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ExplicitFileScope
from tests.props.conftest import make_critic_run


@dataclass(frozen=True)
class TablePermissions:
    """Effective table permissions (works with both direct grants and inherited roles)."""

    insert: bool
    select: bool
    update: bool

    def all_granted(self) -> bool:
        """Check if all required permissions are granted."""
        return self.insert and self.select and self.update


def check_table_permissions_sync(conn: Connection, username: str, table: str) -> TablePermissions:
    """Check effective table permissions for a user (sync connection).

    Uses has_table_privilege() which handles both direct grants and inherited permissions.
    """
    result = conn.execute(
        text(
            """
            SELECT has_table_privilege(:username, :table, 'INSERT'),
                   has_table_privilege(:username, :table, 'SELECT'),
                   has_table_privilege(:username, :table, 'UPDATE')
        """
        ),
        {"username": username, "table": table},
    )
    row = result.fetchone()
    assert row is not None, f"Expected row from permissions query for {table}"
    return TablePermissions(insert=row[0], select=row[1], update=row[2])


async def check_table_permissions_async(conn: AsyncConnection, username: str, table: str) -> TablePermissions:
    """Check effective table permissions for a user (async connection).

    Uses has_table_privilege() which handles both direct grants and inherited permissions.
    """
    result = await conn.execute(
        text(
            """
            SELECT has_table_privilege(:username, :table, 'INSERT'),
                   has_table_privilege(:username, :table, 'SELECT'),
                   has_table_privilege(:username, :table, 'UPDATE')
        """
        ),
        {"username": username, "table": table},
    )
    row = result.fetchone()
    assert row is not None, f"Expected row from permissions query for {table}"
    return TablePermissions(insert=row[0], select=row[1], update=row[2])


@pytest.mark.requires_postgres
async def test_temp_user_direct_insert(synced_test_db: DatabaseConfig, test_prompt_sha: str):
    """Test 1: Direct Python INSERT with temp user (no Docker).

    This tests the temp user manager in isolation.
    If this PASSES, permissions are correctly granted.
    If this FAILS, problem is in user manager itself.
    """
    run_id = uuid4()

    # Create test CriticRun (required for FK constraint)
    with get_session() as session:
        # Need a valid example first
        example = session.query(Example).first()
        assert example, "Need at least one example in database"

        critic_run = make_critic_run(
            example=example,
            prompt_sha256=test_prompt_sha,  # Use valid prompt from fixture
        )
        critic_run.id = run_id  # Override with our test ID
        session.add(critic_run)
        session.commit()

    # Create temp user
    manager = CriticUserManager(synced_test_db.admin, run_id)

    async with manager as creds:
        print(f"\n✓ Created user: {creds.username}")

        # Connect as temp user
        user_config = synced_test_db.admin.with_user(creds)
        user_engine = create_engine(user_config.url())

        with user_engine.connect() as conn:
            # Verify connection
            result = conn.execute(text("SELECT current_user, current_database()"))
            row = result.fetchone()
            assert row is not None, "Expected row from SELECT query"
            print(f"  Connected as: {row[0]}")
            print(f"  Database: {row[1]}")

            # Verify RLS function
            result = conn.execute(text("SELECT current_critic_run_id()"))
            rls_run_id = result.scalar()
            print(f"  current_critic_run_id(): {rls_run_id}")
            assert rls_run_id == run_id, "RLS function should return correct run_id"

            # Try INSERT
            conn.execute(
                text(
                    """
                INSERT INTO reported_issues (critic_run_id, issue_id, rationale)
                VALUES (:run_id, 'test-direct-insert', 'Direct INSERT test')
            """
                ),
                {"run_id": run_id},
            )
            conn.commit()
            print("  ✓ INSERT succeeded")

        user_engine.dispose()


@pytest.mark.requires_postgres
async def test_temp_user_permissions_visible(synced_test_db: DatabaseConfig):
    """Test 2: Verify permissions are actually granted and visible.

    Uses has_table_privilege() to check effective permissions (includes inherited).
    Tests from both admin and user connections.
    """
    run_id = uuid4()

    manager = CriticUserManager(synced_test_db.admin, run_id)

    async with manager as creds:
        print(f"\n✓ Created user: {creds.username}")

        # Query effective permissions from admin connection
        admin_engine = create_engine(synced_test_db.admin.url())
        with admin_engine.connect() as conn:
            perms = check_table_permissions_sync(conn, creds.username, "reported_issues")
            print(f"  Admin view - Effective permissions: {perms}")
            assert perms.all_granted(), f"All permissions should be granted: {perms}"
        admin_engine.dispose()

        # Query permissions from user connection
        user_config = synced_test_db.admin.with_user(creds)
        user_engine = create_engine(user_config.url())
        with user_engine.connect() as conn:
            # Get current_user for self-check
            result = conn.execute(text("SELECT current_user"))
            current_user = result.scalar()
            assert current_user is not None, "Expected current_user"
            perms = check_table_permissions_sync(conn, current_user, "reported_issues")
            print(f"  User view - Permissions: {perms}")
            assert perms.all_granted(), f"All permissions should be True: {perms}"
        user_engine.dispose()


@pytest.mark.requires_postgres
@pytest.mark.requires_docker
async def test_docker_container_env_vars(
    synced_test_db: DatabaseConfig, async_docker_client, test_specimens_hydrator, test_prompt_sha: str
):
    """Test 3: Log all environment variables inside Docker container.

    Verifies what PG* environment variables the container actually sees.
    Critical for diagnosing environment passing issues.
    """
    run_id = uuid4()
    snapshot_slug = SnapshotSlug("test-fixtures/test-trivial")
    scope = ExplicitFileScope(files=["add.py"])

    # Create test critic run
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=snapshot_slug).first()
        assert example, f"Need example for {snapshot_slug}"

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        critic_run.id = run_id
        session.add(critic_run)
        session.commit()

    # Create agent environment
    agent_env = CriticAgentEnvironment(
        snapshot_slug=snapshot_slug,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        critic_run_id=run_id,
        scope=scope,
        db_config=synced_test_db,
        mount_properties=False,
    )

    async with agent_env as compositor, Client(compositor.runtime.server) as client:
        # Execute env command to see all environment variables
        result = await client.call_tool(
            "exec", {"cmd": ["env"], "cwd": None, "env": None, "user": None, "timeout_ms": 5000}
        )

        assert not result.is_error, f"env command failed: {result.content}"
        output = result.structured_content

        # Parse environment variables
        env_lines = output["stdout"].strip().split("\n")
        pg_vars = {}
        mcp_vars = {}

        for line in env_lines:
            if "=" in line:
                key, value = line.split("=", 1)
                if key.startswith("PG"):
                    pg_vars[key] = value
                elif key.startswith("MCP_"):
                    mcp_vars[key] = value

        print("\n=== PostgreSQL Environment Variables ===")
        for key in sorted(pg_vars.keys()):
            # Mask password
            value = pg_vars[key]
            if key == "PGPASSWORD":
                value = "***" if value else "(empty)"
            print(f"  {key}={value}")

        print("\n=== MCP Environment Variables ===")
        for key in sorted(mcp_vars.keys()):
            value = mcp_vars[key]
            if key == "MCP_SERVER_TOKEN":
                value = f"{value[:8]}..." if value else "(empty)"
            print(f"  {key}={value}")

        # Assertions
        assert "PGHOST" in pg_vars, "PGHOST must be set"
        assert "PGPORT" in pg_vars, "PGPORT must be set"
        assert "PGDATABASE" in pg_vars, "PGDATABASE must be set"
        assert "PGUSER" in pg_vars, "PGUSER must be set"
        assert "PGPASSWORD" in pg_vars, "PGPASSWORD must be set"
        assert pg_vars["PGUSER"].startswith("critic_agent_"), "PGUSER should be critic agent user"


@pytest.mark.requires_postgres
@pytest.mark.requires_docker
async def test_docker_connection_info(
    synced_test_db: DatabaseConfig, async_docker_client, test_specimens_hydrator, test_prompt_sha: str
):
    """Test 4: Query database connection info from inside Docker container.

    Verifies the container is actually connecting to the correct database
    as the correct user.
    """
    run_id = uuid4()
    snapshot_slug = SnapshotSlug("test-fixtures/test-trivial")
    scope = ExplicitFileScope(files=["add.py"])

    # Create test critic run
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=snapshot_slug).first()
        assert example

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        critic_run.id = run_id
        session.add(critic_run)
        session.commit()

    agent_env = CriticAgentEnvironment(
        snapshot_slug=snapshot_slug,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        critic_run_id=run_id,
        scope=scope,
        db_config=synced_test_db,
        mount_properties=False,
    )

    async with agent_env as compositor:
        # Execute Python to query connection info
        query_script = """
import psycopg2
import os

# Connect using environment variables
conn = psycopg2.connect("")  # Empty string uses PG* env vars

cursor = conn.cursor()

# Query connection info
cursor.execute(\"\"\"
    SELECT current_user,
           current_database(),
           inet_server_addr(),
           inet_server_port(),
           current_critic_run_id()
\"\"\")

row = cursor.fetchone()
print(f"current_user: {row[0]}")
print(f"current_database: {row[1]}")
print(f"server_addr: {row[2]}")
print(f"server_port: {row[3]}")
print(f"current_critic_run_id: {row[4]}")

# Check permissions
cursor.execute(\"\"\"
    SELECT has_table_privilege(current_user, 'reported_issues', 'INSERT'),
           has_table_privilege(current_user, 'reported_issues', 'SELECT'),
           has_table_privilege(current_user, 'reported_issues', 'UPDATE')
\"\"\")
perms = cursor.fetchone()
print(f"INSERT permission: {perms[0]}")
print(f"SELECT permission: {perms[1]}")
print(f"UPDATE permission: {perms[2]}")

conn.close()
"""

        async with Client(compositor.runtime.server) as client:
            result = await client.call_tool(
                "exec",
                {"cmd": ["python3", "-c", query_script], "cwd": None, "env": None, "user": None, "timeout_ms": 10000},
            )

            if result.is_error:
                print("\n✗ Query failed:")
                print(result.content)
                pytest.fail(f"Connection query failed: {result.content}")

            output = result.structured_content
            if output["exit"]["exit_code"] != 0:
                print(f"\n✗ Script failed with exit code {output['exit']['exit_code']}")
                print("STDOUT:", output["stdout"])
                print("STDERR:", output["stderr"])
                pytest.fail(f"Script failed: {output['stderr']}")

            print("\n=== Container Database Connection Info ===")
            print(output["stdout"])

            # Parse output and verify
            stdout = output["stdout"]
            assert f"current_user: critic_agent_{run_id}" in stdout, "Should connect as critic agent user"
            assert "current_database:" in stdout
            assert "current_critic_run_id:" in stdout
            assert "INSERT permission: True" in stdout, "Should have INSERT permission"
            assert "SELECT permission: True" in stdout, "Should have SELECT permission"
            assert "UPDATE permission: True" in stdout, "Should have UPDATE permission"


@pytest.mark.requires_postgres
@pytest.mark.requires_docker
async def test_docker_minimal_insert(
    synced_test_db: DatabaseConfig, async_docker_client, test_specimens_hydrator, test_prompt_sha: str
):
    """Test 5: Minimal Docker INSERT test (simplest failing case).

    This is the minimal reproduction of the failing test.
    Uses the issue_helpers.py functions just like the real test.
    """
    run_id = uuid4()
    snapshot_slug = SnapshotSlug("test-fixtures/test-trivial")
    scope = ExplicitFileScope(files=["add.py"])

    # Create test critic run
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=snapshot_slug).first()
        assert example

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        critic_run.id = run_id
        session.add(critic_run)
        session.commit()

    agent_env = CriticAgentEnvironment(
        snapshot_slug=snapshot_slug,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        critic_run_id=run_id,
        scope=scope,
        db_config=synced_test_db,
        mount_properties=False,
    )

    async with agent_env as compositor:
        # Use the actual issue helpers like the real test does
        insert_script = """
from adgn.props.critic.issue_helpers import insert_issue, insert_occurrence

# Insert issue (this is where it fails)
insert_issue(
    issue_id="test-minimal",
    rationale="Minimal test issue"
)

# Insert occurrence
insert_occurrence(
    issue_id="test-minimal",
    file="add.py",
    start_line=1,
    end_line=1
)

print("SUCCESS: INSERT completed")
"""

        async with Client(compositor.runtime.server) as client:
            result = await client.call_tool(
                "exec",
                {"cmd": ["python3", "-c", insert_script], "cwd": None, "env": None, "user": None, "timeout_ms": 15000},
            )

            if result.is_error:
                print("\n✗ INSERT failed:")
                print(result.content)
                pytest.fail(f"INSERT failed: {result.content}")

            output = result.structured_content
            exit_code = output["exit"]["exit_code"]

            if exit_code != 0:
                print(f"\n✗ Script failed with exit code {exit_code}")
                print("STDOUT:", output["stdout"])
                print("STDERR:", output["stderr"])
                pytest.fail(f"INSERT script failed: {output['stderr']}")

            print("\n=== INSERT Result ===")
            print(output["stdout"])

            assert "SUCCESS" in output["stdout"], "INSERT should succeed"

            # Verify the issue was actually inserted
            with get_session() as session:
                issue = session.query(ReportedIssue).filter_by(critic_run_id=run_id, issue_id="test-minimal").first()
                assert issue is not None, "Issue should be in database"
                assert issue.rationale == "Minimal test issue"


@pytest.mark.requires_postgres
async def test_permissions_visible_before_container(synced_test_db: DatabaseConfig, test_prompt_sha: str):
    """Priority 1: Verify permissions exist BEFORE container creation.

    This bifurcates: "permissions never existed" vs "container can't see them".

    With template role inheritance, permissions come from the inherited role
    (critic_agent_template), not direct grants. We use has_table_privilege()
    to check effective permissions.
    """
    run_id = uuid4()

    # Create test critic run
    with get_session() as session:
        example = session.query(Example).first()
        assert example, "Need at least one example in database"

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        critic_run.id = run_id
        session.add(critic_run)
        session.commit()

    # Create temp user
    manager = CriticUserManager(synced_test_db.admin, run_id)

    async with manager as creds:
        print(f"\n✓ Created user: {creds.username}")

        # Query effective permissions immediately after grant (BEFORE any container creation)
        # With template role inheritance, has_table_privilege() checks inherited permissions
        admin_url = synced_test_db.admin.url().replace("postgresql://", "postgresql+asyncpg://")
        admin_engine = create_async_engine(admin_url, echo=False)

        async with admin_engine.begin() as conn:
            # Check effective permissions via helper
            perms = await check_table_permissions_async(conn, creds.username, "reported_issues")
            print(f"  Effective permissions: {perms}")

            # Also check role membership (how permissions are inherited)
            result = await conn.execute(
                text(
                    """
                SELECT r.rolname as member_of
                FROM pg_auth_members m
                JOIN pg_roles r ON r.oid = m.roleid
                JOIN pg_roles u ON u.oid = m.member
                WHERE u.rolname = :username
                """
                ),
                {"username": creds.username},
            )
            memberships = [row[0] for row in result]
            print(f"  Role memberships: {memberships}")

        await admin_engine.dispose()

        assert perms.all_granted(), f"All permissions should be granted via template role: {perms}"
        assert "critic_agent_template" in memberships, "User should be member of critic_agent_template"


@pytest.mark.requires_postgres
async def test_admin_vs_temp_user_visibility(synced_test_db: DatabaseConfig, test_prompt_sha: str):
    """Priority 10: Admin vs temp user side-by-side comparison.

    Verifies both admin and temp user connections see the same effective permissions
    on reported_issues table. With template role inheritance, permissions come from
    the inherited role (critic_agent_template).
    """
    run_id = uuid4()

    # Create test critic run
    with get_session() as session:
        example = session.query(Example).first()
        assert example, "Need at least one example"

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        critic_run.id = run_id
        session.add(critic_run)
        session.commit()

    manager = CriticUserManager(synced_test_db.admin, run_id)

    async with manager as creds:
        print(f"\n✓ Created user: {creds.username}")

        # Admin perspective - check temp user's permissions from admin connection
        admin_url = synced_test_db.admin.url().replace("postgresql://", "postgresql+asyncpg://")
        admin_engine = create_async_engine(admin_url, echo=False)
        async with admin_engine.begin() as conn:
            admin_view_perms = await check_table_permissions_async(conn, creds.username, "reported_issues")
            print(f"  Admin sees temp user perms: {admin_view_perms}")
        await admin_engine.dispose()

        # Temp user perspective - check own permissions
        user_config = synced_test_db.admin.with_user(creds)
        user_url = user_config.url().replace("postgresql://", "postgresql+asyncpg://")
        user_engine = create_async_engine(user_url, echo=False)
        async with user_engine.begin() as conn:
            result = await conn.execute(text("SELECT current_user"))
            current_user = result.scalar()
            assert current_user is not None, "Expected current_user"
            temp_view_perms = await check_table_permissions_async(conn, current_user, "reported_issues")
            print(f"  Temp user sees own perms: {temp_view_perms}")
        await user_engine.dispose()

        # Both views should show same permissions
        print(f"\n  Comparison: admin_view={admin_view_perms}, temp_view={temp_view_perms}")
        assert admin_view_perms == temp_view_perms, "Admin and temp user should see same effective permissions"
        assert temp_view_perms.all_granted(), f"Temp user should have all permissions: {temp_view_perms}"


@pytest.mark.requires_postgres
@pytest.mark.requires_docker
async def test_docker_with_retry_loop(
    synced_test_db: DatabaseConfig, async_docker_client, test_specimens_hydrator, test_prompt_sha: str
):
    """Priority 3: Check for asynchronous replication lag.

    Tests if permissions eventually become visible in container (timing issue).
    """
    run_id = uuid4()
    snapshot_slug = SnapshotSlug("test-fixtures/test-trivial")
    scope = ExplicitFileScope(files=["add.py"])

    # Create test critic run
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=snapshot_slug).first()
        assert example

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        critic_run.id = run_id
        session.add(critic_run)
        session.commit()

    agent_env = CriticAgentEnvironment(
        snapshot_slug=snapshot_slug,
        docker_client=async_docker_client,
        hydrator=test_specimens_hydrator,
        critic_run_id=run_id,
        scope=scope,
        db_config=synced_test_db,
        mount_properties=False,
    )

    async with agent_env as compositor:
        # Execute Python with retry loop
        retry_script = """
import psycopg2
import time

conn = psycopg2.connect("")  # Uses PG* env vars

results = []
for attempt in range(10):
    cursor = conn.cursor()
    cursor.execute("SELECT has_table_privilege(current_user, 'reported_issues', 'INSERT')")
    perm = cursor.fetchone()[0]
    results.append(f"Attempt {attempt}: {perm}")
    print(f"Attempt {attempt}: INSERT permission = {perm}")
    if perm:
        print("SUCCESS: Permission found!")
        break
    time.sleep(0.5)
else:
    print("FAILURE: Permission never became visible")

conn.close()
"""

        async with Client(compositor.runtime.server) as client:
            result = await client.call_tool(
                "exec",
                {"cmd": ["python3", "-c", retry_script], "cwd": None, "env": None, "user": None, "timeout_ms": 15000},
            )

            if result.is_error:
                print("\n✗ Retry script failed:")
                print(result.content)
                pytest.fail(f"Retry script failed: {result.content}")

            output = result.structured_content
            exit_code = output["exit"]["exit_code"]

            stdout = output.get("stdout", "")
            stderr = output.get("stderr", "")

            print("\n=== Retry Loop Results ===")
            print("STDOUT:")
            print(stdout if stdout else "(empty)")
            print("\nSTDERR:")
            print(stderr if stderr else "(empty)")
            print(f"\nExit code: {exit_code}")

            if exit_code != 0:
                print(f"\n✗ Script failed with exit code {exit_code}")
                pytest.fail(f"Retry script failed: exit_code={exit_code}, stderr={stderr}")

            # Check if permission was EVER visible
            if "SUCCESS: Permission found!" in stdout:
                print("\n✓ CONCLUSION: Permission eventually became visible (timing/async issue)")
            elif "Attempt 0: True" in stdout:
                print("\n✓ CONCLUSION: Permission visible immediately (not a timing issue)")
            else:
                print("\n✗ CONCLUSION: Permission NEVER became visible (not a timing issue)")
                print(f"   Full output: {stdout[:500]}")  # First 500 chars
                pytest.fail("Permission never visible even with 5-second retry window")
