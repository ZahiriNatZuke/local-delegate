# Release checklist

Before tagging a release:

- Update the version:
  - in `pyproject.toml`
  - in the changelog
- Run the full test suite.

```python
# bump the version everywhere
VERSION = '1.2.0'
```

Then push the tag.