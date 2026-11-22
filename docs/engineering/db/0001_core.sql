-- Travel AI Platform core schema draft v0.1.0
-- PostgreSQL 17 baseline. Review and execute in ENG-02 before treating as authoritative.
-- Never run against production. This file is a migration design deliverable, not a migration already applied.
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS travel;

CREATE TABLE travel.tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(trim(name)) > 0),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','CLOSED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE travel.branches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  name text NOT NULL,
  timezone text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

CREATE TABLE travel.actors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_type text NOT NULL CHECK (actor_type IN ('HUMAN','TRAVELER','CHANNEL_CLIENT','SYSTEM','SERVICE')),
  display_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE travel.actor_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  actor_id uuid NOT NULL REFERENCES travel.actors(id),
  branch_id uuid,
  role text NOT NULL CHECK (role IN ('TENANT_OWNER','TENANT_ADMIN','BRANCH_MANAGER','OPERATOR','FINANCE','SUPPORT')),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REVOKED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, actor_id, branch_id, role),
  FOREIGN KEY (tenant_id, branch_id) REFERENCES travel.branches(tenant_id, id)
);

CREATE TABLE travel.conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  branch_id uuid,
  channel text NOT NULL,
  external_conversation_id text,
  status text NOT NULL DEFAULT 'OPEN',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, branch_id) REFERENCES travel.branches(tenant_id, id),
  UNIQUE (tenant_id, channel, external_conversation_id)
);

CREATE TABLE travel.cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  branch_id uuid,
  conversation_id uuid,
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','QUALIFYING','READY','IN_PROGRESS','WAITING_CUSTOMER','WAITING_MERCHANT','RESOLVED','CLOSED','SPAM','DUPLICATE')),
  source_channel text NOT NULL,
  request_summary text NOT NULL,
  customer_ref text,
  locale text NOT NULL DEFAULT 'zh-TW',
  service_timezone text,
  duplicate_of_case_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, branch_id) REFERENCES travel.branches(tenant_id, id),
  FOREIGN KEY (tenant_id, conversation_id) REFERENCES travel.conversations(tenant_id, id),
  FOREIGN KEY (tenant_id, duplicate_of_case_id) REFERENCES travel.cases(tenant_id, id)
);

CREATE TABLE travel.complaints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  case_id uuid,
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','INVESTIGATING','WAITING_CUSTOMER','WAITING_MERCHANT','REMEDIATION_IN_PROGRESS','RESOLVED','CLOSED','REOPENED')),
  category text NOT NULL,
  description text NOT NULL,
  resolution_summary text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, case_id) REFERENCES travel.cases(tenant_id, id)
);

CREATE TABLE travel.works (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  case_id uuid,
  supersedes_work_id uuid,
  work_type text NOT NULL CHECK (work_type IN ('BOOKING','CHANGE','CANCELLATION','REFUND','COMPLAINT_RESOLUTION','SERVICE_PUBLICATION','FOLLOW_UP','INTERNAL')),
  title text NOT NULL,
  goal text NOT NULL,
  acceptance_criteria jsonb NOT NULL CHECK (jsonb_typeof(acceptance_criteria) = 'array' AND jsonb_array_length(acceptance_criteria) > 0),
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','READY','RUNNING','WAITING_DECISION','WAITING_EXTERNAL','RECONCILIATION_REQUIRED','BLOCKED','SUCCEEDED','FAILED','CANCELLED','EXPIRED')),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  priority text NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('LOW','NORMAL','HIGH','URGENT')),
  due_at timestamptz,
  owner_actor_id uuid REFERENCES travel.actors(id),
  blocked_reason_code text,
  input_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, case_id) REFERENCES travel.cases(tenant_id, id),
  FOREIGN KEY (tenant_id, supersedes_work_id) REFERENCES travel.works(tenant_id, id),
  CHECK ((status <> 'BLOCKED' AND status <> 'WAITING_DECISION') OR blocked_reason_code IS NOT NULL)
);

CREATE TABLE travel.execution_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  work_id uuid NOT NULL,
  task_type text NOT NULL,
  target_system text NOT NULL,
  status text NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','RUNNING','PENDING','UNKNOWN','RECONCILIATION_REQUIRED','SUCCEEDED','FAILED','CANCELLED','SKIPPED')),
  operation_key text NOT NULL,
  request_hash char(64) NOT NULL,
  connector_account_id uuid,
  approval_id uuid,
  next_run_at timestamptz,
  deadline_at timestamptz,
  result_summary jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, target_system, operation_key),
  FOREIGN KEY (tenant_id, work_id) REFERENCES travel.works(tenant_id, id)
);

CREATE TABLE travel.execution_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  task_id uuid NOT NULL,
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  request_hash char(64) NOT NULL,
  transport_status text NOT NULL CHECK (transport_status IN ('STARTED','RESPONSE','TIMEOUT','CONNECTION_ERROR','PARSE_ERROR')),
  provider_status text,
  provider_reference text,
  safe_error_code text,
  safe_error_message text,
  response_digest char(64),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, task_id, attempt_no),
  FOREIGN KEY (tenant_id, task_id) REFERENCES travel.execution_tasks(tenant_id, id)
);

