# Low-Level Design — superseded

This document has been **absorbed into
[`BFA_MVP2_SYSTEM_DESIGN.md`](BFA_MVP2_SYSTEM_DESIGN.md)**, which is now the single
canonical design for MVP-2.

`LLD.md` was written before three decisions that changed the architecture materially:

| Decision | Effect |
|---|---|
| Extraction and analysis merge into **one service** | the HTTP hop, the cross-service JWT flow, and the two-service topology described here no longer exist |
| **Slack** reduced to outbound notification plus a narrow feedback/correction channel | the Slack approval workflow described here is replaced by dashboard actions |
| **Successful** pipelines are ingested for KPI reporting | the failure-only flow described here is incomplete |

The system design document also carries material that never existed here: the
repo/branch fingerprint normalisation and its collapse/collision gates, the merged fix
cache with `kb_version` verdict invalidation, database access by flow phase and per store,
the replay harness specification, and the dashboard column specifications.

Where an identifier or statement in this file conflicts with the system design document,
**the system design document is authoritative** (see its §13.12).
