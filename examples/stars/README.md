# GitHub stars example

This project ranks a small list of GitHub repositories by star count. It demonstrates:

- Python interoperability with `requests` and `time`;
- a user-defined profiling macro;
- type annotations;
- pattern matching on HTTP status codes;
- a `sorted-for` comprehension with `:key` and `:reverse`;
- map destructuring.

## Run it

From this directory:

```bash
spork sync
spork run
```

The example makes unauthenticated requests to the GitHub API. It requires network access and is subject to GitHub's unauthenticated rate limit. Star counts and timing vary between runs.

Example output:

```text
GitHub fetch took 0.42s
102000 - tiangolo/fastapi
95000 - django/django
...
```

## Source

- [`spork.it`](spork.it) declares `requests` and the `stars.core:main` entry point.
- [`src/stars/core.spork`](src/stars/core.spork) contains the macro and application.

See [Projects and CLI](../../docs/PROJECTS.md) for manifest and dependency details. The [Language Reference](../../docs/LANG.md) covers [macros](../../docs/LANG.md#11-macros), [pattern matching](../../docs/LANG.md#7-pattern-matching), and [sorted vector comprehensions](../../docs/LANG.md#sorted-vector-comprehension).
