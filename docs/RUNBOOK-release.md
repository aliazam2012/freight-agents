# Runbook: Release

## Table of Contents

- [Before](#before)
- [Record and Report](#record-and-report)
- [Tag](#tag)

---

## Before

1. `main` is green on all required checks.
2. The milestone's issues are closed or moved, each with a reason.
3. `CHANGELOG.md` has the release's entries under Unreleased.

## Record and Report

Model results come from a recorded run, never from memory. Live calls cost money: get the owner's approval and an estimate first.

1. Record a sample of 3 golden cases with the chosen model and read the token counts; estimate the full run from them.
2. Record the full golden set into `apps/claims-intake/evals/cassettes/`.
3. `make eval ARGS="--mode recorded --report"` and commit the cassettes and the dated report.
4. Update the README's Results section from that report only.

## Tag

1. Move the CHANGELOG entries under the new version with today's date.
2. Open the release pull request; merge when green.
3. `git tag -a vX.Y.Z -m "vX.Y.Z"` on the merge commit, push the tag, and publish a GitHub release whose notes link the evaluation report.
