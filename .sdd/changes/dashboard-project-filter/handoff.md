# Handoff: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Current state

- SDD status: closed
- Last completed gate: memory
- Current revision: branch feat/dashboard-project-filter, PR #661 (not merged)

## What changed

- Own-repo switch removed from panel, API and local_status; local map project-names.json written by
  project_fields with lazy bounded backfill; by-project card and project filter across the panel.

## Decisions

- E1-E10 in spec.md (raw folder name shown, session= gets no breakdown, quota and inflight do not
  follow the filter, names visible on a panel published on the network).

## Next action

- Coordinator: live check against the installed daemon (backfill over the real projects root, map
  written by the installed hooks), then merge for 0.52.0.

## Memory

- Canonical note: none from this agent; the coordinator records the day's journal in the vault
- Indexes updated: none

