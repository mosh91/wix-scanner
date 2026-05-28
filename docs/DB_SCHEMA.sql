-- Wix Scanner canonical PostgreSQL schema
-- Source: README + IMPLEMENTATION_STORIES
-- Target: PostgreSQL 15+

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===== Enums =====
CREATE TYPE user_role AS ENUM ('operator', 'admin', 'security_admin', 'system');
CREATE TYPE event_status AS ENUM ('draft', 'active', 'archived');
CREATE TYPE auth_mode AS ENUM ('oauth_token', 'api_key', 'relay_secret');
CREATE TYPE checkin_result AS ENUM (
  'checked_in',
  'already_checked_in',
  'queued_offline',
  'invalid_ticket',
  'outside_block_window',
  'error'
);
CREATE TYPE scan_source AS ENUM ('operator_ui', 'manual_override', 'relay', 'wix_mobile', 'reconciliation');
CREATE TYPE scan_processing_status AS ENUM ('accepted', 'rejected', 'queued', 'synced', 'failed');
CREATE TYPE queue_state AS ENUM ('pending', 'in_progress', 'synced', 'dead_letter', 'cancelled');
CREATE TYPE attempt_channel AS ENUM ('live_api', 'worker_retry', 'reconciliation');
CREATE TYPE relay_status AS ENUM ('enabled', 'disabled', 'degraded');
CREATE TYPE run_status AS ENUM ('running', 'completed', 'failed');
CREATE TYPE scanner_health AS ENUM ('connected', 'disconnected', 'unresponsive', 'unknown');
CREATE TYPE backend_health AS ENUM ('green', 'yellow', 'red');
CREATE TYPE ticket_manifest_state AS ENUM ('active', 'checked_in', 'cancelled', 'void', 'stale');
CREATE TYPE credential_audit_action AS ENUM ('create', 'update', 'rotate', 'test', 'refresh', 'read_denied');
CREATE TYPE action_outcome AS ENUM ('success', 'failure');

-- ===== Users / RBAC =====
CREATE TABLE app_user (
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
CREATE TABLE event (
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

CREATE TABLE event_block (
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

CREATE TABLE event_config_version (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  config_snapshot JSONB NOT NULL,
  created_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT event_config_version_unique UNIQUE (event_id, version_number)
);

CREATE TABLE event_ticket_manifest (
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

CREATE INDEX idx_event_ticket_manifest_event_state ON event_ticket_manifest (event_id, manifest_state);
CREATE INDEX idx_event_ticket_manifest_event_updated_at ON event_ticket_manifest (event_id, updated_at DESC);

-- ===== Scanner sessions and scan events =====
CREATE TABLE scan_session (
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

CREATE TABLE scan_event (
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

CREATE INDEX idx_scan_event_event_ticket ON scan_event (event_id, ticket_number);
CREATE INDEX idx_scan_event_received_at ON scan_event (received_at DESC);

-- ===== Check-in state and attempts =====
CREATE TABLE checkin_record (
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

CREATE INDEX idx_checkin_record_event_result ON checkin_record (event_id, result);
CREATE INDEX idx_checkin_record_updated_at ON checkin_record (updated_at DESC);

CREATE TABLE checkin_attempt (
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

CREATE UNIQUE INDEX uq_checkin_attempt_scan_event_attempt
  ON checkin_attempt (scan_event_id, attempt_number);

-- ===== Offline queue / worker visibility =====
CREATE TABLE queue_item (
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

CREATE INDEX idx_queue_item_state_next_retry ON queue_item (state, next_retry_at);

-- ===== Relay fleet and relay dedupe =====
CREATE TABLE relay_instance (
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

ALTER TABLE scan_session
  ADD CONSTRAINT scan_session_relay_fk
  FOREIGN KEY (relay_id) REFERENCES relay_instance(id);

CREATE TABLE relay_ingest_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  relay_id UUID NOT NULL REFERENCES relay_instance(id) ON DELETE CASCADE,
  scan_event_id UUID NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT relay_ingest_unique UNIQUE (relay_id, scan_event_id)
);

CREATE TABLE relay_heartbeat (
  id BIGSERIAL PRIMARY KEY,
  relay_id UUID NOT NULL REFERENCES relay_instance(id) ON DELETE CASCADE,
  queue_depth INTEGER NOT NULL DEFAULT 0,
  oldest_queue_age_seconds INTEGER,
  ingest_rate_per_minute NUMERIC(10,2),
  forward_success_rate NUMERIC(5,2),
  replay_count INTEGER NOT NULL DEFAULT 0,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_relay_heartbeat_relay_recorded_at
  ON relay_heartbeat (relay_id, recorded_at DESC);

-- ===== Metrics and health =====
CREATE TABLE scan_metric (
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

CREATE INDEX idx_scan_metric_event_created_at ON scan_metric (event_id, created_at DESC);
CREATE INDEX idx_scan_metric_session_created_at ON scan_metric (session_id, created_at DESC);

CREATE TABLE auth_health_metric (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mode auth_mode NOT NULL,
  token_expiry_horizon_seconds INTEGER,
  refresh_success BOOLEAN,
  auth_failure_count INTEGER,
  validation_failure_count INTEGER,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_auth_health_metric_recorded_at ON auth_health_metric (recorded_at DESC);

-- ===== Reconciliation =====
CREATE TABLE reconciliation_run (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  status run_status NOT NULL DEFAULT 'running',
  drift_count INTEGER NOT NULL DEFAULT 0,
  resolved_count INTEGER NOT NULL DEFAULT 0,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  triggered_by UUID REFERENCES app_user(id),
  notes TEXT
);

CREATE TABLE reconciliation_item (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES reconciliation_run(id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  ticket_number TEXT NOT NULL,
  local_result checkin_result,
  wix_result checkin_result,
  resolution_result checkin_result,
  scan_event_id UUID REFERENCES scan_event(id),
  detail JSONB,
  resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_reconciliation_item_run_id ON reconciliation_item (run_id);

-- ===== Secret management and audit =====
CREATE TABLE secret_credential (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  mode auth_mode NOT NULL,
  encrypted_value BYTEA NOT NULL,
  key_version TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID REFERENCES app_user(id),
  rotated_by UUID REFERENCES app_user(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  rotated_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  CONSTRAINT secret_credential_name_mode_active_uniq UNIQUE (name, mode, is_active)
);

CREATE TABLE credential_audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  credential_id UUID REFERENCES secret_credential(id) ON DELETE SET NULL,
  action credential_audit_action NOT NULL,
  outcome action_outcome NOT NULL,
  actor_id UUID REFERENCES app_user(id),
  request_id TEXT,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_credential_audit_log_created_at ON credential_audit_log (created_at DESC);

-- ===== Generic audit trail for sensitive operations =====
CREATE TABLE audit_log (
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

CREATE INDEX idx_audit_log_created_at ON audit_log (created_at DESC);
CREATE INDEX idx_audit_log_resource ON audit_log (resource_type, resource_id);
