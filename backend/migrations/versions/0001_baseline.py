"""baseline – full initial schema from docs/DB_SCHEMA.sql

Revision ID: 0001
Revises:
Create Date: 2026-05-31

This migration captures the schema as it existed before Alembic was introduced.
All statements are wrapped in IF NOT EXISTS / DO $$ guards so that running
``alembic upgrade head`` against an already-bootstrapped database is safe.

To mark an existing database as already at this revision without executing the
DDL, run:

    alembic stamp 0001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Helper: execute raw SQL, tolerating "already exists" errors so the migration
# stays idempotent when applied to an already-bootstrapped database.
# ---------------------------------------------------------------------------

_DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===== Enums =====
DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('operator', 'admin', 'security_admin', 'system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE event_status AS ENUM ('draft', 'active', 'archived');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE auth_mode AS ENUM ('oauth_token', 'api_key', 'relay_secret');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE checkin_result AS ENUM (
    'checked_in',
    'already_checked_in',
    'queued_offline',
    'invalid_ticket',
    'outside_block_window',
    'error'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE scan_source AS ENUM ('operator_ui', 'manual_override', 'relay', 'wix_mobile', 'reconciliation');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE scan_processing_status AS ENUM ('accepted', 'rejected', 'queued', 'synced', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE queue_state AS ENUM ('pending', 'in_progress', 'synced', 'dead_letter', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE attempt_channel AS ENUM ('live_api', 'worker_retry', 'reconciliation');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE relay_status AS ENUM ('enabled', 'disabled', 'degraded');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE run_status AS ENUM ('running', 'completed', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE scanner_health AS ENUM ('connected', 'disconnected', 'unresponsive', 'unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE backend_health AS ENUM ('green', 'yellow', 'red');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE ticket_manifest_state AS ENUM ('active', 'checked_in', 'cancelled', 'void', 'stale');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE credential_audit_action AS ENUM ('create', 'update', 'rotate', 'test', 'refresh', 'read_denied');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE action_outcome AS ENUM ('success', 'failure');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE credential_lifecycle_state AS ENUM (
    'created', 'validated', 'active', 'expiring_soon',
    'rotation_pending', 'revoked', 'failed'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE binding_status AS ENUM ('pending', 'verified', 'unverified', 'revoked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE app_installation_status AS ENUM (
    'pending_install', 'installed', 'uninstalled', 'failed'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE event_readiness_status AS ENUM ('ready', 'degraded', 'critical');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE reconciliation_state AS ENUM (
    'in_sync', 'local_pending', 'local_only', 'wix_only', 'conflict'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ===== Users / RBAC =====
CREATE TABLE IF NOT EXISTS app_user (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_subject TEXT UNIQUE,
  email TEXT UNIQUE,
  display_name TEXT NOT NULL,
  role user_role NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===== Event configuration =====
CREATE TABLE IF NOT EXISTS event (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wix_event_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL,
  status event_status NOT NULL DEFAULT 'draft',
  allow_block_overlap BOOLEAN NOT NULL DEFAULT FALSE,
  sync_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sync_interval_seconds INTEGER NOT NULL DEFAULT 120,
  created_by UUID REFERENCES app_user(id),
  updated_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT event_sync_interval_seconds_chk CHECK (sync_interval_seconds BETWEEN 30 AND 900)
);

CREATE TABLE IF NOT EXISTS event_block (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  block_code TEXT NOT NULL,
  name TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ NOT NULL,
  grace_period_minutes INTEGER NOT NULL DEFAULT 0,
  allow_overlap BOOLEAN NOT NULL DEFAULT FALSE,
  priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID REFERENCES app_user(id),
  updated_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT event_block_window_chk CHECK (starts_at < ends_at),
  CONSTRAINT event_block_grace_chk CHECK (grace_period_minutes BETWEEN 0 AND 120),
  CONSTRAINT event_block_unique_code UNIQUE (event_id, block_code)
);

CREATE TABLE IF NOT EXISTS event_config_version (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  config_snapshot JSONB NOT NULL,
  created_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT event_config_version_unique UNIQUE (event_id, version_number)
);

-- ===== Wix site-event binding verification =====
CREATE TABLE IF NOT EXISTS wix_site_event_binding (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  wix_site_id TEXT NOT NULL,
  wix_event_id TEXT NOT NULL,
  binding_id TEXT,
  status binding_status NOT NULL DEFAULT 'pending',
  app_installation_status app_installation_status NOT NULL DEFAULT 'pending_install',
  binding_verified_at TIMESTAMPTZ,
  scopes_verified_at TIMESTAMPTZ,
  last_verification_error TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_by UUID REFERENCES app_user(id),
  updated_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT wix_binding_unique_event UNIQUE (event_id, wix_site_id, wix_event_id)
);

CREATE INDEX IF NOT EXISTS idx_wix_site_event_binding_event_status
  ON wix_site_event_binding (event_id, status);

-- ===== Wix app scope verification =====
CREATE TABLE IF NOT EXISTS wix_app_scope (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id UUID NOT NULL REFERENCES wix_site_event_binding(id) ON DELETE CASCADE,
  scope TEXT NOT NULL,
  is_required BOOLEAN NOT NULL DEFAULT TRUE,
  verified_at TIMESTAMPTZ,
  verification_failed_at TIMESTAMPTZ,
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT wix_app_scope_unique UNIQUE (binding_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_wix_app_scope_binding_verified
  ON wix_app_scope (binding_id, verified_at DESC);

CREATE TABLE IF NOT EXISTS event_ticket_manifest (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  ticket_number TEXT NOT NULL,
  wix_ticket_id TEXT,
  ticket_holder_hash TEXT,
  manifest_state ticket_manifest_state NOT NULL DEFAULT 'active',
  last_synced_at TIMESTAMPTZ,
  source_revision TEXT,
  last_seen_scan_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT event_ticket_manifest_unique_event_ticket UNIQUE (event_id, ticket_number),
  CONSTRAINT event_ticket_manifest_ticket_not_blank_chk CHECK (length(trim(ticket_number)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_event_ticket_manifest_event_state
  ON event_ticket_manifest (event_id, manifest_state);
CREATE INDEX IF NOT EXISTS idx_event_ticket_manifest_event_updated_at
  ON event_ticket_manifest (event_id, updated_at DESC);

-- ===== Scanner sessions and scan events =====
CREATE TABLE IF NOT EXISTS scan_session (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID REFERENCES event(id),
  operator_id UUID REFERENCES app_user(id),
  relay_id UUID,
  station_id TEXT,
  station_label TEXT,
  client_info JSONB,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS scan_event (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_event_id UUID NOT NULL UNIQUE,
  event_id UUID NOT NULL REFERENCES event(id),
  block_id UUID REFERENCES event_block(id),
  session_id UUID REFERENCES scan_session(id),
  source scan_source NOT NULL,
  ticket_number TEXT NOT NULL,
  qr_payload TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  processing_status scan_processing_status NOT NULL DEFAULT 'accepted',
  rejection_reason TEXT,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  CONSTRAINT scan_event_ticket_not_blank_chk CHECK (length(trim(ticket_number)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_scan_event_event_ticket ON scan_event (event_id, ticket_number);
CREATE INDEX IF NOT EXISTS idx_scan_event_received_at ON scan_event (received_at DESC);

-- ===== Check-in state and attempts =====
CREATE TABLE IF NOT EXISTS checkin_record (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id),
  ticket_number TEXT NOT NULL,
  block_id UUID REFERENCES event_block(id),
  first_scan_event_id UUID REFERENCES scan_event(id),
  last_scan_event_id UUID REFERENCES scan_event(id),
  result checkin_result NOT NULL,
  wix_checkin_id TEXT,
  wix_ticket_id TEXT,
  checked_in_at TIMESTAMPTZ,
  last_error_code TEXT,
  last_error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT checkin_record_unique_event_ticket UNIQUE (event_id, ticket_number)
);

CREATE INDEX IF NOT EXISTS idx_checkin_record_event_result ON checkin_record (event_id, result);
CREATE INDEX IF NOT EXISTS idx_checkin_record_updated_at ON checkin_record (updated_at DESC);

CREATE TABLE IF NOT EXISTS checkin_attempt (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_event_id UUID NOT NULL REFERENCES scan_event(id) ON DELETE CASCADE,
  channel attempt_channel NOT NULL,
  attempt_number INTEGER NOT NULL,
  http_status INTEGER,
  result checkin_result NOT NULL,
  error_code TEXT,
  error_message TEXT,
  response_latency_ms INTEGER,
  wix_response JSONB,
  attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT checkin_attempt_number_chk CHECK (attempt_number > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_checkin_attempt_scan_event_attempt
  ON checkin_attempt (scan_event_id, attempt_number);

-- ===== Offline queue =====
CREATE TABLE IF NOT EXISTS queue_item (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_event_id UUID NOT NULL UNIQUE REFERENCES scan_event(id) ON DELETE CASCADE,
  state queue_state NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  last_attempt_at TIMESTAMPTZ,
  synced_at TIMESTAMPTZ,
  dead_letter_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_queue_item_state_next_retry ON queue_item (state, next_retry_at);

-- ===== Relay fleet =====
CREATE TABLE IF NOT EXISTS relay_instance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  relay_code TEXT NOT NULL UNIQUE,
  venue_name TEXT NOT NULL,
  station_group TEXT,
  status relay_status NOT NULL DEFAULT 'enabled',
  software_version TEXT,
  auth_key_version INTEGER NOT NULL DEFAULT 1,
  last_heartbeat_at TIMESTAMPTZ,
  created_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
  ALTER TABLE scan_session
    ADD CONSTRAINT scan_session_relay_fk
    FOREIGN KEY (relay_id) REFERENCES relay_instance(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS relay_ingest_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  relay_id UUID NOT NULL REFERENCES relay_instance(id) ON DELETE CASCADE,
  scan_event_id UUID NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT relay_ingest_unique UNIQUE (relay_id, scan_event_id)
);

CREATE TABLE IF NOT EXISTS relay_heartbeat (
  id BIGSERIAL PRIMARY KEY,
  relay_id UUID NOT NULL REFERENCES relay_instance(id) ON DELETE CASCADE,
  queue_depth INTEGER NOT NULL DEFAULT 0,
  oldest_queue_age_seconds INTEGER,
  ingest_rate_per_minute NUMERIC(10,2),
  forward_success_rate NUMERIC(5,2),
  replay_count INTEGER NOT NULL DEFAULT 0,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_relay_heartbeat_relay_recorded_at
  ON relay_heartbeat (relay_id, recorded_at DESC);

-- ===== Metrics and health =====
CREATE TABLE IF NOT EXISTS scan_metric (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_event_id UUID REFERENCES scan_event(id) ON DELETE SET NULL,
  session_id UUID REFERENCES scan_session(id) ON DELETE SET NULL,
  operator_id UUID REFERENCES app_user(id) ON DELETE SET NULL,
  event_id UUID REFERENCES event(id) ON DELETE SET NULL,
  response_time_ms INTEGER NOT NULL,
  success_status BOOLEAN NOT NULL,
  error_code TEXT,
  concurrent_count INTEGER,
  scanner_status scanner_health NOT NULL DEFAULT 'unknown',
  backend_status backend_health NOT NULL DEFAULT 'green',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT scan_metric_latency_chk CHECK (response_time_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_scan_metric_event_created_at ON scan_metric (event_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_metric_session_created_at ON scan_metric (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS auth_health_metric (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mode auth_mode NOT NULL,
  token_expiry_horizon_seconds INTEGER,
  refresh_success BOOLEAN,
  auth_failure_count INTEGER,
  validation_failure_count INTEGER,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_health_metric_recorded_at ON auth_health_metric (recorded_at DESC);

-- ===== Reconciliation =====
CREATE TABLE IF NOT EXISTS reconciliation_run (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  status run_status NOT NULL DEFAULT 'running',
  reconciliation_state reconciliation_state NOT NULL DEFAULT 'in_sync',
  drift_count INTEGER NOT NULL DEFAULT 0,
  resolved_count INTEGER NOT NULL DEFAULT 0,
  conflict_count INTEGER NOT NULL DEFAULT 0,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  triggered_by UUID REFERENCES app_user(id),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS reconciliation_item (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  ticket_number TEXT NOT NULL,
  reconciliation_state reconciliation_state NOT NULL DEFAULT 'in_sync',
  local_result checkin_result,
  wix_result checkin_result,
  resolution_result checkin_result,
  scan_event_id UUID REFERENCES scan_event(id),
  detail JSONB,
  resolved_at TIMESTAMPTZ,
  conflict_resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_item_run_id ON reconciliation_item (run_id);

-- ===== Event readiness gate =====
CREATE TABLE IF NOT EXISTS event_readiness_check (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  overall_status event_readiness_status NOT NULL DEFAULT 'critical',
  binding_verified BOOLEAN NOT NULL DEFAULT FALSE,
  credentials_active BOOLEAN NOT NULL DEFAULT FALSE,
  scopes_complete BOOLEAN NOT NULL DEFAULT FALSE,
  manifest_synced BOOLEAN NOT NULL DEFAULT FALSE,
  cache_warmed BOOLEAN NOT NULL DEFAULT FALSE,
  worker_responsive BOOLEAN NOT NULL DEFAULT FALSE,
  relay_healthy BOOLEAN,
  last_binding_error TEXT,
  last_credential_error TEXT,
  last_scope_error TEXT,
  last_manifest_error TEXT,
  last_worker_error TEXT,
  recommendations JSONB NOT NULL DEFAULT '[]'::JSONB,
  triggered_by UUID REFERENCES app_user(id),
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  valid_until TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_event_readiness_check_event_checked_at
  ON event_readiness_check (event_id, checked_at DESC);

-- ===== Credentials =====
CREATE TABLE IF NOT EXISTS secret_credential (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  mode auth_mode NOT NULL,
  encrypted_value BYTEA NOT NULL,
  key_version TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  lifecycle_state credential_lifecycle_state NOT NULL DEFAULT 'created',
  last_validated_at TIMESTAMPTZ,
  validation_error TEXT,
  created_by UUID REFERENCES app_user(id),
  rotated_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  rotated_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  CONSTRAINT secret_credential_name_mode_active_uniq UNIQUE (name, mode, is_active)
);

CREATE TABLE IF NOT EXISTS credential_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  credential_id UUID REFERENCES secret_credential(id) ON DELETE SET NULL,
  action credential_audit_action NOT NULL,
  outcome action_outcome NOT NULL,
  actor_id UUID REFERENCES app_user(id),
  request_id TEXT,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credential_audit_log_created_at ON credential_audit_log (created_at DESC);

-- ===== Generic audit trail =====
CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id UUID REFERENCES app_user(id),
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT,
  outcome action_outcome NOT NULL,
  reason TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log (resource_type, resource_id);

-- ===== Runtime tables managed by SQLAlchemy services =====

CREATE TABLE IF NOT EXISTS scan_idempotency (
  id SERIAL PRIMARY KEY,
  event_id VARCHAR(255) NOT NULL,
  ticket_number VARCHAR(255) NOT NULL,
  scan_event_id VARCHAR(36) UNIQUE NOT NULL,
  wix_check_in_id VARCHAR(255),
  outcome VARCHAR(100) NOT NULL,
  error_message VARCHAR(512),
  source VARCHAR(50),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_scan_idem UNIQUE (event_id, ticket_number, scan_event_id)
);

CREATE TABLE IF NOT EXISTS wix_sync_controls (
  event_id TEXT PRIMARY KEY,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  interval_seconds INTEGER NOT NULL DEFAULT 300,
  last_successful_sync_at DOUBLE PRECISION,
  last_attempt_at DOUBLE PRECISION,
  last_error TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS reset_audit (
  reset_id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  records_cleared INTEGER NOT NULL DEFAULT 0,
  performed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reset_audit_scope_id ON reset_audit (scope_id);

CREATE TABLE IF NOT EXISTS credential_lifecycle (
  credential_id TEXT PRIMARY KEY,
  profile_name TEXT NOT NULL,
  auth_mode TEXT NOT NULL,
  lifecycle_state TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL,
  validated_at TEXT,
  activated_at TEXT,
  last_validated_at TEXT,
  validation_error TEXT,
  expires_at TEXT,
  rotation_note TEXT,
  created_by_actor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credential_lifecycle_events (
  event_id TEXT PRIMARY KEY,
  credential_id TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  actor TEXT NOT NULL,
  event_note TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cle_credential_id ON credential_lifecycle_events (credential_id);

CREATE TABLE IF NOT EXISTS wix_scope_audit (
  audit_id TEXT PRIMARY KEY,
  binding_id TEXT NOT NULL,
  wix_site_id TEXT NOT NULL,
  wix_event_id TEXT NOT NULL,
  required_scopes TEXT NOT NULL,
  verified_scopes TEXT NOT NULL,
  missing_scopes TEXT NOT NULL,
  status TEXT NOT NULL,
  alert_reason TEXT,
  scopes_verified_at TEXT NOT NULL,
  verified_by_actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wix_scope_audit_binding_id ON wix_scope_audit (binding_id);
CREATE INDEX IF NOT EXISTS idx_wix_scope_audit_created_at ON wix_scope_audit (created_at DESC);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id SERIAL PRIMARY KEY,
  wix_request_id TEXT,
  wix_event_id TEXT NOT NULL,
  ticket_number TEXT NOT NULL,
  source TEXT NOT NULL,
  checked_in_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  signature_valid INTEGER NOT NULL,
  status TEXT NOT NULL,
  error_message TEXT,
  received_at DOUBLE PRECISION NOT NULL,
  retried_from_id INTEGER
);

CREATE TABLE IF NOT EXISTS scan_events (
  id SERIAL PRIMARY KEY,
  event_id TEXT NOT NULL,
  ticket_number TEXT NOT NULL,
  source TEXT NOT NULL,
  result TEXT NOT NULL,
  wix_request_id TEXT,
  created_at DOUBLE PRECISION NOT NULL,
  CONSTRAINT uq_scan_events UNIQUE (event_id, ticket_number, source, result)
);

CREATE TABLE IF NOT EXISTS checkin_records (
  id SERIAL PRIMARY KEY,
  event_id TEXT NOT NULL,
  ticket_number TEXT NOT NULL,
  source TEXT NOT NULL,
  wix_ticket_id TEXT,
  wix_request_id TEXT,
  checked_in_at TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  CONSTRAINT uq_checkin_records UNIQUE (event_id, ticket_number)
);

CREATE TABLE IF NOT EXISTS event_activation (
  id BIGSERIAL PRIMARY KEY,
  wix_event_id VARCHAR NOT NULL UNIQUE,
  status VARCHAR NOT NULL,
  activated_at VARCHAR NOT NULL,
  activated_by_actor VARCHAR NOT NULL,
  readiness_status VARCHAR NOT NULL DEFAULT 'ready',
  readiness_acknowledged INTEGER NOT NULL DEFAULT 0,
  readiness_failed_checks TEXT NOT NULL DEFAULT '[]',
  readiness_recommended_actions TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS auth_token_runtime (
  credential_id VARCHAR PRIMARY KEY,
  last_refresh_at VARCHAR,
  last_tested_at VARCHAR,
  last_error TEXT,
  updated_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_api_key_settings (
  settings_key VARCHAR PRIMARY KEY,
  encrypted_api_key TEXT NOT NULL,
  encrypted_wix_account_id TEXT NOT NULL,
  last_rotated_at VARCHAR,
  last_validated_at VARCHAR,
  last_validation_error TEXT,
  created_at VARCHAR NOT NULL,
  updated_at VARCHAR NOT NULL,
  created_by_actor VARCHAR NOT NULL,
  updated_by_actor VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_api_key_audit (
  audit_id VARCHAR PRIMARY KEY,
  action VARCHAR NOT NULL,
  actor VARCHAR NOT NULL,
  outcome VARCHAR NOT NULL,
  details TEXT,
  occurred_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS event_manifest_sync (
  event_id VARCHAR PRIMARY KEY,
  last_known_sync_ts DOUBLE PRECISION NOT NULL,
  source_revision VARCHAR NOT NULL,
  total_tickets INTEGER NOT NULL,
  checked_in_tickets INTEGER NOT NULL
);
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(_DDL))


def downgrade() -> None:
    # Downgrade intentionally left empty for the baseline.
    # Dropping all tables would be destructive; operators should restore from backup.
    pass