CREATE TABLE travel.decision_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  subject_type text NOT NULL,
  subject_id uuid NOT NULL,
  decision_type text NOT NULL,
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','APPROVED','REJECTED','EXPIRED','CANCELLED','SUPERSEDED')),
  revision integer NOT NULL CHECK (revision > 0),
  payload_hash char(64) NOT NULL,
  policy_version text NOT NULL,
  summary text NOT NULL,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

CREATE TABLE travel.approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  decision_request_id uuid NOT NULL,
  approver_actor_id uuid NOT NULL REFERENCES travel.actors(id),
  decision text NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
  revision integer NOT NULL,
  payload_hash char(64) NOT NULL,
  policy_version text NOT NULL,
  scope jsonb NOT NULL,
  comment text,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, decision_request_id) REFERENCES travel.decision_requests(tenant_id, id)
);
CREATE INDEX approvals_decision_lookup ON travel.approvals(tenant_id, decision_request_id, created_at DESC);

CREATE TABLE travel.approval_revocations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  approval_id uuid NOT NULL,
  revoked_by_actor_id uuid NOT NULL REFERENCES travel.actors(id),
  reason text NOT NULL,
  revoked_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, approval_id),
  FOREIGN KEY (tenant_id, approval_id) REFERENCES travel.approvals(tenant_id, id)
);

CREATE TABLE travel.quotes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  case_id uuid NOT NULL,
  service_version_id uuid NOT NULL,
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  service_at timestamptz NOT NULL,
  service_timezone text NOT NULL,
  party jsonb NOT NULL,
  line_items jsonb NOT NULL CHECK (jsonb_typeof(line_items) = 'array'),
  amount_minor bigint NOT NULL CHECK (amount_minor >= 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  terms_snapshot jsonb NOT NULL,
  supplier_snapshot jsonb NOT NULL,
  availability_checked_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, case_id, revision),
  FOREIGN KEY (tenant_id, case_id) REFERENCES travel.cases(tenant_id, id),
  CHECK (expires_at > created_at)
);

CREATE TABLE travel.bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  case_id uuid NOT NULL,
  quote_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','QUOTED','HOLD_PENDING','HELD','CONFIRM_PENDING','CONFIRMED','REJECTED','CANCEL_PENDING','CANCELLED','CHANGE_PENDING','UNKNOWN','EXPIRED','MANUAL_REVIEW')),
  payment_status text NOT NULL DEFAULT 'NOT_REQUIRED' CHECK (payment_status IN ('NOT_REQUIRED','NOT_STARTED','REQUIRES_ACTION','PROCESSING','AUTHORIZED','CAPTURED','PARTIALLY_REFUNDED','REFUNDED','FAILED','UNKNOWN')),
  provider text NOT NULL,
  provider_reference text,
  operation_key text NOT NULL,
  request_hash char(64) NOT NULL,
  confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, provider, operation_key),
  FOREIGN KEY (tenant_id, case_id) REFERENCES travel.cases(tenant_id, id),
  FOREIGN KEY (tenant_id, quote_id) REFERENCES travel.quotes(tenant_id, id),
  CHECK ((status <> 'CONFIRMED') OR (provider_reference IS NOT NULL AND confirmed_at IS NOT NULL))
);

CREATE TABLE travel.external_references (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  subject_type text NOT NULL,
  subject_id uuid NOT NULL,
  provider text NOT NULL,
  provider_account_ref text NOT NULL,
  external_id text NOT NULL,
  external_status text,
  last_verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, provider, provider_account_ref, external_id)
);

CREATE TABLE travel.evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  subject_type text NOT NULL,
  subject_id uuid NOT NULL,
  evidence_type text NOT NULL,
  storage_ref text NOT NULL,
  content_digest char(64) NOT NULL,
  source_system text NOT NULL,
  captured_at timestamptz NOT NULL,
  captured_by_actor_id uuid REFERENCES travel.actors(id),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

CREATE TABLE travel.idempotency_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  operation text NOT NULL,
  idempotency_key text NOT NULL,
  request_hash char(64) NOT NULL,
  response_status integer,
  response_body jsonb,
  resource_type text,
  resource_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  UNIQUE (tenant_id, operation, idempotency_key)
);

CREATE TABLE travel.outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  aggregate_version integer NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  correlation_id uuid NOT NULL,
  causation_id uuid,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  publish_attempts integer NOT NULL DEFAULT 0,
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, aggregate_type, aggregate_id, aggregate_version, event_type)
);
CREATE INDEX outbox_unpublished ON travel.outbox_events(occurred_at) WHERE published_at IS NULL;

CREATE TABLE travel.inbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  source text NOT NULL,
  event_id text NOT NULL,
  event_type text NOT NULL,
  payload_digest char(64) NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  processing_error text,
  UNIQUE (tenant_id, source, event_id)
);

CREATE TABLE travel.audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  actor_id uuid REFERENCES travel.actors(id),
  action text NOT NULL,
  subject_type text NOT NULL,
  subject_id uuid NOT NULL,
  before_digest char(64),
  after_digest char(64),
  reason text,
  correlation_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id)
);

-- ENG-02 MUST add RLS policies for every tenant-owned table before application use.
-- Application DB role must not be superuser, table owner, or BYPASSRLS.
-- Tenant context must be set transaction-locally after authenticated request validation.
COMMIT;
