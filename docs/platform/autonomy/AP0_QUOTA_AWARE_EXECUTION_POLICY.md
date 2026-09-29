# AP0-TC4.1 — Quota-Aware Execution Policy

Status: policy baseline; no Control Plane, Worker Manager, provider, or runtime mutation
Date: 2026-09-29
Canonical predecessor: `AP0_TC4_REGISTRY_MVP_READY`

## 1. Purpose

This policy bounds autonomous development before provider or model capacity is exhausted. It governs Task admission, Worker admission, model-call and context budgets, delegation, checkpointing, continuation, provider availability, retries, review, pause/resume, and the audit evidence needed for later enforcement.

Core principle:

> Autonomy means bounded continuation, not unlimited execution until provider exhaustion.

AP0 freezes conservative defaults. A provider model's advertised context capacity or a subscription's possible quota is not an execution allowance. This policy does not create a schema migration, runtime resource, worker, provider session, or new authority.

## 2. Evidence from TC4

TC4 is design evidence, not blame. The observed execution was approximately:

- implementation worker #1: 41 model calls;
- completion worker #2: 90 model calls;
- second worker context: approximately 206k tokens;
- independent review started after the large implementation runs;
- the reviewer received `HTTP 429` with `usage_limit_reached` and a provider-supplied future reset time;
- retries were attempted although the quota window was already exhausted.

Cached input-token counts are not treated as exact subscription billing. The incident nevertheless establishes that bounded model-call budgets, bounded context, pre-delegation quota evidence, explicit review reservation, checkpointed continuation, and no-retry quota pauses are necessary.

## 3. Execution defaults

AP0 permits no parallel autonomous development:

```text
max_live_workers_global = 1
max_live_workers_per_task = 1
max_live_delegations = 1
```

A delegated Worker, continuation Worker, or reviewer is admitted only when this policy, the immutable Task scope, and the remaining Task-global budget permit it. A reviewer is a bounded execution consumer, not an unlimited separate budget.

## 4. Model-call budget

A model call is an invocation that consumes an LLM/provider execution opportunity. It is distinct from deterministic tool execution.

Initial AP0 defaults:

```text
Coordinator:
  soft_limit = 8
  hard_limit = 12

Implementation Worker:
  soft_limit = 15
  checkpoint_threshold = 20
  hard_limit = 25

Independent Reviewer:
  soft_limit = 5
  hard_limit = 8

Task global model-call budget:
  hard_limit = 40
```

The Task-global hard limit overrides every component allowance. For example, an implementation Worker with ten local calls remaining may use only three if the Task has three model calls remaining. No parent, child, reviewer, or continuation receives an independent unlimited allowance.

At a component soft limit, the actor narrows scope and evaluates whether a checkpoint is due. At a component hard limit or the Task-global hard limit, it stops new model work, records the budget state, and checkpoints when a resumable next action exists. A Task with no remaining global budget does not admit a continuation, retry, or additional review cycle.

## 5. Context budget

Initial Worker limits are:

```text
context_soft_limit = 80k tokens
context_hard_limit = 120k tokens
```

At the soft limit, the Worker must stop broad exploration, summarize verified evidence, narrow the remaining scope, and prepare a checkpoint. At the hard limit, it must not begin broad new implementation work; it creates or refreshes a checkpoint and terminates cleanly. Any continuation starts with a fresh, compact Task Packet and fresh budget admission.

A Worker must not intentionally grow toward a model's maximum context window. Model capacity is not execution budget.

## 6. Deterministic-tool preference

Model calls and deterministic operations are not equivalent. Prefer a deterministic operation whenever it can establish the needed fact:

- `pytest` and other tests;
- `git status`, `git diff`, and `git diff --check`;
- compilation, lint, and type checks;
- `sha256sum` and fixture-hash validation;
- static search;
- SQLite integrity and foreign-key checks;
- filesystem inspection.

```text
deterministic evidence available?
        │
   ┌────┴────┐
  yes        no
   │          │
   ▼          ▼
use tool    model call
```

