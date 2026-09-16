# F4.5 — Reel Lifecycle UI

## Scope

F4.5 presents the existing F4.4 Reel lifecycle fields in the Next.js Library and Reel detail UI. It changes frontend presentation and the owner curation interaction only. It does not change lifecycle ownership, database migrations, workflows, deployment, or production state.

## Lifecycle mapping

The UI keeps the three dimensions separate:

| Dimension | Browser role | Values | UI meaning |
| --- | --- | --- | --- |
| Download | read-only system state | `received`, `downloading`, `downloaded`, `failed` | received/waiting, download in progress, media available, or download problem |
| Transcription | read-only system state | `not_requested`, `queued`, `processing`, `completed`, `failed` | not started, waiting, processing/enriching, processing completed, or failed |
| Curation | owner-controlled user state | `inbox`, `organized` | awaiting organization or organized by the owner |

The lifecycle component groups Download and Transcription under **Estado do sistema** and Curation under **Organização**. It never collapses them into a generic Reel status.

`transcription_status=completed` means the transcription/enrichment lifecycle completed. It does not claim that transcript text exists: accepted completion outcomes also include `no_audio` and `empty_transcript`, which are not exposed by this API projection.

Unknown lifecycle values are rejected by the frontend runtime API validators before presentation. The shared presentation mapping also renders an explicit safe unknown indicator if it is used with an untrusted value; it never substitutes a valid-looking default.

## Library and detail behavior

Library cards use compact lifecycle indicators and expose the current curation action. Reel detail uses the same component with the full system/user grouping. The component does not use source metadata, so Telegram-created and Web-created Reels have the same lifecycle semantics. Category controls remain separate; neither category actions nor curation actions change each other.

## Curation API and feedback

The only lifecycle write from the browser is:

`PATCH /api/reels/{reel_id}/curation`

The request is exactly:

```json
{"curation_status":"inbox"}
```

or:

```json
{"curation_status":"organized"}
```

The client reuses the existing same-origin F4.4 CSRF bootstrap (`GET /api/auth/csrf`, then `X-CSRF-Token`) used by category controls. It sends no lifecycle field other than `curation_status`.

While a request is submitting, its action is disabled and a bounded loading message is shown. A successful bounded lifecycle response is runtime-validated and becomes the local confirmed projection. A failure leaves the last confirmed projection in place and displays a user-facing error without backend details. Same-state responses remain stable because the F4.4 endpoint is idempotent.

## Browser authority boundary

- `download_status`: read-only browser presentation; no browser mutation.
- `transcription_status`: read-only browser presentation; no browser mutation.
- `curation_status`: owner-controlled browser mutation through the F4.4 endpoint with CSRF.
- `transcription_attempt_id`: neither exposed nor written by the lifecycle UI.
