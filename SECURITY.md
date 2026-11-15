# Security Policy

## Key Storage

Model configuration and any directly entered API keys are stored locally in `~/.slidearena/models.json`. Set `SLIDEARENA_HOME` to use another local data directory. To keep a key out of that file, store it in an environment variable and configure the model key as `env:VARIABLE_NAME`.

The app masks keys in the web interface and benchmark reports. Do not include credentials in bug reports, screenshots, logs, or pull requests.

## Network Exposure

The web server binds to `127.0.0.1` and validates request Host and Origin headers. It does not enable cross-origin access. Model requests are sent to the provider endpoint configured by the user.

## Private Reports

Please report suspected vulnerabilities privately through GitHub Security Advisories for this repository, if private vulnerability reporting is enabled. The repository URL currently uses the `OWNER` placeholder; contact the maintainer through the repository profile if that feature is unavailable. Do not disclose an unpatched issue in a public issue.
