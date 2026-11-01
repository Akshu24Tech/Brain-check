# brain-check

A deterministic auditor for a markdown second brain.

Agents write into the brain every day. brain-check decides what they're allowed to read back. No LLM in the loop. Every rule is plain Python, so the checker can't hallucinate.

## Run

```
python brain_check.py brain/ [YYYY-MM-DD]
```

Exits 1 on any FAIL, so it can gate a cron job or a git hook.

## Note format

```
---
status: checked | unverified
source: where the claim came from
written_by: human | <agent name>
expires: 2026-12-31            # optional
facts: pro_price=79; tier=pro  # optional, used for contradiction checks
---
```

## Checks

| check | catches |
|---|---|
| routing | folders agents.md never routes to, and routes to folders that are gone |
| map-size | agents.md over 200 lines |
| guard | no rule telling agents to push back on conflicting requests |
| links | `[[links]]` pointing at nothing |
| contradiction | two notes asserting different values for the same fact |
| expired | notes past their expiry date |
| unsourced | agent-written notes with no source |
| protected | agent writes inside read-only folders (strategy, finance) |

## Output

`_trusted_context.md` is built only from notes that pass every check. Point your agents at that file, not at the raw brain.