Do not ask a model to discover a deterministic test failure or repository fact unless interpretation is necessary after the deterministic evidence exists.

## 7. Checkpoint policy

A checkpoint is required at any of the following triggers:

- 20 model calls in one implementation Worker;
- context at or above 80k tokens;
- provider quota warning;
- provider authentication degradation;
- a major milestone completion;
- Task pause;
- Worker replacement;
- before independent review; or
- before a continuation Worker.

A minimum secret-free checkpoint contains:

```text
task_id
current state
branch
worktree
HEAD
changed files
completed acceptance criteria
tests executed
tests passing
tests failing
unresolved issues
active resources
next permitted action
provider state
budget consumed
budget remaining
evidence references
```

Checkpoints contain no chain-of-thought, full conversation transcript, provider credential, secret, raw environment dump, or terminal-history export. They are concise evidence for a permitted continuation.

## 8. Continuation workers

A continuation Worker receives a compact fresh Task Packet, not the full prior conversation by default. The packet contains:

```text
objective
constraints
current HEAD
relevant diff/files
checkpoint
test evidence
remaining acceptance criteria
known failures
next action
budget remaining
```

Continuation requires a valid checkpoint and fresh admission against concurrency, Task-global model-call, Worker, context, provider, and environment limits. If the Task-global budget is exhausted, continuation is not admitted.

## 9. Task decomposition

Before Worker admission, the Coordinator estimates whether the proposed implementation reasonably fits within both:

```text
<= 25 implementation model calls
and
<= 120k Worker context
```

If it does not, it must be split into independently testable slices. The preferred sequence is:

```text
implementation slice A
↓ checkpoint
implementation slice B
↓ checkpoint
implementation slice C
↓ full deterministic validation
review
```

Do not delegate “implement the entire remaining system” when the scope contains multiple independently testable components. A materially changed decomposition requires human escalation when it changes approved scope or expected budget materially.

## 10. Provider preflight

Before admitting any Worker, continuation, or reviewer, evaluate:

```text
provider configured?
authentication usable?
quota state acceptable?
Task budget remaining?
Worker/reviewer budget available?
context packet bounded?
required environment available?
```

Preflight returns one of:

```text
ADMIT
BLOCK_PROVIDER_AUTH
PAUSE_PROVIDER_QUOTA
BLOCK_ENVIRONMENT
BLOCK_BUDGET
```

Do not spawn first and discover predictable provider failure later when preflight evidence is available. An `UNKNOWN` provider state is not affirmative evidence of availability; admission requires the configured policy's acceptable observation.

## 11. Provider channel state

Provider paths are independent channels. Examples include Codex CLI authentication, an OpenAI/Codex provider session, and another configured provider. Failure of one channel does not prove every channel unavailable.

Each channel records an independent state:

```text
AVAILABLE
AUTH_EXPIRED
QUOTA_EXHAUSTED
TRANSIENT_FAILURE
UNKNOWN
```

Fallback is permitted only when it is explicitly configured, remains within the Task's allowed provider scope, passes fresh preflight, and has sufficient remaining Task budget. Never silently switch providers or channels.

## 12. Authentication failure

For authentication failures such as `401`, `403`, expired CLI authentication, or invalid credentials:

```text
NO blind retry
↓
record provider/auth state
↓
BLOCK_PROVIDER_AUTH
```

The Task must distinguish provider authentication blocking from implementation failure. A separately configured provider/channel may be evaluated only through a new admission decision. Provider credentials must never appear in audit events, checkpoints, Task Packets, or logs.

## 13. Usage-limit behavior

An explicit subscription/window-exhaustion response, such as `HTTP 429` with `type = usage_limit_reached` and `reset_at` or `resets_in`, requires:

```text
STOP
↓
NO short retry loop
↓
record quota observation
↓
checkpoint
↓
Task → PAUSED(PROVIDER_QUOTA)
```

The reset value is an observation, not a permanent configuration value. Do not hardcode it. Resume requires fresh availability evidence and a supported checkpoint, then repeats budget, policy, prerequisite, and environment admission checks.

