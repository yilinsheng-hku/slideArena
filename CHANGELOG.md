# Changelog

## Unreleased

- Added 10 generated tasks per run (5 charts, 2 condensations, 3 layouts) with random numbers, names, distractors, and layouts, so the public bank cannot simply be memorised. References are computed in code and checked with the real scorer before use. The default batch changes every ISO week; `--seed` reproduces a batch and `--no-fresh` uses the hand-checked bank only.
- Judges are calibrated before judging: each must tell a reference answer from a deliberately worse copy in 2 blind controls. Judges that prefer the worse copy or cannot tell them apart are left out, and the leaderboard shows each judge's results and self-consistency.
- The offline demo judges now use simple real judgement (invented numbers, overflowing text) instead of random votes.
- One-click benchmarking now works for any number of models.
- Outlines and layouts are now reviewed blind against the hand-checked reference answer by another model, instead of pairwise between models. Scores no longer depend on which other models are in the run, review cost per model is constant, and two models can review each other without self-judging. Matching the reference leaves the rule score unchanged; beating or losing to it moves a judged task by 12.5 points.
- "Tied" / "behind" now come from one Westfall–Young permutation test over all pairs. The old per-pair test against the leader wrongly reported someone "behind" in about 90% of runs with 10 equally good models; the new test stays near 10%.
- Network timeouts, dropped connections, and provider errors are no longer scored as wrong answers; they are reported as unscored. Models with more than 20% unscored tasks are flagged and skipped by routing.
- Routing now uses the same test as the leaderboard, so it never picks a model the leaderboard marks as behind.
- Models that fail a connection check are excluded before the run and listed on the leaderboard.
- Added a run plan (calls and review method) in the web app, `POST /api/benchmark/plan`, and before `slidearena bench`.
- Added a "benchmark all models" button on the models page.
- A single model is no longer marked as the leader, and tasks are not marked saturated with only one model.

## 0.1.0

- Added a local web app for connecting existing model providers and managing model configurations.
- Added offline demo models so the complete workflow can be tried without network access or API costs.
- Added a 23-task PPT benchmark covering outline writing, condensing, charts, layout, image generation, and speed.
- Added deterministic scoring, source-grounded number checks, task-level confidence intervals, pairwise review, and model routing.
- Added rate-limit handling and unscored status for tasks skipped after repeated rate limits.
- Added editable PowerPoint generation with routed outline, chart, and image tasks.
- Added a simplified layout renderer and optional vision-model screenshot review.
- Added a loopback-only web server, command-line interface, and package entry point.
- Added strict loopback Host and Origin checks, request-size limits, safe JSON API errors, and security response headers.
- Added an offline Playwright end-to-end test covering model setup, benchmarking, the leaderboard, and PPT download.
- Added scripts for generating real benchmark tables and README screenshots from local results, without reading model credentials.
- Added PyPI Trusted Publishing and GitHub Release automation for version tags.
