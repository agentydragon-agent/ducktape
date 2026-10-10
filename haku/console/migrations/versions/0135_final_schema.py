"""Frozen final Haku console schema, retaining deployed revision 0135.

A database already at 0135 applies nothing. Older deployed revisions must first
reach 0135 using the pre-squash image. Fresh databases create the final schema
without replaying intermediate data rewrites or retired tables.

DDL captured from the original chain in PostgreSQL 18 CI; see the adjacent
baseline test for its provenance and exact schema comparison. No runtime ORM
metadata is used. Specimen migration histories are independent and unchanged.
"""

from alembic import op
from sqlalchemy import text

revision: str = "0135"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()
    # Some frozen function bodies reference tables created later in the dump.
    check_bodies = conn.scalar(text("SHOW check_function_bodies"))
    op.execute("SET LOCAL check_function_bodies = false")
    # Execute the multi-statement DDL without DBAPI parameter interpolation:
    # function bodies contain literal percent signs and dollar quoting.
    conn.exec_driver_sql(_SCHEMA_SQL, execution_options={"no_parameters": True})
    conn.execute(text("SELECT set_config('check_function_bodies', :value, true)"), {"value": check_bodies})
    # The surviving logical index registration is bootstrap data, not DDL.
    # The deleted chat registration must not return with the squash.
    op.execute("INSERT INTO recall_index.indexes (index_id, index_type) VALUES ('haku-state', 'git')")


def downgrade() -> None:
    raise RuntimeError("0135 is the forward-only Haku console baseline")


