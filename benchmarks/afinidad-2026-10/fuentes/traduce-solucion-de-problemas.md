# Troubleshooting

If the service does not start, follow these steps in order:

1. Check that the port is free.
2. Delete the stale lock file.
3. Start the service again.

```python
def is_free(port):
    """Return True when nothing listens on the port."""
    # try to bind and close at once
    return True
```

### Still failing?

Open an issue and attach the log.