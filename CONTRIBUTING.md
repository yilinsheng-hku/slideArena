# Contributing

## Run the Tests

Install the package and run all three checks from the repository root:

```bash
python -m pip install -e .
python tests/test_scoring.py
python tests/smoke_test.py
python -m slidearena selftest
```

The scoring tests must print `全部通过`, the smoke test must print `全部通过`, and the self-test must print `评分器自检通过`. Tests use local fake API servers; do not add tests that call real model APIs or depend on a real API key.

The browser end-to-end test is a development check for the complete offline UI flow:

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
python tests/e2e_test.py
```

It starts a temporary local server, adds the three demo models, runs the benchmark, checks the
leaderboard and downloads a generated four-slide PPTX. If Playwright is not installed, the script
prints a skip message and exits successfully.

## Add a Task

1. Add the task and its reference answer to the appropriate bank in `slidearena/cases.py`.
2. Run `python -m slidearena selftest` and make sure the new reference answer scores 100 without changing existing reference answers or scoring rules to accommodate it.
3. Add a corresponding deduction test to `tests/test_scoring.py` so a representative mistake loses points.
4. Run all three test commands before opening a pull request.

Keep task material self-contained, use fictional or public data, and avoid personal information or real credentials.

## Add a Provider Preset

Add an entry to `PRESETS` in `slidearena/llm.py` with a unique `key`, display `label`, supported `protocol`, public default `base_url`, and default `model` when known. Keep API keys out of presets. Add or update protocol tests with a local fake server, and document provider-specific limitations when necessary.

## Pull Requests

Keep changes focused, describe the user-visible behavior, and include the output of all three required tests in the pull request template.

## 发布新版本

1. 在 `pyproject.toml` 和 `slidearena/__init__.py` 中改版本号。
2. 在 `CHANGELOG.md` 顶部增加对应版本的功能和修复记录。
3. 运行四项本地检查，并确认构建产物中包含网页静态文件。
4. 创建并推送版本标签：

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

推送 `v*` 标签会触发 `.github/workflows/release.yml`，构建 sdist 和 wheel，发布到 PyPI，并创建附带变更记录和构建产物的 GitHub Release。首次发布前，需要在 PyPI 配置 Trusted Publisher：选择项目包名，仓库填写 GitHub 的 `OWNER/slidearena`，workflow 文件填写 `.github/workflows/release.yml`，environment 名填写 `pypi`（若 PyPI 页面要求环境名，必须与仓库的发布环境完全一致）。Workflow 使用 OIDC，不在仓库或代码中保存 token。