# Frozen SQL, not generated from the live ORM at migration time.
_SCHEMA_SQL = r"""
-- Name: recall_index; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA recall_index;


--


--
-- Name: agent_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_status AS ENUM (
    'draft',
    'active',
    'abandoned',
    'disabled',
    'deleted'
);


--
-- Name: client_registration_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.client_registration_kind AS ENUM (
    'oauth_proxy_unclassified',
    'dcr',
    'cimd',
    'preregistered'
);


--
-- Name: credential_binding_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.credential_binding_status AS ENUM (
    'issuing',
    'issued',
    'active',
    'revoked',
    'expired',
    'failed'
);


--
-- Name: credential_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.credential_kind AS ENUM (
    'oauth',
    'static'
);


--
-- Name: enrollment_phase; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.enrollment_phase AS ENUM (
    'awaiting_browser',
    'awaiting_approval',
    'allowed',
    'exchanging',
    'completed',
    'denied',
    'expired',
    'failed'
);


--
-- Name: operator_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.operator_status AS ENUM (
    'active',
    'disabled'
);


--
-- Name: tool_call_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tool_call_status AS ENUM (
    'pending_approval',
    'running',
    'ok',
    'error',
    'denied',
    'withdrawn'
);


--
-- Name: haku_0009_agent_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_agent_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'draft' THEN
                    RAISE EXCEPTION 'activated Agent records are tombstoned, not deleted'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.agent_id, NEW.owner_operator_id, NEW.created_at)
                   IS DISTINCT FROM ROW(OLD.agent_id, OLD.owner_operator_id, OLD.created_at) THEN
                    RAISE EXCEPTION 'Agent identity and owner are immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF OLD.activated_at IS NOT NULL
                   AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
                    RAISE EXCEPTION 'Agent activation evidence is immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF OLD.last_seen_at IS NOT NULL
                   AND (NEW.last_seen_at IS NULL OR NEW.last_seen_at < OLD.last_seen_at) THEN
                    RAISE EXCEPTION 'Agent last-seen evidence is monotonic'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.status <> OLD.status AND NOT (
                    (OLD.status = 'draft' AND NEW.status = 'active')
                    OR (OLD.status = 'draft' AND NEW.status = 'abandoned')
                    OR (OLD.status = 'active' AND NEW.status IN ('disabled', 'deleted'))
                    OR (OLD.status = 'disabled' AND NEW.status = 'deleted')
                    OR (
                        OLD.status = 'disabled' AND NEW.status = 'active'
                        AND EXISTS (
                            SELECT 1 FROM credential_bindings
                            WHERE agent_id = NEW.agent_id
                              AND kind = 'static'
                              AND status = 'active'
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM credential_bindings
                            WHERE agent_id = NEW.agent_id AND kind <> 'static'
                        )
                    )
                ) THEN
                    RAISE EXCEPTION 'illegal Agent status transition: % -> %',
                        OLD.status, NEW.status USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_agent_name_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_agent_name_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            owning_agent_status TEXT;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.agent_id IS NOT NULL THEN
                    SELECT status::TEXT INTO owning_agent_status
                    FROM agents WHERE agent_id = OLD.agent_id;
                    IF owning_agent_status IS DISTINCT FROM 'draft' THEN
                        RAISE EXCEPTION 'activated and historical Agent names remain reserved'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'INSERT'
               AND NEW.originating_interaction_id IS NOT NULL
               AND NEW.pending_interaction_id IS NULL THEN
                RAISE EXCEPTION 'interaction-originated Agent names must begin as pending reservations'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.reservation_id, NEW.display_name, NEW.display_name_key,
                       NEW.originating_interaction_id, NEW.created_at)
                   IS DISTINCT FROM
                   ROW(OLD.reservation_id, OLD.display_name, OLD.display_name_key,
                       OLD.originating_interaction_id, OLD.created_at) THEN
                    RAISE EXCEPTION 'Agent display-name reservations are immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF ROW(NEW.pending_interaction_id, NEW.agent_id, NEW.activated_at)
                   IS DISTINCT FROM
                   ROW(OLD.pending_interaction_id, OLD.agent_id, OLD.activated_at)
                   AND NOT (
                       OLD.pending_interaction_id IS NOT NULL
                       AND OLD.agent_id IS NULL
                       AND OLD.activated_at IS NULL
                       AND NEW.pending_interaction_id IS NULL
                       AND NEW.agent_id IS NOT NULL
                       AND NEW.activated_at IS NOT NULL
                   ) THEN
                    RAISE EXCEPTION 'Agent name ownership may only transfer from interaction to Agent'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_assert_binding_activation(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_binding_activation(target_binding_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            binding_agent UUID;
            binding_status TEXT;
            binding_generation BIGINT;
            binding_predecessor UUID;
            agent_status TEXT;
            maximum_generation BIGINT;
            predecessor_status TEXT;
        BEGIN
            SELECT binding.agent_id, binding.status::TEXT, binding.generation,
                   binding.supersedes_binding_id, agent.status::TEXT
            INTO binding_agent, binding_status, binding_generation,
                 binding_predecessor, agent_status
            FROM credential_bindings AS binding
            JOIN agents AS agent ON agent.agent_id = binding.agent_id
            WHERE binding.binding_id = target_binding_id;
            IF NOT FOUND OR binding_status <> 'active' THEN
                RETURN;
            END IF;
            IF agent_status <> 'active' THEN
                RAISE EXCEPTION 'only an active Agent may own an active binding'
                    USING ERRCODE = '23514';
            END IF;
            SELECT max(generation) INTO maximum_generation
            FROM credential_bindings WHERE agent_id = binding_agent;
            IF binding_generation <> maximum_generation THEN
                RAISE EXCEPTION 'a stale binding generation cannot become active'
                    USING ERRCODE = '23514';
            END IF;
            IF binding_predecessor IS NULL THEN
                IF binding_generation <> 1 THEN
                    RAISE EXCEPTION 'an initial active binding must be generation one'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                SELECT status::TEXT INTO predecessor_status
                FROM credential_bindings WHERE binding_id = binding_predecessor;
                IF predecessor_status NOT IN ('revoked', 'expired', 'failed') THEN
                    RAISE EXCEPTION 'replacement activation must terminally close its predecessor'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
        END;
        $$;


--
-- Name: haku_0009_assert_binding_subtype(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_binding_subtype(target_binding_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            binding_kind TEXT;
            grant_count BIGINT;
            static_count BIGINT;
        BEGIN
            SELECT kind::TEXT INTO binding_kind
            FROM credential_bindings WHERE binding_id = target_binding_id;
            IF NOT FOUND THEN
                RETURN;
            END IF;
            SELECT count(*) INTO grant_count
            FROM authorization_grants WHERE binding_id = target_binding_id;
            SELECT count(*) INTO static_count
            FROM static_credentials WHERE binding_id = target_binding_id;
            IF (binding_kind = 'oauth' AND (grant_count <> 1 OR static_count <> 0))
               OR (binding_kind = 'static' AND (grant_count <> 0 OR static_count <> 1)) THEN
                RAISE EXCEPTION 'CredentialBinding must own exactly its enum-selected subtype'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;


--
-- Name: haku_0009_assert_correlation_reservation(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_correlation_reservation(target_interaction_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            reservation_count BIGINT;
        BEGIN
            SELECT count(*) INTO reservation_count
            FROM enrollment_correlation_reservations
            WHERE interaction_id = target_interaction_id;
            IF reservation_count <> 1 THEN
                RAISE EXCEPTION 'EnrollmentInteraction must own exactly one correlation reservation'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;


--
-- Name: haku_0009_assert_grant_consistency(uuid, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_grant_consistency(target_grant_id uuid, require_initial_state boolean) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            binding_kind TEXT;
            binding_status TEXT;
            binding_agent UUID;
            binding_generation BIGINT;
            binding_predecessor UUID;
            agent_owner UUID;
            agent_status TEXT;
            owner_status TEXT;
            authorizing_operator UUID;
            browser_operator UUID;
            grant_client UUID;
            interaction_client UUID;
            interaction_phase TEXT;
            reconnect_agent UUID;
            reconnect_binding UUID;
            reconnect_binding_kind TEXT;
            reconnect_binding_status TEXT;
            current_name_origin UUID;
            grant_interaction UUID;
            scopes_are_narrowed BOOLEAN;
        BEGIN
            SELECT binding.kind::TEXT,
                   binding.status::TEXT,
                   binding.agent_id,
                   binding.generation,
                   binding.supersedes_binding_id,
                   agent.owner_operator_id,
                   agent.status::TEXT,
                   owner.status::TEXT,
                   authorizing_anchor.operator_id,
                   browser_anchor.operator_id,
                   auth_grant.client_software_id,
                   interaction.client_software_id,
                   interaction.phase::TEXT,
                   interaction.reconnect_agent_id,
                   interaction.reconnect_predecessor_binding_id,
                   reconnect_predecessor.kind::TEXT,
                   reconnect_predecessor.status::TEXT,
                   current_name.originating_interaction_id,
                   interaction.interaction_id,
                   auth_grant.allowed_scopes <@ interaction.requested_scopes
            INTO binding_kind, binding_status, binding_agent, binding_generation, binding_predecessor,
                 agent_owner, agent_status, owner_status, authorizing_operator,
                 browser_operator, grant_client, interaction_client, interaction_phase,
                 reconnect_agent, reconnect_binding, reconnect_binding_kind,
                 reconnect_binding_status, current_name_origin, grant_interaction,
                 scopes_are_narrowed
            FROM authorization_grants AS auth_grant
            JOIN credential_bindings AS binding ON binding.binding_id = auth_grant.binding_id
            JOIN agents AS agent ON agent.agent_id = binding.agent_id
            JOIN agent_name_reservations AS current_name
              ON current_name.reservation_id = agent.current_name_reservation_id
            JOIN operators AS owner ON owner.operator_id = agent.owner_operator_id
            JOIN oidc_identities AS authorizing_identity
              ON authorizing_identity.identity_id = auth_grant.authorizing_identity_id
            JOIN identity_anchors AS authorizing_anchor
              ON authorizing_anchor.anchor_id = authorizing_identity.anchor_id
            JOIN enrollment_interactions AS interaction
              ON interaction.interaction_id = auth_grant.enrollment_interaction_id
            LEFT JOIN oidc_identities AS browser_identity
              ON browser_identity.identity_id = interaction.browser_identity_id
            LEFT JOIN identity_anchors AS browser_anchor
              ON browser_anchor.anchor_id = browser_identity.anchor_id
            LEFT JOIN credential_bindings AS reconnect_predecessor
              ON reconnect_predecessor.binding_id = interaction.reconnect_predecessor_binding_id
            WHERE auth_grant.grant_id = target_grant_id;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            IF binding_kind <> 'oauth' THEN
                RAISE EXCEPTION 'AuthorizationGrant requires an OAuth binding'
                    USING ERRCODE = '23514';
            END IF;
            IF require_initial_state AND binding_status <> 'issuing' THEN
                RAISE EXCEPTION 'AuthorizationGrant must begin on an issuing OAuth binding'
                    USING ERRCODE = '23514';
            END IF;
            IF owner_status <> 'active'
               OR authorizing_operator IS DISTINCT FROM agent_owner
               OR browser_operator IS DISTINCT FROM agent_owner THEN
                RAISE EXCEPTION 'grant, browser identity, and Agent must resolve to one active Operator'
                    USING ERRCODE = '23514';
            END IF;
            IF grant_client <> interaction_client THEN
                RAISE EXCEPTION 'grant client software must match its interaction'
                    USING ERRCODE = '23514';
            END IF;
            IF scopes_are_narrowed IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'grant scopes cannot broaden the requested client-facing scopes'
                    USING ERRCODE = '23514';
            END IF;
            IF interaction_phase NOT IN ('exchanging', 'completed', 'expired', 'failed') THEN
                RAISE EXCEPTION 'resulting grant requires an exchanging or closed interaction'
                    USING ERRCODE = '23514';
            END IF;

            IF reconnect_agent IS NULL THEN
                IF binding_predecessor IS NOT NULL OR binding_generation <> 1
                   OR current_name_origin IS DISTINCT FROM grant_interaction
                   OR agent_status NOT IN ('draft', 'active')
                   OR (require_initial_state AND agent_status <> 'draft') THEN
                    RAISE EXCEPTION 'create-new enrollment requires a draft Agent first binding'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF binding_agent <> reconnect_agent OR binding_predecessor <> reconnect_binding
                  OR reconnect_binding_kind <> 'oauth'
                  OR (require_initial_state AND reconnect_binding_status <> 'active')
                  OR agent_status <> 'active' THEN
                RAISE EXCEPTION 'reconnect grant must replace the selected binding on its active Agent'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;


--
-- Name: haku_0009_assert_interaction_aggregate(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_interaction_aggregate(target_interaction_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            interaction_phase TEXT;
            reconnect_agent UUID;
            reconnect_binding UUID;
            browser_operator UUID;
            reconnect_owner UUID;
            reconnect_status TEXT;
            reconnect_kind TEXT;
            pending_name_count BIGINT;
            grant_count BIGINT;
        BEGIN
            SELECT interaction.phase::TEXT,
                   interaction.reconnect_agent_id,
                   interaction.reconnect_predecessor_binding_id,
                   browser_anchor.operator_id
            INTO interaction_phase, reconnect_agent, reconnect_binding, browser_operator
            FROM enrollment_interactions AS interaction
            LEFT JOIN oidc_identities AS browser_identity
              ON browser_identity.identity_id = interaction.browser_identity_id
            LEFT JOIN identity_anchors AS browser_anchor
              ON browser_anchor.anchor_id = browser_identity.anchor_id
            WHERE interaction.interaction_id = target_interaction_id;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT count(*) INTO pending_name_count
            FROM agent_name_reservations
            WHERE pending_interaction_id = target_interaction_id;
            SELECT count(*) INTO grant_count
            FROM authorization_grants
            WHERE enrollment_interaction_id = target_interaction_id;

            IF interaction_phase IN ('awaiting_browser', 'awaiting_approval') THEN
                IF pending_name_count <> 0 OR grant_count <> 0 THEN
                    RAISE EXCEPTION 'pre-decision interaction cannot own a name or grant'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF interaction_phase = 'allowed' THEN
                IF grant_count <> 0 OR
                   ((reconnect_agent IS NULL AND pending_name_count <> 1)
                    OR (reconnect_agent IS NOT NULL AND pending_name_count <> 0)) THEN
                    RAISE EXCEPTION 'Allowed interaction must be exactly create-new or reconnect'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF interaction_phase IN ('exchanging', 'completed') THEN
                IF pending_name_count <> 0 OR grant_count <> 1 THEN
                    RAISE EXCEPTION 'exchanging/completed interaction must own one resulting grant'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF interaction_phase = 'denied' THEN
                IF pending_name_count <> 0 OR grant_count <> 0 THEN
                    RAISE EXCEPTION 'denied interaction cannot own a name or grant'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF interaction_phase IN ('expired', 'failed') THEN
                IF pending_name_count <> 0 OR grant_count > 1 THEN
                    RAISE EXCEPTION 'closed interaction cannot retain a pending name'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                RAISE EXCEPTION 'unknown EnrollmentInteraction phase: %', interaction_phase
                    USING ERRCODE = '23514';
            END IF;

            IF reconnect_agent IS NOT NULL THEN
                SELECT agent.owner_operator_id, binding.status::TEXT, binding.kind::TEXT
                INTO reconnect_owner, reconnect_status, reconnect_kind
                FROM agents AS agent
                JOIN credential_bindings AS binding
                  ON binding.agent_id = agent.agent_id
                 AND binding.binding_id = reconnect_binding
                WHERE agent.agent_id = reconnect_agent;
                IF NOT FOUND OR reconnect_owner IS DISTINCT FROM browser_operator THEN
                    RAISE EXCEPTION 'reconnect target must belong to the browser Operator'
                        USING ERRCODE = '23514';
                END IF;
                IF interaction_phase = 'allowed'
                   AND (reconnect_status <> 'active' OR reconnect_kind <> 'oauth') THEN
                    RAISE EXCEPTION 'new reconnect authorization must target an active OAuth binding'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
        END;
        $$;


--
-- Name: haku_0009_assert_name_promotion(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_name_promotion(target_reservation_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            origin_interaction UUID;
            pending_interaction UUID;
            owning_agent UUID;
            matching_grants BIGINT;
        BEGIN
            SELECT originating_interaction_id, pending_interaction_id, agent_id
            INTO origin_interaction, pending_interaction, owning_agent
            FROM agent_name_reservations
            WHERE reservation_id = target_reservation_id;
            IF NOT FOUND OR origin_interaction IS NULL OR pending_interaction IS NOT NULL THEN
                RETURN;
            END IF;
            SELECT count(*) INTO matching_grants
            FROM authorization_grants AS auth_grant
            JOIN credential_bindings AS binding ON binding.binding_id = auth_grant.binding_id
            WHERE auth_grant.enrollment_interaction_id = origin_interaction
              AND binding.agent_id = owning_agent;
            IF matching_grants <> 1 THEN
                RAISE EXCEPTION 'promoted Agent name must belong to its interaction resulting Agent'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;


--
-- Name: haku_0009_assert_tool_call_principal(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_assert_tool_call_principal(target_tool_call_id text) RETURNS void
    LANGUAGE plpgsql
    AS $$
        DECLARE
            principal_count BIGINT;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM mcp_tool_calls WHERE tool_call_id = target_tool_call_id
            ) THEN
                RETURN;
            END IF;
            SELECT count(*) INTO principal_count
            FROM mcp_tool_call_principals
            WHERE tool_call_id = target_tool_call_id;
            IF principal_count <> 1 THEN
                RAISE EXCEPTION 'every tool call must own exactly one ToolCallPrincipal'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;


--
-- Name: haku_0009_authorization_grant_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_authorization_grant_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF ROW(NEW.grant_id, NEW.binding_id, NEW.authorizing_identity_id,
                   NEW.client_software_id, NEW.enrollment_interaction_id,
                   NEW.allowed_scopes, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.grant_id, OLD.binding_id, OLD.authorizing_identity_id,
                   OLD.client_software_id, OLD.enrollment_interaction_id,
                   OLD.allowed_scopes, OLD.created_at) THEN
                RAISE EXCEPTION 'AuthorizationGrant provenance and scopes are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.initial_access_jti IS NOT NULL
               AND NEW.initial_access_jti IS DISTINCT FROM OLD.initial_access_jti THEN
                RAISE EXCEPTION 'initial access-token evidence cannot be changed or cleared'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.initial_refresh_jti IS NOT NULL
               AND NEW.initial_refresh_jti IS DISTINCT FROM OLD.initial_refresh_jti THEN
                RAISE EXCEPTION 'initial refresh-token evidence cannot be changed or cleared'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.token_family_persisted_at IS NOT NULL
               AND NEW.token_family_persisted_at IS DISTINCT FROM OLD.token_family_persisted_at THEN
                RAISE EXCEPTION 'token-family persistence evidence cannot be changed or cleared'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_agent_active_bindings(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_agent_active_bindings() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            active_binding UUID;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            IF NEW.status <> 'active' THEN
                SELECT binding_id INTO active_binding
                FROM credential_bindings
                WHERE agent_id = NEW.agent_id AND status = 'active'
                LIMIT 1;
                IF active_binding IS NOT NULL THEN
                    RAISE EXCEPTION 'non-active Agent cannot retain an active binding'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NEW.status = 'abandoned' AND (
                EXISTS (
                    SELECT 1 FROM credential_bindings
                    WHERE agent_id = NEW.agent_id
                      AND status NOT IN ('revoked', 'expired', 'failed')
                )
                OR NOT EXISTS (
                    SELECT 1 FROM credential_bindings
                    WHERE agent_id = NEW.agent_id
                      AND status IN ('revoked', 'expired', 'failed')
                )
            ) THEN
                RAISE EXCEPTION 'abandoned Agent requires terminal bindings and no live binding'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'draft' AND NEW.status = 'active'
               AND NOT EXISTS (
                   SELECT 1 FROM credential_bindings
                   WHERE agent_id = NEW.agent_id AND status = 'active'
               ) THEN
                RAISE EXCEPTION 'first verified use must activate Agent and binding atomically'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_aggregate_from_grant(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_aggregate_from_grant() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM haku_0009_assert_interaction_aggregate(OLD.enrollment_interaction_id);
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_interaction_aggregate(NEW.enrollment_interaction_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_aggregate_from_interaction(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_aggregate_from_interaction() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_interaction_aggregate(NEW.interaction_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_aggregate_from_name(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_aggregate_from_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            target_interaction_id UUID;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_interaction_id := OLD.pending_interaction_id;
            ELSIF NEW.pending_interaction_id IS NOT NULL THEN
                target_interaction_id := NEW.pending_interaction_id;
            ELSE
                target_interaction_id := OLD.pending_interaction_id;
            END IF;
            IF target_interaction_id IS NOT NULL THEN
                PERFORM haku_0009_assert_interaction_aggregate(target_interaction_id);
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_binding_activation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_binding_activation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_binding_activation(NEW.binding_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_grant_consistency(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_grant_consistency() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_grant_consistency(NEW.grant_id, TG_OP = 'INSERT');
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_name_promotion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_name_promotion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP <> 'DELETE' THEN
                PERFORM haku_0009_assert_name_promotion(NEW.reservation_id);
                RETURN NEW;
            END IF;
            RETURN OLD;
        END;
        $$;


--
-- Name: haku_0009_check_new_interaction_correlation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_new_interaction_correlation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            PERFORM haku_0009_assert_correlation_reservation(NEW.interaction_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_principal_from_call(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_principal_from_call() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_tool_call_principal(NEW.tool_call_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_principal_from_principal(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_principal_from_principal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM haku_0009_assert_tool_call_principal(OLD.tool_call_id);
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_tool_call_principal(NEW.tool_call_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_subtype_from_binding(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_subtype_from_binding() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM haku_0009_assert_binding_subtype(OLD.binding_id);
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_binding_subtype(NEW.binding_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_subtype_from_grant(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_subtype_from_grant() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM haku_0009_assert_binding_subtype(OLD.binding_id);
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_binding_subtype(NEW.binding_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_check_subtype_from_static(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_check_subtype_from_static() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM haku_0009_assert_binding_subtype(OLD.binding_id);
                RETURN OLD;
            END IF;
            PERFORM haku_0009_assert_binding_subtype(NEW.binding_id);
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_client_software_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_client_software_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            redirect_uri TEXT;
        BEGIN
            FOREACH redirect_uri IN ARRAY NEW.validated_redirect_uris LOOP
                IF btrim(redirect_uri) = '' THEN
                    RAISE EXCEPTION 'validated redirect URIs must be non-empty'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            IF cardinality(NEW.validated_redirect_uris) <>
               (SELECT count(DISTINCT item) FROM unnest(NEW.validated_redirect_uris) AS item) THEN
                RAISE EXCEPTION 'validated redirect URIs must not contain duplicates'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND
               ROW(NEW.client_software_id, NEW.registration_kind, NEW.oauth_client_id, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.client_software_id, OLD.registration_kind, OLD.oauth_client_id, OLD.created_at) THEN
                RAISE EXCEPTION 'ClientSoftware registration identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_correlation_reservation_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_correlation_reservation_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF clock_timestamp() < OLD.release_after THEN
                    RAISE EXCEPTION 'correlation reservation cannot be released before its tombstone expiry'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF ROW(NEW.interaction_id, NEW.client_id, NEW.redirect_uri,
                   NEW.code_challenge, NEW.release_after)
               IS DISTINCT FROM
               ROW(OLD.interaction_id, OLD.client_id, OLD.redirect_uri,
                   OLD.code_challenge, OLD.release_after) THEN
                RAISE EXCEPTION 'correlation reservation is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_credential_binding_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_credential_binding_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            predecessor_agent_id UUID;
            predecessor_kind TEXT;
            predecessor_generation BIGINT;
        BEGIN
            PERFORM 1 FROM agents WHERE agent_id = NEW.agent_id FOR UPDATE;
            IF NEW.supersedes_binding_id IS NOT NULL THEN
                SELECT agent_id, kind::TEXT, generation
                INTO predecessor_agent_id, predecessor_kind, predecessor_generation
                FROM credential_bindings
                WHERE binding_id = NEW.supersedes_binding_id;
                IF NOT FOUND
                   OR predecessor_agent_id <> NEW.agent_id
                   OR predecessor_kind <> NEW.kind::TEXT
                   OR predecessor_generation >= NEW.generation THEN
                    RAISE EXCEPTION 'binding predecessor must be an older binding of the same Agent and kind'
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.binding_id, NEW.agent_id, NEW.kind, NEW.generation,
                       NEW.supersedes_binding_id, NEW.created_at)
                   IS DISTINCT FROM
                   ROW(OLD.binding_id, OLD.agent_id, OLD.kind, OLD.generation,
                       OLD.supersedes_binding_id, OLD.created_at) THEN
                    RAISE EXCEPTION 'CredentialBinding identity and lineage are immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.status <> OLD.status AND NOT (
                    (OLD.status = 'issuing' AND NEW.status IN ('issued', 'expired', 'failed'))
                    OR (OLD.status = 'issued' AND NEW.status IN ('active', 'revoked', 'expired', 'failed'))
                    OR (OLD.status = 'active' AND NEW.status IN ('revoked', 'expired'))
                ) THEN
                    RAISE EXCEPTION 'illegal CredentialBinding status transition: % -> %',
                        OLD.status, NEW.status USING ERRCODE = '23514';
                END IF;
                IF OLD.issued_at IS NOT NULL
                   AND NEW.issued_at IS DISTINCT FROM OLD.issued_at THEN
                    RAISE EXCEPTION 'binding issuance evidence is immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF OLD.activated_at IS NOT NULL
                   AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
                    RAISE EXCEPTION 'binding activation evidence is immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF OLD.ended_at IS NOT NULL
                   AND ROW(NEW.ended_at, NEW.end_reason)
                       IS DISTINCT FROM ROW(OLD.ended_at, OLD.end_reason) THEN
                    RAISE EXCEPTION 'binding terminal evidence is immutable'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_enrollment_interaction_delete_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_enrollment_interaction_delete_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF clock_timestamp() < OLD.correlation_release_after THEN
                RAISE EXCEPTION 'EnrollmentInteraction cannot be deleted before correlation release'
                    USING ERRCODE = '23514';
            END IF;
            RETURN OLD;
        END;
        $$;


--
-- Name: haku_0009_enrollment_interaction_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_enrollment_interaction_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            redirect_is_valid BOOLEAN;
        BEGIN
            SELECT NEW.redirect_uri = ANY(client.validated_redirect_uris)
            INTO redirect_is_valid
            FROM client_software AS client
            WHERE client.client_software_id = NEW.client_software_id
              AND client.oauth_client_id = NEW.client_id;
            IF redirect_is_valid IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'interaction redirect URI was not validated for its client software'
                    USING ERRCODE = '23514';
            END IF;

            IF TG_OP = 'INSERT' THEN
                IF NEW.phase <> 'awaiting_browser' THEN
                    RAISE EXCEPTION 'EnrollmentInteraction must begin in awaiting_browser'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF ROW(NEW.interaction_id, NEW.client_software_id, NEW.client_id,
                   NEW.redirect_uri, NEW.code_challenge, NEW.requested_scopes,
                   NEW.presentation_snapshot, NEW.upstream_authorization_url,
                   NEW.expires_at, NEW.correlation_release_after, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.interaction_id, OLD.client_software_id, OLD.client_id,
                   OLD.redirect_uri, OLD.code_challenge, OLD.requested_scopes,
                   OLD.presentation_snapshot, OLD.upstream_authorization_url,
                   OLD.expires_at, OLD.correlation_release_after, OLD.created_at) THEN
                RAISE EXCEPTION 'EnrollmentInteraction correlation and presentation are immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.phase <> OLD.phase AND NOT (
                (OLD.phase = 'awaiting_browser' AND NEW.phase IN ('awaiting_approval', 'expired', 'failed'))
                OR (OLD.phase = 'awaiting_approval' AND NEW.phase IN ('allowed', 'denied', 'expired', 'failed'))
                OR (OLD.phase = 'allowed' AND NEW.phase IN ('exchanging', 'expired', 'failed'))
                OR (OLD.phase = 'exchanging' AND NEW.phase IN ('completed', 'expired', 'failed'))
            ) THEN
                RAISE EXCEPTION 'illegal EnrollmentInteraction phase transition: % -> %',
                    OLD.phase, NEW.phase USING ERRCODE = '23514';
            END IF;

            IF OLD.browser_nonce_digest IS NULL AND NEW.browser_nonce_digest IS NOT NULL THEN
                RAISE EXCEPTION 'consumed browser nonce cannot be restored'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.browser_nonce_digest IS NOT NULL
               AND NEW.browser_nonce_digest IS NOT NULL
               AND NEW.browser_nonce_digest IS DISTINCT FROM OLD.browser_nonce_digest THEN
                RAISE EXCEPTION 'browser nonce cannot be replaced'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.browser_identity_id IS NOT NULL
               AND NEW.browser_identity_id IS DISTINCT FROM OLD.browser_identity_id THEN
                RAISE EXCEPTION 'browser identity is immutable once established'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.browser_identity_id IS NULL AND NEW.browser_identity_id IS NOT NULL
               AND NOT (OLD.phase = 'awaiting_browser' AND NEW.phase = 'awaiting_approval') THEN
                RAISE EXCEPTION 'browser identity may only be established on browser arrival'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.browser_binding_digest IS NULL AND NEW.browser_binding_digest IS NOT NULL
               AND NOT (OLD.phase = 'awaiting_browser' AND NEW.phase = 'awaiting_approval') THEN
                RAISE EXCEPTION 'consumed browser binding cannot be restored'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.browser_binding_digest IS NOT NULL
               AND NEW.browser_binding_digest IS NOT NULL
               AND NEW.browser_binding_digest IS DISTINCT FROM OLD.browser_binding_digest THEN
                RAISE EXCEPTION 'browser binding cannot be replaced'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.browser_binding_digest IS NOT NULL AND NEW.browser_binding_digest IS NULL
               AND NEW.phase NOT IN ('completed', 'denied', 'expired', 'failed') THEN
                RAISE EXCEPTION 'browser binding may only be cleared in a terminal phase'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.decision_digest IS NOT NULL
               AND NEW.decision_digest IS DISTINCT FROM OLD.decision_digest THEN
                RAISE EXCEPTION 'enrollment decision is immutable once recorded'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.decision_digest IS NULL AND NEW.decision_digest IS NOT NULL
               AND NOT (OLD.phase = 'awaiting_approval' AND NEW.phase IN ('allowed', 'denied')) THEN
                RAISE EXCEPTION 'decision may only be recorded by an allow or deny transition'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.reconnect_agent_id IS NOT NULL AND
               ROW(NEW.reconnect_agent_id, NEW.reconnect_predecessor_binding_id)
               IS DISTINCT FROM
               ROW(OLD.reconnect_agent_id, OLD.reconnect_predecessor_binding_id) THEN
                RAISE EXCEPTION 'reconnect target is immutable once selected'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.reconnect_agent_id IS NULL AND NEW.reconnect_agent_id IS NOT NULL
               AND NOT (OLD.phase = 'awaiting_approval' AND NEW.phase = 'allowed') THEN
                RAISE EXCEPTION 'reconnect target may only be selected when allowing enrollment'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.closed_at IS NOT NULL AND
               ROW(NEW.closed_at, NEW.closure_reason)
               IS DISTINCT FROM ROW(OLD.closed_at, OLD.closure_reason) THEN
                RAISE EXCEPTION 'closed interaction metadata is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_identity_anchor_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_identity_anchor_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF ROW(NEW.anchor_id, NEW.operator_id, NEW.trust_domain,
                   NEW.stable_external_user_key, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.anchor_id, OLD.operator_id, OLD.trust_domain,
                   OLD.stable_external_user_key, OLD.created_at) THEN
                RAISE EXCEPTION 'IdentityAnchor identity and Operator link are immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_lock_grant_authority(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_lock_grant_authority() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
            target_operator UUID;
        BEGIN
            SELECT agent.owner_operator_id INTO target_operator
            FROM credential_bindings AS binding
            JOIN agents AS agent ON agent.agent_id = binding.agent_id
            WHERE binding.binding_id = NEW.binding_id
            FOR UPDATE OF agent;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'AuthorizationGrant binding must exist before grant creation'
                    USING ERRCODE = '23503';
            END IF;
            PERFORM 1 FROM operators WHERE operator_id = target_operator FOR UPDATE;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_oidc_identity_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_oidc_identity_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF ROW(NEW.identity_id, NEW.anchor_id, NEW.issuer, NEW.subject, NEW.first_seen_at)
               IS DISTINCT FROM
               ROW(OLD.identity_id, OLD.anchor_id, OLD.issuer, OLD.subject, OLD.first_seen_at) THEN
                RAISE EXCEPTION 'OidcIdentity provenance and IdentityAnchor link are immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0009_static_credential_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_static_credential_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            RAISE EXCEPTION 'StaticCredential rows are immutable; rotate the binding instead'
                USING ERRCODE = '23514';
        END;
        $$;


--
-- Name: haku_0009_tool_call_principal_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0009_tool_call_principal_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF ROW(NEW.tool_call_id, NEW.operator_id, NEW.binding_id)
               IS DISTINCT FROM ROW(OLD.tool_call_id, OLD.operator_id, OLD.binding_id) THEN
                RAISE EXCEPTION 'ToolCallPrincipal provenance is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;


--
-- Name: haku_0113_kubernetes_grant_source_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0113_kubernetes_grant_source_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Shape is enforced independently by ck_kubernetes_grants_principal_shape.
    -- Let that constraint report malformed relational combinations instead of
    -- misclassifying them as source-provenance failures in this BEFORE trigger.
    IF NOT (
        (NEW.principal_kind = 'agent'
         AND NEW.principal_agent_id IS NOT NULL
         AND NEW.principal_agent_id = NEW.owner_agent_id
         AND NEW.principal_session_id IS NULL)
        OR
        (NEW.principal_kind = 'session'
         AND NEW.principal_agent_id IS NULL
         AND NEW.principal_session_id IS NOT NULL)
    ) THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.mcp_tool_calls AS call
        JOIN public.mcp_tool_call_principals AS request_principal
          ON request_principal.tool_call_id = call.tool_call_id
        JOIN public.credential_bindings AS binding
          ON binding.binding_id = request_principal.binding_id
        JOIN public.agents AS agent
          ON agent.agent_id = binding.agent_id
        WHERE call.tool_call_id = NEW.source_tool_call_id
          AND binding.agent_id = NEW.owner_agent_id
          AND agent.status NOT IN ('abandoned', 'deleted')
          AND call.server_id IN ('kubernetes', 'grants')
          AND call.tool_name = 'create_grant'
          AND call.status IN ('running', 'ok')
          AND call.approved_at IS NOT NULL
          AND call.approval_policy_id IS NULL
          AND (
            (NEW.principal_kind = 'agent'
             AND NEW.principal_agent_id = binding.agent_id)
            OR
            (NEW.principal_kind = 'session'
             AND request_principal.session_id IS NOT NULL
             AND NEW.principal_session_id = request_principal.session_id
             AND EXISTS (
               SELECT 1
               FROM public.sessions AS source_session
               WHERE source_session.session_id = request_principal.session_id
                 AND source_session.agent_binding_id = request_principal.binding_id
                 AND source_session.ended_at IS NULL
                 AND source_session.close_requested_at IS NULL
                 AND source_session.bridge_connected_at IS NOT NULL
                 AND source_session.lease_expires_at > statement_timestamp()
             ))
          )
    ) THEN
        RAISE EXCEPTION 'invalid Kubernetes grant source provenance or principal'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'ck_kubernetes_grants_source_provenance';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: haku_0119_kubernetes_grant_source_invariants(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haku_0119_kubernetes_grant_source_invariants() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NOT (
        (NEW.principal_kind = 'agent'
         AND NEW.principal_access_profile_id IS NULL)
        OR
        (NEW.principal_kind = 'access_profile'
         AND NEW.principal_agent_id IS NULL
         AND NEW.principal_access_profile_id IS NOT NULL)
    ) THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.mcp_tool_calls AS call
        JOIN public.mcp_tool_call_principals AS request_principal
          ON request_principal.tool_call_id = call.tool_call_id
        JOIN public.credential_bindings AS binding
          ON binding.binding_id = request_principal.binding_id
        JOIN public.agents AS agent
          ON agent.agent_id = binding.agent_id
        WHERE call.tool_call_id = NEW.source_tool_call_id
          AND binding.agent_id = NEW.owner_agent_id
          AND agent.status NOT IN ('abandoned', 'deleted')
          AND call.server_id IN ('kubernetes', 'grants')
          AND call.tool_name = 'create_grant'
          AND call.status IN ('running', 'ok')
          AND call.approved_at IS NOT NULL
          AND call.approval_policy_id IS NULL
          AND (
            (NEW.principal_kind = 'agent'
             AND EXISTS (
               SELECT 1
               FROM public.agents AS target_agent
               WHERE target_agent.agent_id = NEW.principal_agent_id
                 AND target_agent.status NOT IN ('abandoned', 'deleted')
             ))
            OR
            (NEW.principal_kind = 'access_profile'
             AND NEW.principal_access_profile_id IS NOT NULL)
          )
    ) THEN
        RAISE EXCEPTION 'invalid Kubernetes grant source provenance or principal'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'ck_kubernetes_grants_source_provenance';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: prevent_conversation_identity_update(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_conversation_identity_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
            BEGIN
                IF NEW.agent_id IS DISTINCT FROM OLD.agent_id
                   OR NEW.access_profile_id IS DISTINCT FROM OLD.access_profile_id
                   OR NEW.harness_kind IS DISTINCT FROM OLD.harness_kind THEN
                    RAISE EXCEPTION 'conversation identity is immutable';
                END IF;
                RETURN NEW;
            END;
            $$;


SET LOCAL default_tablespace = '';

SET LOCAL default_table_access_method = heap;

--
-- Name: agent_name_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_name_reservations (
    reservation_id uuid NOT NULL,
    display_name text NOT NULL,
    display_name_key text NOT NULL,
    originating_interaction_id uuid,
    pending_interaction_id uuid,
    agent_id uuid,
    created_at timestamp with time zone NOT NULL,
    activated_at timestamp with time zone,
    CONSTRAINT ck_agent_name_reservations_activation_shape CHECK (((agent_id IS NULL) = (activated_at IS NULL))),
    CONSTRAINT ck_agent_name_reservations_display_name_length CHECK ((char_length(display_name) <= 80)),
    CONSTRAINT ck_agent_name_reservations_display_name_nonempty CHECK ((display_name ~ U&'[^[:space:][:cntrl:]\00a0\1680\2000-\200a\2028\2029\202f\205f\3000\feff]'::text)),
    CONSTRAINT ck_agent_name_reservations_exactly_one_owner CHECK ((num_nonnulls(pending_interaction_id, agent_id) = 1)),
    CONSTRAINT ck_agent_name_reservations_key_nonempty CHECK ((display_name_key ~ U&'[^[:space:][:cntrl:]\00a0\1680\2000-\200a\2028\2029\202f\205f\3000\feff]'::text)),
    CONSTRAINT ck_agent_name_reservations_pending_origin CHECK (((pending_interaction_id IS NULL) OR (originating_interaction_id = pending_interaction_id)))
);


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    agent_id uuid NOT NULL,
    owner_operator_id uuid NOT NULL,
    current_name_reservation_id uuid NOT NULL,
    status public.agent_status NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    activated_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    auto_approval_policy text,
    access_profile_id text,
    CONSTRAINT ck_agents_access_profile_id_nonempty CHECK (((access_profile_id IS NULL) OR (btrim(access_profile_id) <> ''::text))),
    CONSTRAINT ck_agents_status_shape CHECK ((((status = 'draft'::public.agent_status) AND (activated_at IS NULL)) OR ((status = 'abandoned'::public.agent_status) AND (activated_at IS NULL)) OR ((status = ANY (ARRAY['active'::public.agent_status, 'disabled'::public.agent_status, 'deleted'::public.agent_status])) AND (activated_at IS NOT NULL))))
);


--
-- Name: authorization_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.authorization_grants (
    grant_id uuid NOT NULL,
    binding_id uuid NOT NULL,
    authorizing_identity_id uuid NOT NULL,
    client_software_id uuid NOT NULL,
    enrollment_interaction_id uuid NOT NULL,
    allowed_scopes text[] NOT NULL,
    initial_access_jti text,
    initial_refresh_jti text,
    token_family_persisted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_authorization_grants_allowed_scopes_no_null CHECK ((array_position(allowed_scopes, NULL::text) IS NULL)),
    CONSTRAINT ck_authorization_grants_token_family_evidence_shape CHECK ((((token_family_persisted_at IS NULL) AND (initial_access_jti IS NULL) AND (initial_refresh_jti IS NULL)) OR ((token_family_persisted_at IS NOT NULL) AND (initial_access_jti IS NOT NULL) AND (btrim(initial_access_jti) <> ''::text) AND ((initial_refresh_jti IS NULL) OR (btrim(initial_refresh_jti) <> ''::text)))))
);


--
-- Name: client_software; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.client_software (
    client_software_id uuid NOT NULL,
    registration_kind public.client_registration_kind NOT NULL,
    oauth_client_id text NOT NULL,
    validated_redirect_uris text[] NOT NULL,
    metadata_hash bytea NOT NULL,
    observed_name text,
    observed_icon_uri text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_client_software_metadata_hash_nonempty CHECK ((octet_length(metadata_hash) > 0)),
    CONSTRAINT ck_client_software_oauth_client_id_nonempty CHECK ((btrim(oauth_client_id) <> ''::text)),
    CONSTRAINT ck_client_software_validated_redirect_uris_no_null CHECK ((array_position(validated_redirect_uris, NULL::text) IS NULL)),
    CONSTRAINT ck_client_software_validated_redirect_uris_nonempty CHECK ((cardinality(validated_redirect_uris) > 0))
);


--
-- Name: credential_bindings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credential_bindings (
    binding_id uuid NOT NULL,
    agent_id uuid NOT NULL,
    kind public.credential_kind NOT NULL,
    status public.credential_binding_status NOT NULL,
    generation bigint NOT NULL,
    supersedes_binding_id uuid,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    issued_at timestamp with time zone,
    activated_at timestamp with time zone,
    ended_at timestamp with time zone,
    end_reason text,
    CONSTRAINT ck_credential_bindings_generation_positive CHECK ((generation > 0)),
    CONSTRAINT ck_credential_bindings_status_shape CHECK ((((status = 'issuing'::public.credential_binding_status) AND (issued_at IS NULL) AND (activated_at IS NULL) AND (ended_at IS NULL) AND (end_reason IS NULL)) OR ((status = 'issued'::public.credential_binding_status) AND (issued_at IS NOT NULL) AND (activated_at IS NULL) AND (ended_at IS NULL) AND (end_reason IS NULL)) OR ((status = 'active'::public.credential_binding_status) AND (issued_at IS NOT NULL) AND (activated_at IS NOT NULL) AND (ended_at IS NULL) AND (end_reason IS NULL)) OR ((status = ANY (ARRAY['revoked'::public.credential_binding_status, 'expired'::public.credential_binding_status, 'failed'::public.credential_binding_status])) AND (ended_at IS NOT NULL) AND (end_reason IS NOT NULL) AND (btrim(end_reason) <> ''::text)))),
    CONSTRAINT ck_credential_bindings_timestamp_order CHECK ((((issued_at IS NULL) OR (issued_at >= created_at)) AND ((activated_at IS NULL) OR ((issued_at IS NOT NULL) AND (activated_at >= issued_at))) AND ((ended_at IS NULL) OR (ended_at >= COALESCE(activated_at, issued_at, created_at)))))
);


--
-- Name: enrollment_correlation_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enrollment_correlation_reservations (
    interaction_id uuid NOT NULL,
    client_id text NOT NULL,
    redirect_uri text NOT NULL,
    code_challenge text NOT NULL,
    release_after timestamp with time zone NOT NULL
);


--
-- Name: enrollment_interactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.enrollment_interactions (
    interaction_id uuid NOT NULL,
    client_software_id uuid NOT NULL,
    client_id text NOT NULL,
    redirect_uri text NOT NULL,
    code_challenge text NOT NULL,
    requested_scopes text[] NOT NULL,
    presentation_snapshot jsonb NOT NULL,
    upstream_authorization_url text NOT NULL,
    phase public.enrollment_phase NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    correlation_release_after timestamp with time zone NOT NULL,
    browser_nonce_digest bytea,
    browser_identity_id uuid,
    browser_binding_digest bytea,
    decision_digest bytea,
    reconnect_agent_id uuid,
    reconnect_predecessor_binding_id uuid,
    closure_reason text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    closed_at timestamp with time zone,
    auto_approval_policy text,
    access_profile_id text,
    CONSTRAINT ck_enrollment_interactions_access_profile_id_nonempty CHECK (((access_profile_id IS NULL) OR (btrim(access_profile_id) <> ''::text))),
    CONSTRAINT ck_enrollment_interactions_browser_binding_shape CHECK (((browser_binding_digest IS NULL) OR (browser_identity_id IS NOT NULL))),
    CONSTRAINT ck_enrollment_interactions_client_id_nonempty CHECK ((btrim(client_id) <> ''::text)),
    CONSTRAINT ck_enrollment_interactions_code_challenge_nonempty CHECK ((btrim(code_challenge) <> ''::text)),
    CONSTRAINT ck_enrollment_interactions_correlation_outlives_interaction CHECK ((correlation_release_after > expires_at)),
    CONSTRAINT ck_enrollment_interactions_phase_shape CHECK ((((phase = 'awaiting_browser'::public.enrollment_phase) AND (browser_nonce_digest IS NOT NULL) AND (browser_identity_id IS NULL) AND (decision_digest IS NULL) AND (reconnect_agent_id IS NULL) AND (closed_at IS NULL) AND (closure_reason IS NULL)) OR ((phase = 'awaiting_approval'::public.enrollment_phase) AND (browser_nonce_digest IS NULL) AND (browser_identity_id IS NOT NULL) AND (browser_binding_digest IS NOT NULL) AND (decision_digest IS NULL) AND (reconnect_agent_id IS NULL) AND (closed_at IS NULL) AND (closure_reason IS NULL)) OR ((phase = ANY (ARRAY['allowed'::public.enrollment_phase, 'exchanging'::public.enrollment_phase])) AND (browser_nonce_digest IS NULL) AND (browser_identity_id IS NOT NULL) AND (browser_binding_digest IS NOT NULL) AND (decision_digest IS NOT NULL) AND (closed_at IS NULL) AND (closure_reason IS NULL)) OR ((phase = 'completed'::public.enrollment_phase) AND (browser_nonce_digest IS NULL) AND (browser_identity_id IS NOT NULL) AND (browser_binding_digest IS NULL) AND (decision_digest IS NOT NULL) AND (closed_at IS NOT NULL) AND (closure_reason IS NOT NULL) AND (btrim(closure_reason) <> ''::text)) OR ((phase = 'denied'::public.enrollment_phase) AND (browser_nonce_digest IS NULL) AND (browser_identity_id IS NOT NULL) AND (browser_binding_digest IS NULL) AND (decision_digest IS NOT NULL) AND (reconnect_agent_id IS NULL) AND (closed_at IS NOT NULL) AND (closure_reason IS NOT NULL) AND (btrim(closure_reason) <> ''::text)) OR ((phase = ANY (ARRAY['expired'::public.enrollment_phase, 'failed'::public.enrollment_phase])) AND (browser_nonce_digest IS NULL) AND (browser_binding_digest IS NULL) AND (closed_at IS NOT NULL) AND (closure_reason IS NOT NULL) AND (btrim(closure_reason) <> ''::text)))),
    CONSTRAINT ck_enrollment_interactions_reconnect_shape CHECK (((reconnect_agent_id IS NULL) = (reconnect_predecessor_binding_id IS NULL))),
    CONSTRAINT ck_enrollment_interactions_redirect_uri_nonempty CHECK ((btrim(redirect_uri) <> ''::text)),
    CONSTRAINT ck_enrollment_interactions_requested_scopes_no_null CHECK ((array_position(requested_scopes, NULL::text) IS NULL)),
    CONSTRAINT ck_enrollment_interactions_upstream_url_nonempty CHECK ((btrim(upstream_authorization_url) <> ''::text))
);


--
-- Name: identity_anchors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.identity_anchors (
    anchor_id uuid NOT NULL,
    operator_id uuid NOT NULL,
    trust_domain text NOT NULL,
    stable_external_user_key text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_identity_anchors_external_key_nonempty CHECK ((btrim(stable_external_user_key) <> ''::text)),
    CONSTRAINT ck_identity_anchors_trust_domain_nonempty CHECK ((btrim(trust_domain) <> ''::text))
);


--
-- Name: kubernetes_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kubernetes_grants (
    grant_id uuid NOT NULL,
    owner_agent_id uuid CONSTRAINT kubernetes_grants_agent_id_not_null NOT NULL,
    source_tool_call_id text NOT NULL,
    scope jsonb NOT NULL,
    rules jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone,
    end_reason text,
    principal_kind text NOT NULL,
    principal_agent_id uuid,
    principal_access_profile_id text,
    ended_at timestamp with time zone,
    CONSTRAINT ck_kubernetes_grants_end_shape CHECK ((((ended_at IS NOT NULL) OR (end_reason IS NULL)) AND ((end_reason IS NULL) OR (btrim(end_reason) <> ''::text)))),
    CONSTRAINT ck_kubernetes_grants_expiration_after_creation CHECK (((expires_at IS NULL) OR (expires_at > created_at))),
    CONSTRAINT ck_kubernetes_grants_principal_shape CHECK ((((principal_kind = 'agent'::text) AND (principal_agent_id IS NOT NULL) AND (principal_access_profile_id IS NULL)) OR ((principal_kind = 'access_profile'::text) AND (principal_agent_id IS NULL) AND (principal_access_profile_id IS NOT NULL)))),
    CONSTRAINT ck_kubernetes_grants_rules_nonempty CHECK (((jsonb_typeof(rules) = 'array'::text) AND (jsonb_array_length(rules) > 0))),
    CONSTRAINT ck_kubernetes_grants_scope_shape CHECK (((jsonb_typeof(scope) = 'object'::text) AND (scope ? 'kind'::text) AND ((scope ->> 'kind'::text) = ANY (ARRAY['namespaces'::text, 'all_namespaces'::text, 'cluster'::text, 'non_resource'::text])) AND ((((scope ->> 'kind'::text) = 'namespaces'::text) AND (scope ? 'namespaces'::text) AND (jsonb_typeof((scope -> 'namespaces'::text)) = 'array'::text) AND (jsonb_array_length((scope -> 'namespaces'::text)) > 0)) OR (((scope ->> 'kind'::text) <> 'namespaces'::text) AND (NOT (scope ? 'namespaces'::text)))))),
    CONSTRAINT ck_kubernetes_grants_source_tool_call_nonempty CHECK ((btrim(source_tool_call_id) <> ''::text))
);


--
-- Name: mcp_tool_call_principals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mcp_tool_call_principals (
    tool_call_id text NOT NULL,
    operator_id uuid,
    binding_id uuid,
    session_id uuid,
    CONSTRAINT ck_mcp_tool_call_principals_exactly_one_variant CHECK ((num_nonnulls(operator_id, binding_id) = 1)),
    CONSTRAINT ck_mcp_tool_call_principals_session_agent CHECK (((session_id IS NULL) OR (binding_id IS NOT NULL)))
);


--
-- Name: mcp_tool_calls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mcp_tool_calls (
    tool_call_id text NOT NULL,
    server_id text NOT NULL,
    tool_name text NOT NULL,
    status public.tool_call_status NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    arguments_json jsonb NOT NULL,
    rationale text NOT NULL,
    title text,
    result_json jsonb,
    error text,
    approval_policy_id text,
    auto_approval_evaluation text,
    approved_at timestamp with time zone,
    withdrawal_reason text,
    decision_note text,
    decision_operator_id uuid,
    CONSTRAINT ck_mcp_tool_calls_decision_note_length CHECK (((decision_note IS NULL) OR (char_length(decision_note) <= 4096)))
);


--
-- Name: oidc_identities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oidc_identities (
    identity_id uuid NOT NULL,
    anchor_id uuid NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_oidc_identities_issuer_nonempty CHECK ((btrim(issuer) <> ''::text)),
    CONSTRAINT ck_oidc_identities_subject_nonempty CHECK ((btrim(subject) <> ''::text))
);


--
-- Name: operator_login_flows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_login_flows (
    state text NOT NULL,
    browser_binding text NOT NULL,
    return_to text,
    data jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_operator_login_flows_browser_binding_nonempty CHECK ((btrim(browser_binding) <> ''::text))
);


--
-- Name: operators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operators (
    operator_id uuid NOT NULL,
    status public.operator_status NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: push_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_subscriptions (
    endpoint text NOT NULL,
    operator_id uuid NOT NULL,
    p256dh text NOT NULL,
    auth text NOT NULL,
    user_agent text,
    created_at timestamp with time zone NOT NULL,
    last_failure_at timestamp with time zone
);


--
-- Name: static_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.static_credentials (
    binding_id uuid NOT NULL,
    secret_reference text NOT NULL,
    credential_fingerprint bytea NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_static_credentials_fingerprint_nonempty CHECK ((octet_length(credential_fingerprint) > 0)),
    CONSTRAINT ck_static_credentials_secret_reference_nonempty CHECK ((btrim(secret_reference) <> ''::text))
);


--
-- Name: content_embeddings; Type: TABLE; Schema: recall_index; Owner: -
--

CREATE TABLE recall_index.content_embeddings (
    content_sha text NOT NULL,
    model_key text NOT NULL,
    embedding public.halfvec NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: contents; Type: TABLE; Schema: recall_index; Owner: -
--

CREATE TABLE recall_index.contents (
    content_sha text NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: git_chunks; Type: TABLE; Schema: recall_index; Owner: -
--

CREATE TABLE recall_index.git_chunks (
    blob_sha text NOT NULL,
    chunker_key text NOT NULL,
    byte_start bigint NOT NULL,
    byte_end bigint NOT NULL,
    content_sha text NOT NULL,
    index_id text NOT NULL
);


--
-- Name: git_sync_state; Type: TABLE; Schema: recall_index; Owner: -
--

CREATE TABLE recall_index.git_sync_state (
    branch text NOT NULL,
    remote_commit text,
    remote_seen_at timestamp with time zone,
    commit_sha text,
    chunker_key text,
    synced_at timestamp with time zone,
    index_id text NOT NULL,
    CONSTRAINT ck_git_sync_state_indexed_half CHECK ((((commit_sha IS NULL) = (chunker_key IS NULL)) AND ((commit_sha IS NULL) = (synced_at IS NULL))))
);


--
-- Name: git_tip; Type: TABLE; Schema: recall_index; Owner: -
--

CREATE TABLE recall_index.git_tip (
    path text NOT NULL,
    blob_sha text NOT NULL,
    index_id text NOT NULL
);


--
-- Name: indexes; Type: TABLE; Schema: recall_index; Owner: -
--

CREATE TABLE recall_index.indexes (
    index_id text NOT NULL,
    index_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_indexes_index_type CHECK ((index_type = 'git'::text))
);


--
-- Name: agent_name_reservations agent_name_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT agent_name_reservations_pkey PRIMARY KEY (reservation_id);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (agent_id);


--
-- Name: authorization_grants authorization_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT authorization_grants_pkey PRIMARY KEY (grant_id);


--
-- Name: client_software client_software_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_software
    ADD CONSTRAINT client_software_pkey PRIMARY KEY (client_software_id);


--
-- Name: credential_bindings credential_bindings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_bindings
    ADD CONSTRAINT credential_bindings_pkey PRIMARY KEY (binding_id);


--
-- Name: enrollment_correlation_reservations enrollment_correlation_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_correlation_reservations
    ADD CONSTRAINT enrollment_correlation_reservations_pkey PRIMARY KEY (interaction_id);


--
-- Name: enrollment_interactions enrollment_interactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_interactions
    ADD CONSTRAINT enrollment_interactions_pkey PRIMARY KEY (interaction_id);


--
-- Name: identity_anchors identity_anchors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identity_anchors
    ADD CONSTRAINT identity_anchors_pkey PRIMARY KEY (anchor_id);


--
-- Name: kubernetes_grants kubernetes_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kubernetes_grants
    ADD CONSTRAINT kubernetes_grants_pkey PRIMARY KEY (grant_id);


--
-- Name: mcp_tool_call_principals mcp_tool_call_principals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_tool_call_principals
    ADD CONSTRAINT mcp_tool_call_principals_pkey PRIMARY KEY (tool_call_id);


--
-- Name: mcp_tool_calls mcp_tool_calls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_pkey PRIMARY KEY (tool_call_id);


--
-- Name: oidc_identities oidc_identities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_identities
    ADD CONSTRAINT oidc_identities_pkey PRIMARY KEY (identity_id);


--
-- Name: operator_login_flows operator_login_flows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_login_flows
    ADD CONSTRAINT operator_login_flows_pkey PRIMARY KEY (state);


--
-- Name: operators operators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operators
    ADD CONSTRAINT operators_pkey PRIMARY KEY (operator_id);


--
-- Name: push_subscriptions push_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pkey PRIMARY KEY (endpoint);


--
-- Name: static_credentials static_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.static_credentials
    ADD CONSTRAINT static_credentials_pkey PRIMARY KEY (binding_id);


--
-- Name: agent_name_reservations uq_agent_name_reservations_agent_reservation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT uq_agent_name_reservations_agent_reservation UNIQUE (agent_id, reservation_id);


--
-- Name: agent_name_reservations uq_agent_name_reservations_display_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT uq_agent_name_reservations_display_name_key UNIQUE (display_name_key);


--
-- Name: agent_name_reservations uq_agent_name_reservations_pending_interaction; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT uq_agent_name_reservations_pending_interaction UNIQUE (pending_interaction_id);


--
-- Name: authorization_grants uq_authorization_grants_binding_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT uq_authorization_grants_binding_id UNIQUE (binding_id);


--
-- Name: authorization_grants uq_authorization_grants_enrollment_interaction_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT uq_authorization_grants_enrollment_interaction_id UNIQUE (enrollment_interaction_id);


--
-- Name: client_software uq_client_software_id_oauth_client_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_software
    ADD CONSTRAINT uq_client_software_id_oauth_client_id UNIQUE (client_software_id, oauth_client_id);


--
-- Name: client_software uq_client_software_oauth_client_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_software
    ADD CONSTRAINT uq_client_software_oauth_client_id UNIQUE (oauth_client_id);


--
-- Name: credential_bindings uq_credential_bindings_agent_binding; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_bindings
    ADD CONSTRAINT uq_credential_bindings_agent_binding UNIQUE (agent_id, binding_id);


--
-- Name: credential_bindings uq_credential_bindings_agent_generation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_bindings
    ADD CONSTRAINT uq_credential_bindings_agent_generation UNIQUE (agent_id, generation);


--
-- Name: enrollment_correlation_reservations uq_enrollment_correlation_reservations_tuple; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_correlation_reservations
    ADD CONSTRAINT uq_enrollment_correlation_reservations_tuple UNIQUE (client_id, redirect_uri, code_challenge);


--
-- Name: enrollment_interactions uq_enrollment_interactions_correlation_component; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_interactions
    ADD CONSTRAINT uq_enrollment_interactions_correlation_component UNIQUE (interaction_id, client_id, redirect_uri, code_challenge, correlation_release_after);


--
-- Name: identity_anchors uq_identity_anchors_trust_domain_external_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identity_anchors
    ADD CONSTRAINT uq_identity_anchors_trust_domain_external_key UNIQUE (trust_domain, stable_external_user_key);


--
-- Name: oidc_identities uq_oidc_identities_issuer_subject; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_identities
    ADD CONSTRAINT uq_oidc_identities_issuer_subject UNIQUE (issuer, subject);


--
-- Name: static_credentials uq_static_credentials_fingerprint; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.static_credentials
    ADD CONSTRAINT uq_static_credentials_fingerprint UNIQUE (credential_fingerprint);


--
-- Name: content_embeddings content_embeddings_pkey; Type: CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.content_embeddings
    ADD CONSTRAINT content_embeddings_pkey PRIMARY KEY (content_sha, model_key);


--
-- Name: contents contents_pkey; Type: CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.contents
    ADD CONSTRAINT contents_pkey PRIMARY KEY (content_sha);


--
-- Name: git_chunks git_chunks_pkey; Type: CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_chunks
    ADD CONSTRAINT git_chunks_pkey PRIMARY KEY (index_id, blob_sha, chunker_key, byte_start);


--
-- Name: git_sync_state git_sync_state_pkey; Type: CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_sync_state
    ADD CONSTRAINT git_sync_state_pkey PRIMARY KEY (index_id);


--
-- Name: git_tip git_tip_pkey; Type: CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_tip
    ADD CONSTRAINT git_tip_pkey PRIMARY KEY (index_id, path);


--
-- Name: indexes indexes_pkey; Type: CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.indexes
    ADD CONSTRAINT indexes_pkey PRIMARY KEY (index_id);


--
-- Name: idx_agent_name_reservations_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_name_reservations_agent_id ON public.agent_name_reservations USING btree (agent_id);


--
-- Name: idx_agents_owner_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agents_owner_operator_id ON public.agents USING btree (owner_operator_id);


--
-- Name: idx_authorization_grants_authorizing_identity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorization_grants_authorizing_identity_id ON public.authorization_grants USING btree (authorizing_identity_id);


--
-- Name: idx_authorization_grants_client_software_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorization_grants_client_software_id ON public.authorization_grants USING btree (client_software_id);


--
-- Name: idx_credential_bindings_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credential_bindings_agent_id ON public.credential_bindings USING btree (agent_id);


--
-- Name: idx_enrollment_interactions_client_software_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enrollment_interactions_client_software_id ON public.enrollment_interactions USING btree (client_software_id);


--
-- Name: idx_enrollment_interactions_phase_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_enrollment_interactions_phase_expires_at ON public.enrollment_interactions USING btree (phase, expires_at);


--
-- Name: idx_identity_anchors_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_identity_anchors_operator_id ON public.identity_anchors USING btree (operator_id);


--
-- Name: idx_kubernetes_grants_access_profile_principal_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kubernetes_grants_access_profile_principal_expiry ON public.kubernetes_grants USING btree (principal_access_profile_id, expires_at);


--
-- Name: idx_kubernetes_grants_agent_principal_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kubernetes_grants_agent_principal_expiry ON public.kubernetes_grants USING btree (principal_agent_id, expires_at);


--
-- Name: idx_kubernetes_grants_owner_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kubernetes_grants_owner_expiry ON public.kubernetes_grants USING btree (owner_agent_id, expires_at);


--
-- Name: idx_kubernetes_grants_source_tool_call; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kubernetes_grants_source_tool_call ON public.kubernetes_grants USING btree (source_tool_call_id);


--
-- Name: idx_mcp_tool_call_principals_binding_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_tool_call_principals_binding_id ON public.mcp_tool_call_principals USING btree (binding_id);


--
-- Name: idx_mcp_tool_call_principals_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_tool_call_principals_operator_id ON public.mcp_tool_call_principals USING btree (operator_id);


--
-- Name: idx_mcp_tool_call_principals_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_tool_call_principals_session_id ON public.mcp_tool_call_principals USING btree (session_id);


--
-- Name: idx_mcp_tool_calls_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_tool_calls_created_at ON public.mcp_tool_calls USING btree (created_at);


--
-- Name: idx_oidc_identities_anchor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oidc_identities_anchor_id ON public.oidc_identities USING btree (anchor_id);


--
-- Name: idx_operator_login_flows_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_operator_login_flows_expires_at ON public.operator_login_flows USING btree (expires_at);


--
-- Name: idx_push_subscriptions_operator_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_push_subscriptions_operator_id ON public.push_subscriptions USING btree (operator_id);


--
-- Name: uq_credential_bindings_one_active_per_agent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_credential_bindings_one_active_per_agent ON public.credential_bindings USING btree (agent_id) WHERE (status = 'active'::public.credential_binding_status);


--
-- Name: agents ctrg_haku_0009_agent_active_bindings; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_agent_active_bindings AFTER INSERT OR UPDATE ON public.agents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_agent_active_bindings();


--
-- Name: credential_bindings ctrg_haku_0009_binding_activation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_binding_activation AFTER INSERT OR UPDATE ON public.credential_bindings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_binding_activation();


--
-- Name: credential_bindings ctrg_haku_0009_binding_subtype; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_binding_subtype AFTER INSERT OR DELETE OR UPDATE ON public.credential_bindings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_subtype_from_binding();


--
-- Name: mcp_tool_calls ctrg_haku_0009_call_has_principal; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_call_has_principal AFTER INSERT OR UPDATE ON public.mcp_tool_calls DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_principal_from_call();


--
-- Name: authorization_grants ctrg_haku_0009_grant_consistency; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_grant_consistency AFTER INSERT OR UPDATE ON public.authorization_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_grant_consistency();


--
-- Name: authorization_grants ctrg_haku_0009_grant_interaction_aggregate; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_grant_interaction_aggregate AFTER INSERT OR DELETE OR UPDATE ON public.authorization_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_aggregate_from_grant();


--
-- Name: authorization_grants ctrg_haku_0009_grant_subtype; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_grant_subtype AFTER INSERT OR DELETE OR UPDATE ON public.authorization_grants DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_subtype_from_grant();


--
-- Name: enrollment_interactions ctrg_haku_0009_interaction_aggregate; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_interaction_aggregate AFTER INSERT OR UPDATE ON public.enrollment_interactions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_aggregate_from_interaction();


--
-- Name: agent_name_reservations ctrg_haku_0009_name_interaction_aggregate; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_name_interaction_aggregate AFTER INSERT OR DELETE OR UPDATE ON public.agent_name_reservations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_aggregate_from_name();


--
-- Name: agent_name_reservations ctrg_haku_0009_name_promotion; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_name_promotion AFTER INSERT OR UPDATE ON public.agent_name_reservations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_name_promotion();


--
-- Name: enrollment_interactions ctrg_haku_0009_new_interaction_has_correlation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_new_interaction_has_correlation AFTER INSERT ON public.enrollment_interactions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_new_interaction_correlation();


--
-- Name: mcp_tool_call_principals ctrg_haku_0009_principal_has_call; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_principal_has_call AFTER INSERT OR DELETE OR UPDATE ON public.mcp_tool_call_principals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_principal_from_principal();


--
-- Name: static_credentials ctrg_haku_0009_static_subtype; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_haku_0009_static_subtype AFTER INSERT OR DELETE OR UPDATE ON public.static_credentials DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haku_0009_check_subtype_from_static();


--
-- Name: agents trg_haku_0009_agent_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_agent_invariants BEFORE INSERT OR DELETE OR UPDATE ON public.agents FOR EACH ROW EXECUTE FUNCTION public.haku_0009_agent_invariants();


--
-- Name: agent_name_reservations trg_haku_0009_agent_name_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_agent_name_invariants BEFORE INSERT OR DELETE OR UPDATE ON public.agent_name_reservations FOR EACH ROW EXECUTE FUNCTION public.haku_0009_agent_name_invariants();


--
-- Name: authorization_grants trg_haku_0009_authorization_grant_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_authorization_grant_immutable BEFORE UPDATE ON public.authorization_grants FOR EACH ROW EXECUTE FUNCTION public.haku_0009_authorization_grant_immutable();


--
-- Name: client_software trg_haku_0009_client_software_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_client_software_invariants BEFORE INSERT OR UPDATE ON public.client_software FOR EACH ROW EXECUTE FUNCTION public.haku_0009_client_software_invariants();


--
-- Name: enrollment_correlation_reservations trg_haku_0009_correlation_reservation_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_correlation_reservation_invariants BEFORE DELETE OR UPDATE ON public.enrollment_correlation_reservations FOR EACH ROW EXECUTE FUNCTION public.haku_0009_correlation_reservation_invariants();


--
-- Name: credential_bindings trg_haku_0009_credential_binding_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_credential_binding_invariants BEFORE INSERT OR UPDATE ON public.credential_bindings FOR EACH ROW EXECUTE FUNCTION public.haku_0009_credential_binding_invariants();


--
-- Name: enrollment_interactions trg_haku_0009_enrollment_interaction_delete_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_enrollment_interaction_delete_guard BEFORE DELETE ON public.enrollment_interactions FOR EACH ROW EXECUTE FUNCTION public.haku_0009_enrollment_interaction_delete_guard();


--
-- Name: enrollment_interactions trg_haku_0009_enrollment_interaction_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_enrollment_interaction_invariants BEFORE INSERT OR UPDATE ON public.enrollment_interactions FOR EACH ROW EXECUTE FUNCTION public.haku_0009_enrollment_interaction_invariants();


--
-- Name: identity_anchors trg_haku_0009_identity_anchor_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_identity_anchor_immutable BEFORE UPDATE ON public.identity_anchors FOR EACH ROW EXECUTE FUNCTION public.haku_0009_identity_anchor_immutable();


--
-- Name: authorization_grants trg_haku_0009_lock_grant_authority; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_lock_grant_authority BEFORE INSERT OR UPDATE ON public.authorization_grants FOR EACH ROW EXECUTE FUNCTION public.haku_0009_lock_grant_authority();


--
-- Name: oidc_identities trg_haku_0009_oidc_identity_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_oidc_identity_immutable BEFORE UPDATE ON public.oidc_identities FOR EACH ROW EXECUTE FUNCTION public.haku_0009_oidc_identity_immutable();


--
-- Name: static_credentials trg_haku_0009_static_credential_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_static_credential_immutable BEFORE UPDATE ON public.static_credentials FOR EACH ROW EXECUTE FUNCTION public.haku_0009_static_credential_immutable();


--
-- Name: mcp_tool_call_principals trg_haku_0009_tool_call_principal_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0009_tool_call_principal_immutable BEFORE UPDATE ON public.mcp_tool_call_principals FOR EACH ROW EXECUTE FUNCTION public.haku_0009_tool_call_principal_immutable();


--
-- Name: kubernetes_grants trg_haku_0119_kubernetes_grant_source_invariants; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_haku_0119_kubernetes_grant_source_invariants BEFORE INSERT OR UPDATE OF owner_agent_id, principal_kind, principal_agent_id, principal_access_profile_id, source_tool_call_id ON public.kubernetes_grants FOR EACH ROW EXECUTE FUNCTION public.haku_0119_kubernetes_grant_source_invariants();


--
-- Name: agent_name_reservations agent_name_reservations_originating_interaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT agent_name_reservations_originating_interaction_id_fkey FOREIGN KEY (originating_interaction_id) REFERENCES public.enrollment_interactions(interaction_id) ON DELETE RESTRICT;


--
-- Name: agent_name_reservations agent_name_reservations_pending_interaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT agent_name_reservations_pending_interaction_id_fkey FOREIGN KEY (pending_interaction_id) REFERENCES public.enrollment_interactions(interaction_id) ON DELETE RESTRICT;


--
-- Name: agents agents_owner_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_owner_operator_id_fkey FOREIGN KEY (owner_operator_id) REFERENCES public.operators(operator_id) ON DELETE RESTRICT;


--
-- Name: authorization_grants authorization_grants_authorizing_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT authorization_grants_authorizing_identity_id_fkey FOREIGN KEY (authorizing_identity_id) REFERENCES public.oidc_identities(identity_id) ON DELETE RESTRICT;


--
-- Name: authorization_grants authorization_grants_client_software_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT authorization_grants_client_software_id_fkey FOREIGN KEY (client_software_id) REFERENCES public.client_software(client_software_id) ON DELETE RESTRICT;


--
-- Name: authorization_grants authorization_grants_enrollment_interaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT authorization_grants_enrollment_interaction_id_fkey FOREIGN KEY (enrollment_interaction_id) REFERENCES public.enrollment_interactions(interaction_id) ON DELETE RESTRICT;


--
-- Name: credential_bindings credential_bindings_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_bindings
    ADD CONSTRAINT credential_bindings_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id) ON DELETE RESTRICT;


--
-- Name: enrollment_interactions enrollment_interactions_browser_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_interactions
    ADD CONSTRAINT enrollment_interactions_browser_identity_id_fkey FOREIGN KEY (browser_identity_id) REFERENCES public.oidc_identities(identity_id) ON DELETE RESTRICT;


--
-- Name: agent_name_reservations fk_agent_name_reservations_agent; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_name_reservations
    ADD CONSTRAINT fk_agent_name_reservations_agent FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: agents fk_agents_owned_current_name; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT fk_agents_owned_current_name FOREIGN KEY (agent_id, current_name_reservation_id) REFERENCES public.agent_name_reservations(agent_id, reservation_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: authorization_grants fk_authorization_grants_binding; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorization_grants
    ADD CONSTRAINT fk_authorization_grants_binding FOREIGN KEY (binding_id) REFERENCES public.credential_bindings(binding_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: credential_bindings fk_credential_bindings_same_agent_predecessor; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_bindings
    ADD CONSTRAINT fk_credential_bindings_same_agent_predecessor FOREIGN KEY (agent_id, supersedes_binding_id) REFERENCES public.credential_bindings(agent_id, binding_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: enrollment_correlation_reservations fk_enrollment_correlation_reservations_exact_interaction; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_correlation_reservations
    ADD CONSTRAINT fk_enrollment_correlation_reservations_exact_interaction FOREIGN KEY (interaction_id, client_id, redirect_uri, code_challenge, release_after) REFERENCES public.enrollment_interactions(interaction_id, client_id, redirect_uri, code_challenge, correlation_release_after) ON DELETE CASCADE;


--
-- Name: enrollment_interactions fk_enrollment_interactions_exact_client_software; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_interactions
    ADD CONSTRAINT fk_enrollment_interactions_exact_client_software FOREIGN KEY (client_software_id, client_id) REFERENCES public.client_software(client_software_id, oauth_client_id) ON DELETE RESTRICT;


--
-- Name: enrollment_interactions fk_enrollment_interactions_reconnect_predecessor; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.enrollment_interactions
    ADD CONSTRAINT fk_enrollment_interactions_reconnect_predecessor FOREIGN KEY (reconnect_agent_id, reconnect_predecessor_binding_id) REFERENCES public.credential_bindings(agent_id, binding_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: mcp_tool_calls fk_mcp_tool_calls_decision_operator; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_tool_calls
    ADD CONSTRAINT fk_mcp_tool_calls_decision_operator FOREIGN KEY (decision_operator_id) REFERENCES public.operators(operator_id) ON DELETE RESTRICT;


--
-- Name: static_credentials fk_static_credentials_binding; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.static_credentials
    ADD CONSTRAINT fk_static_credentials_binding FOREIGN KEY (binding_id) REFERENCES public.credential_bindings(binding_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: identity_anchors identity_anchors_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identity_anchors
    ADD CONSTRAINT identity_anchors_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.operators(operator_id) ON DELETE RESTRICT;


--
-- Name: kubernetes_grants kubernetes_grants_owner_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kubernetes_grants
    ADD CONSTRAINT kubernetes_grants_owner_agent_id_fkey FOREIGN KEY (owner_agent_id) REFERENCES public.agents(agent_id) ON DELETE RESTRICT;


--
-- Name: kubernetes_grants kubernetes_grants_principal_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kubernetes_grants
    ADD CONSTRAINT kubernetes_grants_principal_agent_id_fkey FOREIGN KEY (principal_agent_id) REFERENCES public.agents(agent_id) ON DELETE RESTRICT;


--
-- Name: kubernetes_grants kubernetes_grants_source_tool_call_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kubernetes_grants
    ADD CONSTRAINT kubernetes_grants_source_tool_call_id_fkey FOREIGN KEY (source_tool_call_id) REFERENCES public.mcp_tool_calls(tool_call_id) ON DELETE RESTRICT;


--
-- Name: mcp_tool_call_principals mcp_tool_call_principals_binding_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_tool_call_principals
    ADD CONSTRAINT mcp_tool_call_principals_binding_id_fkey FOREIGN KEY (binding_id) REFERENCES public.credential_bindings(binding_id) ON DELETE RESTRICT;


--
-- Name: mcp_tool_call_principals mcp_tool_call_principals_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_tool_call_principals
    ADD CONSTRAINT mcp_tool_call_principals_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.operators(operator_id) ON DELETE RESTRICT;


--
-- Name: mcp_tool_call_principals mcp_tool_call_principals_tool_call_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_tool_call_principals
    ADD CONSTRAINT mcp_tool_call_principals_tool_call_id_fkey FOREIGN KEY (tool_call_id) REFERENCES public.mcp_tool_calls(tool_call_id) ON DELETE CASCADE;


--
-- Name: oidc_identities oidc_identities_anchor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_identities
    ADD CONSTRAINT oidc_identities_anchor_id_fkey FOREIGN KEY (anchor_id) REFERENCES public.identity_anchors(anchor_id) ON DELETE RESTRICT;


--
-- Name: push_subscriptions push_subscriptions_operator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_operator_id_fkey FOREIGN KEY (operator_id) REFERENCES public.operators(operator_id) ON DELETE CASCADE;


--
-- Name: content_embeddings content_embeddings_content_sha_fkey; Type: FK CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.content_embeddings
    ADD CONSTRAINT content_embeddings_content_sha_fkey FOREIGN KEY (content_sha) REFERENCES recall_index.contents(content_sha);


--
-- Name: git_chunks git_chunks_content_sha_fkey; Type: FK CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_chunks
    ADD CONSTRAINT git_chunks_content_sha_fkey FOREIGN KEY (content_sha) REFERENCES recall_index.contents(content_sha);


--
-- Name: git_chunks git_chunks_index_id_fkey; Type: FK CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_chunks
    ADD CONSTRAINT git_chunks_index_id_fkey FOREIGN KEY (index_id) REFERENCES recall_index.indexes(index_id);


--
-- Name: git_sync_state git_sync_state_index_id_fkey; Type: FK CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_sync_state
    ADD CONSTRAINT git_sync_state_index_id_fkey FOREIGN KEY (index_id) REFERENCES recall_index.indexes(index_id);


--
-- Name: git_tip git_tip_index_id_fkey; Type: FK CONSTRAINT; Schema: recall_index; Owner: -
--

ALTER TABLE ONLY recall_index.git_tip
    ADD CONSTRAINT git_tip_index_id_fkey FOREIGN KEY (index_id) REFERENCES recall_index.indexes(index_id);


--
-- PostgreSQL database dump complete
--
"""
