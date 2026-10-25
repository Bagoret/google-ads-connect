# Bidding principles

> Analysis guidance, not account facts. Verify current bid-strategy behaviour in
> official Google documentation before recommending changes.

## Before recommending a bid or target change
- Confirm the objective and target exist in `context/business.md` and are current.
- Confirm conversion actions included in bidding (`context/measurement.md`).
  Smart bidding optimises toward primary conversions; secondary ones are reported only.
- Check for recent changes (strategy, target, budget, conversion setup) —
  smart bidding needs time to adapt after changes; avoid stacking changes.
- Account for conversion delay: recent days understate conversions and ROAS.

## Volume and confidence
- Ratios from small samples are noisy. Report clicks/conversions next to every
  CPA, conversion rate, and ROAS figure.
- Prefer longer windows or aggregated segments when volume is low, but never
  merge incompatible segments to gain volume.

## Target logic (only with supplied data)
- tROAS / tCPA proposals must reference a supplied target or margin. Never
  derive a target from benchmarks.
- Change targets in moderate steps and define a validation window before acting.
- Budget-limited campaigns: a target change may not change spend; check budget
  status and impression share lost to budget first.

## What counts as a recommendation
Every bid recommendation must state: entity ID, current setting (from data),
proposed setting, supporting metrics with date range, expected risk, and a
validation plan (metric, window, success/rollback criteria).
