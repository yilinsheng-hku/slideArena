# Changelog

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
