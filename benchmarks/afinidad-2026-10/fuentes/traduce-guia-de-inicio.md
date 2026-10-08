# Quick start

Install the package and run the check:

- Install it with pip.
- Run the check command.
- Read the report.

```bash
pip install demo-tool  # installs the CLI
demo-tool check --strict
```

## Configuration

Set the timeout in seconds:

```toml
[demo]
timeout = 30  # seconds
```