Quota exhaustion is not Task failure. It does not invalidate already passing deterministic validation or completed implementation evidence.

## 14. Transient retries

Quota exhaustion and a transient rate limit are different conditions. For a clearly transient provider or network failure without an exhausted usage window, automatic retries are limited to two after the original attempt. Use bounded exponential backoff with jitter.

Do not retry where available evidence says recovery cannot occur inside the retry interval. Every retry consumes the applicable model/provider budget and is recorded. Authentication failures, explicit `usage_limit_reached`, exhausted Task budget, and unauthorized provider fallback are not transient retry candidates.

## 15. Review budget

Independent review is required evidence where the Task Contract calls for it, but it is not free. Before implementation consumes the Task budget, reserve the expected reviewer allocation from the shared Task-global budget. The initial reviewer hard reservation is at most eight model calls and must fit inside the 40-call Task hard limit.

Reviewer admission requires:

```text
implementation finished
deterministic tests completed
checkpoint created
review budget available
provider available
```

If implementation is complete but reviewer budget or provider quota is unavailable, preserve the review checkpoint and record:

```text
READY_FOR_REVIEW
+
PAUSED_PROVIDER_QUOTA
```

Do not re-run implementation. When availability returns, resume directly at review from the checkpoint. If the reviewer encounters quota exhaustion, stop, checkpoint the review evidence, and pause rather than retrying implementation or starting another reviewer.

## 16. Budget accounting

Every delegated execution consumes the parent Task-global budget. Conceptually:

```text
Task Global Budget
      │
      ├── Hermes coordination
      ├── implementation Worker
      ├── continuation Worker
      └── reviewer
```

The conceptual Task budget state is:

```text
budget:
  model_calls_limit
  model_calls_used

  delegation_limit
  delegations_used

  reviewer_calls_reserved

  context_soft_limit
  context_hard_limit

  provider_retry_limit
  provider_retries_used
```

AP0-TC4.1 requires no schema migration. Until dedicated enforcement exists, compatible budget information may be carried in the current JSON `resource_budget`, checkpoint payload, and Audit Events. Policy evaluation must apply the Task-global remaining balance before any component-local allowance.

## 17. Audit events

Future Control Plane audit history must support these secret-free events:

```text
BUDGET_ADMITTED
BUDGET_SOFT_LIMIT_REACHED
CHECKPOINT_REQUIRED
BUDGET_HARD_LIMIT_REACHED
PROVIDER_AUTH_BLOCKED
PROVIDER_QUOTA_EXHAUSTED
PROVIDER_AVAILABLE
TASK_PAUSED_QUOTA
TASK_RESUMED_QUOTA
CONTINUATION_ADMITTED
REVIEW_BUDGET_RESERVED
```

Event payloads record bounded identifiers, policy version, counters, state transitions, safe provider/channel classification, and evidence references. They must not contain provider credentials, raw provider response bodies, full prompts, chain-of-thought, or secret-bearing context.

## 18. State semantics

The following states are distinct and must not be collapsed:

```text
FAILED
BLOCKED
PAUSED_PROVIDER_QUOTA
BLOCKED_PROVIDER_AUTH
PAUSED_OPERATOR
READY_FOR_REVIEW
```

`FAILED` means the admitted work reached a terminal unsuccessful result. `BLOCKED` means a non-quota prerequisite or policy condition prevents progress. `PAUSED_PROVIDER_QUOTA` means continuation is valid but awaits fresh quota availability. `BLOCKED_PROVIDER_AUTH` means a provider authentication condition prevents use of that channel. `PAUSED_OPERATOR` awaits an operator decision. `READY_FOR_REVIEW` means implementation and deterministic validation evidence are preserved for review admission.

A reviewer unavailable because of quota does not make the implementation fail. Authentication expiration does not make implementation evidence invalid.

## 19. Human escalation

Escalate for a human decision when:

