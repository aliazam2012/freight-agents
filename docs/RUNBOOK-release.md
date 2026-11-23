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

1. Record a sample and read the projection: `make record ARGS="--limit 3 --max-usd 1"` prints tokens and dollars per case and the projected cost of all 36.
2. With the owner's approval of that projection, record the full set under the approved cap: `make record ARGS="--max-usd 6"`. Recording stops before it passes the cap.
3. `make eval ARGS="--mode recorded --report"` and commit the cassettes and the dated report.
4. Update the README's Results section from that report only.

## Tag

1. Move the CHANGELOG entries under the new version with today's date.
2. Open the release pull request; merge when green.
3. `git tag -a vX.Y.Z -m "vX.Y.Z"` on the merge commit, push the tag, and publish a GitHub release whose notes link the evaluation report.
