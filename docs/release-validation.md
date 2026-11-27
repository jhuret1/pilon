# Local release verification — 0.1.0a1

Checked on Windows, Python 3.13, in a new virtual environment with system packages
disabled. This records engineering checks, not scientific accuracy.

- Core editable installation and optional LangExtract/OpenRouter installation succeeded.
- Dependency consistency check succeeded.
- **27 tests passed**, including the actual LangExtract adapter with mocked inference.
- Offline replay: 24 reviews, 32 assertions, 12 candidate concepts, zero API calls.
- Installed wheel, loaded bundled fixtures and served bundled viewer assets outside
  the source package; the replay completed successfully.
- Browser: ontology selection, absence versus broken-component values, source
  evidence, routing and costs displayed; no JavaScript errors observed.
- Live Amazon import: 20 reviews from `Home_and_Kitchen`, dataset revision
  `2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e`; only the bounded slice was downloaded.
- No paid inference was run on Amazon during release preparation.
- Git-tracked file checks excluded runtime databases, real review data, common
  credential patterns and private absolute paths. This is not a formal security audit.

The [observed dependency versions](tested-environment-windows-py313.txt) are a
platform-specific reference, not a cross-platform lockfile. Linux and other Python
versions have CI jobs configured; this local validation does not claim they were run.

The project is a local Git repository at this stage. No public hosting, PyPI release,
live provider availability or independent induction benchmark is implied.