- additional quota expenditure materially exceeds the admitted Task budget;
- another provider must be enabled or authorized;
- decomposition materially changes expected scope; or
- review identifies a new architectural problem requiring another large implementation cycle.

Do not escalate routine deterministic test fixes that fit the approved scope and remaining budget.

## 20. Future enforcement

TC4.1 defines policy only. A future Control Plane and Worker Manager must enforce:

- Task and Worker admission budgets;
- Task-global counters and component reservations;
- Worker context soft/hard thresholds;
- checkpoint requirements and valid continuation packets;
- delegation and concurrency limits;
- independent provider-channel states;
- pause/resume conditions;
- review-budget reservation; and
- secret-free audit evidence.

Hermes must eventually consume Control Plane decisions rather than retaining quota state only in conversation memory. Until then, policy compliance is procedural and must be evidenced in Task checkpoints and audit-compatible records.

## 21. Negative cases

| Case | Required behavior |
|---|---|
| Codex CLI authentication expired | Record `AUTH_EXPIRED`; do not blindly retry; mark `BLOCKED_PROVIDER_AUTH`; independently preflight an explicitly configured direct provider if permitted. |
| Direct provider still available | Do not infer a global outage from CLI failure; admit the direct channel only after explicit fallback authorization and fresh preflight. |
| All providers unavailable | Preserve checkpoint and state; pause for quota or block for authentication/environment according to evidence; do not spawn a Worker. |
| Usage-limit `429` with reset timestamp | Record safe quota observation, checkpoint, and enter `PAUSED_PROVIDER_QUOTA`; do not short-retry or hardcode the reset. |
| Transient `429` without quota exhaustion | Use at most two jittered exponential-backoff retries if the evidence supports likely recovery and budget remains. |
| Worker reaches 20 calls | Require a checkpoint and scope/budget review before more implementation work. |
| Worker reaches 120k context | Stop broad work, create or refresh checkpoint, terminate cleanly, and require a fresh continuation admission. |
| Task-global budget exhausted | Do not admit more implementation, continuation, retry, or review model work. Preserve evidence and escalate if more budget is needed. |
| Implementation complete but review budget unavailable | Keep `READY_FOR_REVIEW` evidence and pause/block according to cause; do not re-run implementation. |
| Reviewer hits quota | Stop review, checkpoint review evidence, and pause for fresh availability; do not retry implementation. |
| Continuation requested without checkpoint | Reject continuation; require a valid secret-free checkpoint first. |
| Fallback provider not authorized | Reject fallback; do not silently switch channels. |
| Deterministic test failure | Report the failing evidence; address only within remaining admitted scope/budget or checkpoint/escalate. Do not spend reviewer calls discovering it first. |
| Deterministic tests pass but reviewer finds architectural issue | Preserve review evidence; treat it as a potential new implementation cycle requiring fresh scope/budget assessment and human escalation if material. |

## 22. Recommended AP0-TC5 implications

AP0-TC5 should turn this policy into enforceable Control Plane and Worker Manager behavior without widening runtime authority. The planned work should:

1. define versioned Task budget and provider-state payload schemas compatible with current `resource_budget`, checkpoints, and Audit Events;
2. atomically reserve and debit Task-global model-call, delegation, and review budgets before Worker/reviewer admission;
3. enforce one live Worker globally, one per Task, and one live delegation;
4. require checkpoints at model-call/context thresholds and validate compact continuation Task Packets;
5. model provider channels independently, including auth, quota, transient, and fresh-availability observations;
6. implement no-retry quota pauses, bounded transient retries, and explicit authorized fallback admission;
7. make `READY_FOR_REVIEW`, quota pause, auth block, operator pause, generic block, and terminal failure distinguishable in the Task state model or typed reason/result contracts;
8. add hermetic positive and negative tests for every case in section 21; and
9. preserve secret-free audit evidence without asserting that cached token counts equal subscription billing.

AP0-TC5 must not use this policy as authorization for production provider configuration, credential retrieval, provider mutation, parallel execution, unrestricted Worker spawning, or runtime cleanup.
