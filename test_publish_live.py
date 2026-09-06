# test_publish_live.py
import os

from server import publish_knowledge, PublishInput

article = {
    "title": "Optional dependency crashes the import chain when the import itself isn't optional",
    "description": "A dependency declared as optional in pyproject.toml can still crash a package on import if the module that needs it imports it unconditionally at the top level.",
    "category": "Programming",
    "tags": ["python", "packaging", "pyproject-toml", "dependencies", "imports"],
    "content": """# Optional dependency crashes the import chain when the import isn't optional

## Problem

A Python package declares one of its dependencies as optional, grouped
under `[project.optional-dependencies]` in `pyproject.toml`. A clean
install without that extra (`pip install package-name`, no `[extra]`
suffix) crashes immediately with `ModuleNotFoundError` the moment the
package is imported — before any code that actually needs the dependency
even runs.

## Context

The package has two dependencies that could each reasonably be seen as
optional: one used for generating content via an external API, and one
used for publishing results via HTTP requests. Both were declared under
the same `[project.optional-dependencies]` mechanism in `pyproject.toml`.

## Solution

Check *how* each optional dependency is imported, not just how it's
declared. A dependency is only truly optional if the import itself is
deferred and guarded:

```python
# Truly optional: import happens inside the function that needs it,
# wrapped so a missing package produces a clean, actionable error.
def call_provider(...):
    try:
        from some_sdk import Client
    except ImportError as exc:
        raise ProviderError(
            "this feature requires the 'some_sdk' package; "
            "install it with: pip install 'package-name[extra]'"
        ) from exc
    ...
```

Compare that with an unconditional top-level import:

```python
# NOT actually optional, regardless of what pyproject.toml says:
import httpx  # <- runs at module load time, no matter what
```

If a module doing this is imported anywhere in the package's own import
chain (even indirectly, through another internal module), the package
becomes unusable without that "optional" dependency. The fix is either to
defer the import (as above) or — often simpler and more honest — to stop
calling it optional and move it into the package's main `dependencies`
list in `pyproject.toml`.

## Why it works

`pyproject.toml`'s `[project.optional-dependencies]` only controls what
`pip` installs by default; it has no effect on when or how a module
imports something. Python doesn't know or care what your packaging
metadata says — an `import` statement at module level always executes at
import time. The two systems (packaging metadata and actual import
behavior) have to be kept in sync manually; nothing enforces that they
agree.

## Caveats

- This is easy to miss because tests often run inside a development
  environment where every dependency (optional or not) is already
  installed — the crash only appears on a fresh, minimal install.
- The fix chosen (defer-and-guard vs. promote to a hard dependency)
  depends on whether the feature genuinely has zero cost when unused. If
  every code path through the package's main entry point needs it
  anyway, there is no real optionality to preserve — just move it to the
  main dependency list.
""",
}

result = publish_knowledge(PublishInput(**article))
print(result)
