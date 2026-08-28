# Anchor

Read `AGENTS.md` before making changes.

The instructions in `AGENTS.md` define the project's architecture, development sequence, testing requirements, financial controls, and Git workflow.

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