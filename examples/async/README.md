# Async HTTP example

This project demonstrates:

- an `^async` Spork function;
- `async-with` for Python asynchronous context managers;
- `await` on Python coroutines;
- imports from `aiohttp` and `asyncio`;
- a dependency declared in `spork.it`.

## Run it

From this directory:

```bash
spork sync
spork run
```

The example requests one JSON object from `jsonplaceholder.typicode.com`, so it requires network access. A successful run prints output similar to:

```text
Received data:
{'userId': 1, 'id': 1, 'title': 'delectus aut autem', 'completed': False}
```

The exact response is controlled by the remote service.

## Source

- [`spork.it`](spork.it) declares `aiohttp` and the `async.core:main` entry point.
- [`src/async/core.spork`](src/async/core.spork) contains the program.

See the canonical [projects and CLI reference](https://spork.sh/docs/reference/tooling/) for manifest and environment details, and [async and generators](https://spork.sh/docs/reference/language/async-and-generators/) for the language forms.
