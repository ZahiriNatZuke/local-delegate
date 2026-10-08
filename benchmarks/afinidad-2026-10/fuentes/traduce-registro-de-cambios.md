## Changelog

### Added

- New `--dry-run` flag.
- Support for custom templates.

### Fixed

- The parser no longer crashes on empty files.

Example of the new flag:

```
$ demo run --dry-run
# nothing was written
```