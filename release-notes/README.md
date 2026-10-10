# Release notes

The GitHub release is created by the *Release images* workflow (`github-release` job), after the images and the chart
are published and signed. You no longer create it by hand.

- **Title:** taken from the annotated tag, so `git tag -a v0.24.0 -m "v0.24.0: short title"` gives
  *v0.24.0 — Short title*.
- **Notes:** `release-notes/<tag>.md` when it exists (hand-written notes, committed before tagging). Otherwise, the
  `## [x.y.z]` section of `CHANGELOG.md`.
- **Footer, added automatically:** the images, the Helm chart, the attached VS Code extension and a link to the
  changelog.

If a release for the tag already exists, the job only attaches the extension.
