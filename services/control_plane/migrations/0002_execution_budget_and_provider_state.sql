BEGIN EXCLUSIVE;
CREATE TABLE task_execution_budgets (
 task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
 schema_version TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 model_calls_limit INTEGER NOT NULL CHECK(model_calls_limit>=0),
 model_calls_used INTEGER NOT NULL DEFAULT 0 CHECK(model_calls_used>=0 AND model_calls_used<=model_calls_limit),
 max_live_delegations INTEGER NOT NULL CHECK(max_live_delegations>=0),
 live_delegations INTEGER NOT NULL DEFAULT 0 CHECK(live_delegations>=0 AND live_delegations<=max_live_delegations),
 reviewer_calls_reserved INTEGER NOT NULL DEFAULT 0 CHECK(reviewer_calls_reserved>=0 AND reviewer_calls_reserved<=8),
 reviewer_calls_used INTEGER NOT NULL DEFAULT 0 CHECK(reviewer_calls_used>=0 AND reviewer_calls_used<=reviewer_calls_reserved),
 provider_retry_limit INTEGER NOT NULL CHECK(provider_retry_limit>=0),
 provider_retries_used INTEGER NOT NULL DEFAULT 0 CHECK(provider_retries_used>=0 AND provider_retries_used<=provider_retry_limit),
 context_soft_limit_tokens INTEGER NOT NULL CHECK(context_soft_limit_tokens>=0),
 context_hard_limit_tokens INTEGER NOT NULL CHECK(context_hard_limit_tokens>=context_soft_limit_tokens),
 budget_state TEXT NOT NULL CHECK(budget_state IN ('OPEN','HARD_LIMIT_REACHED')),
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
 updated_at TEXT NOT NULL CHECK(substr(updated_at,-1)='Z')
) STRICT;
CREATE TABLE provider_channel_states (
 channel_id TEXT PRIMARY KEY CHECK(length(channel_id)>0 AND length(channel_id)<=128),
 schema_version TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('AVAILABLE','AUTH_EXPIRED','QUOTA_EXHAUSTED','TRANSIENT_FAILURE','UNKNOWN')),
 observed_at TEXT NOT NULL CHECK(substr(observed_at,-1)='Z'),
 reset_at TEXT CHECK(reset_at IS NULL OR substr(reset_at,-1)='Z'),
 source TEXT NOT NULL CHECK(length(source)>0 AND length(source)<=128),
 metadata TEXT NOT NULL CHECK(json_valid(metadata) AND json_type(metadata)='object'),
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
 updated_at TEXT NOT NULL CHECK(substr(updated_at,-1)='Z')
) STRICT;
CREATE INDEX task_execution_budgets_state_idx ON task_execution_budgets(budget_state,updated_at);
CREATE INDEX provider_channel_states_state_idx ON provider_channel_states(state,observed_at);
CREATE TRIGGER task_execution_budgets_no_delete BEFORE DELETE ON task_execution_budgets BEGIN SELECT RAISE(ABORT,'TASK_BUDGET_RETAINED'); END;
CREATE TRIGGER provider_channel_states_no_delete BEFORE DELETE ON provider_channel_states BEGIN SELECT RAISE(ABORT,'PROVIDER_CHANNEL_RETAINED'); END;
CREATE TRIGGER task_execution_budgets_update_guard BEFORE UPDATE ON task_execution_budgets BEGIN
 SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.schema_version<>OLD.schema_version OR NEW.policy_version<>OLD.policy_version OR NEW.model_calls_limit<>OLD.model_calls_limit OR NEW.max_live_delegations<>OLD.max_live_delegations OR NEW.provider_retry_limit<>OLD.provider_retry_limit OR NEW.context_soft_limit_tokens<>OLD.context_soft_limit_tokens OR NEW.context_hard_limit_tokens<>OLD.context_hard_limit_tokens THEN RAISE(ABORT,'TASK_BUDGET_IMMUTABLE_FIELD') END;
 SELECT CASE WHEN NEW.revision<>OLD.revision+1 THEN RAISE(ABORT,'TASK_BUDGET_REVISION_CONFLICT') END;
END;
CREATE TRIGGER provider_channel_states_update_guard BEFORE UPDATE ON provider_channel_states BEGIN
 SELECT CASE WHEN NEW.channel_id<>OLD.channel_id OR NEW.schema_version<>OLD.schema_version THEN RAISE(ABORT,'PROVIDER_CHANNEL_IMMUTABLE_FIELD') END;
 SELECT CASE WHEN NEW.revision<>OLD.revision+1 THEN RAISE(ABORT,'PROVIDER_CHANNEL_REVISION_CONFLICT') END;
END;
COMMIT;
