# Anchor

Read `AGENTS.md` before making changes.

The instructions in `AGENTS.md` define the project's architecture, development sequence, testing requirements, financial controls, and Git workflow.

## Anchor Development Protocol

All Anchor development must follow:

`docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md`

Before each gate:

1. Read the protocol.
2. Assign a risk tier.
3. Start from a fresh Claude session by default.
4. Run machine preflight before expensive verification.
5. Keep implementation within scope.
6. Prefer: targeted proof -> browser proof when applicable -> domain regression -> one final full suite when warranted.
7. Do not repeatedly rerun broad suites after environmental failures.
8. Use focused mutation tests for explicit invariants.
9. Do not use `git stash` for baseline comparison; use a separate worktree.
10. Verify Claude-owned child process trees are gone after closeout.
11. Stop and report when a protocol stop condition is reached.
12. Do not automatically begin the next gate.

Financial correctness always takes priority over speed.

The objective is not less verification. It is verification proportional to risk.

## Claude Code Role

Claude Code will primarily be used for:

- independent code review
- architecture review
- identifying edge cases
- reviewing financial implementation
- reviewing tests
- investigating bugs
- selected implementation tasks when explicitly assigned

Do not expand project scope without explicit approval.

Do not modify files during a review-only task.

When reviewing implementation, distinguish:
- confirmed bugs
- financial-model concerns
- architecture concerns
- test gaps
- optional improvements

Run tests when appropriate and report exact results.