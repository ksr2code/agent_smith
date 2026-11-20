# ADR-0013: Role assignments and task-ownership moves
- Status: Proposed
- Date: 2026-11-20
- Deciders: ksmailov + wehan (agreed in chat, 2026-11-20)

## Context

Ownership in the planning docs is side-relative (A/B), never
name-relative. The founding-session sketch tentatively assigned the
sides one way; the final agreement (2026-11-20) is recorded here so
reviews, gates and the author-never-reviews rule map to people. Two
task moves from the same agreement are recorded with it.

## Decision

1. **A side (architect + agent half): ksmailov.** B side (systems
   half): **wehan**.
2. **T10 and T11 move to B.** Flexibility: if A finishes his
   dependency-free tasks (T15, T16) while T10/T11 are unstarted, A
   may pick them up — claim the task in docs/TRACKER.md first so
   work is never duplicated.
3. **T27 (unknown-server compatibility):** B leads the compatibility
   test pass; A fixes client findings.

## Consequences

- Parallel waves become: B runs T06→T07→T08→T09 then T10/T11;
  A runs T15/T16 and may pick up T10/T11 per clause 2; T12 unblocks
  when T08 + T10 have landed.
- The side-relative tables in docs/planning/* stay as they are;
  this ADR is the name↔side mapping (and the T10/T11 exception).
- Review pairing: ksmailov reviews B's PRs; wehan reviews A's PRs.
