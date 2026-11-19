# Changelog

## Unreleased

- One-click benchmarking now works for any number of models: rule scores only for one or two models (no self-judging), third-party pairwise review for three or more.
- Pairwise review uses balanced, rotating pairings and least-loaded judges, so each model's review cost stays flat as the number of models grows.
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
