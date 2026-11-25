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

1. Sample each app: its eval command with `--mode record --limit 3 --max-usd 0.5` records three cases and prints tokens and dollars per case and the projected cost of the rest. Add the six projections into one total.
2. With the owner's approval of that total, give each app its projected share as its cap and record the rest: `--mode record --max-usd <share>`. A case starts only if what was already recorded, what was spent and the costliest case so far stay under the cap; the sample's cassettes are kept, so they are not paid for twice, and a stopped run resumes where it stopped.
3. `make eval-recorded`: every app replays its cassettes through the same graders and floors and writes a dated recorded report. A cassette that no longer matches its prompt fails with the case named; re-record that case.
4. For damage-assessor, `uv run freight-damage eval --mode recorded --write-calibration` writes the confidence thresholds from the recorded findings; run `make eval-recorded` again after it.
5. Commit the cassettes, the calibration and the dated reports. Update the README's Results section from those reports only.

## Tag

1. Move the CHANGELOG entries under the new version with today's date.
2. Open the release pull request; merge when green.
3. `git tag -a vX.Y.Z -m "vX.Y.Z"` on the merge commit, push the tag, and publish a GitHub release whose notes link the evaluation report.
