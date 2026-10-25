# Write path — from proposals to approved actions

**Status: groundwork only. Writes are disabled and no code in this repo can change an ad account.**

## Why writes can't happen today
1. Google's official MCP server (`googleads/google-ads-mcp`) lists only read tools: `search`,
   `list_accessible_customers`, `get_resource_metadata`.
2. `scripts/gads/mcp_client.py` refuses any tool outside a read-only allowlist before sending a request.
3. `config/execution.json` has `"writes_enabled": false`. `.claude/settings.json` denies Claude's Edit/Write
   tools on it; that is best-effort (shell commands are not covered), so it is not the main safeguard.
4. The only executor is `DisabledExecutor`, which always raises `WritesDisabled`.
5. `.claude/settings.json` denies the GoMarble connector, which exposes "propose" tools, in this project.

## The pipeline (built and tested)
`scripts/gads/changes.py`:

```
finding (actions.json) ──► ChangeRequest(proposed) ──► human review ──► approve(fingerprint)
                                                                            │
                     change-log.md ◄── record_approved()                    ▼
                                                  execute_change() ── checks: writes_enabled · status approved ·
                                                                      fingerprint unchanged ── executor.execute()
                                                                                                 │
                                                       verification snapshot ──► verified | rolled_back
```

| Element | Behaviour |
|---|---|
| Typed operations | `pause_campaign`, `enable_campaign`, `set_campaign_budget`, `set_campaign_target_roas`, `set_campaign_target_cpa`, `pause_ad_group`, `pause_keyword`, `add_campaign_negative_keyword`, `add_shared_negative_keyword`; each has an exact parameter set |
| Before/after values | Required for budget and target changes, so a rollback is always defined; no-op changes are rejected |
| Fingerprinted approval | Approval stores a SHA-256 of customer + operation + params; any later edit voids it |
| State machine | `proposed → approved/rejected`, `approved → executed/proposed`, `executed → verified/rolled_back` |
| Records | `save_request()` writes each revision to `outputs/change-requests/` without overwriting; `record_approved()` appends to `decisions/change-log.md` only for approved changes |

## What enabling writes would take (future phase — not started)
1. **An executor.** The likely route is the Google Ads API through Google's official `google-ads` Python
   client library. That is a third-party dependency, so it gets proposed and explained before it is installed.
2. **Dry run first:** every mutate is sent with `validate_only=true` and the result shown before the real call.
3. **Small allowlist:** start with reversible, low-blast-radius operations (pausing a keyword, adding a negative).
   Budget and target changes come later, with caps.
4. **One approved change per call.** No batch execution of unapproved items.
5. **Verification:** a post-change snapshot confirms the new state; the outcome is recorded in the change log.
6. **Kill switch:** you flip `writes_enabled` by hand; Claude cannot.
