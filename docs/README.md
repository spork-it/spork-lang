# Spork Documentation

The project README provides installation and a short tour. The documents here cover the language and tooling in more depth.

> **Version note:** These references describe the branch you are viewing and may be ahead of the latest PyPI release.

## Choose a starting point

| If you want to… | Start with… |
| --- | --- |
| Learn syntax and language semantics | [Language Reference](LANG.md) |
| Look up a core function, macro, reader form, or `std.*` module | [Standard Library Reference](STDLIB.md) |
| Configure `spork.it` or use project commands | [Projects and CLI](PROJECTS.md) |
| Browse runnable programs | [Examples](../examples/) |
| Understand possible future directions | [Future Ideas](IDEAS.md) |

## Reference documents

### [Language Reference](LANG.md)

Literals, bindings, control flow, functions, type annotations, pattern matching, classes, protocols, namespaces, macros, async support, exceptions, Python interoperability, and error reporting.

### [Standard Library Reference](STDLIB.md)

Persistent collection types, core sequence functions, transients, lazy operations, reducers, reader macros, prelude macros, and the `std.string`, `std.map`, and `std.json` modules.

### [Projects and CLI](PROJECTS.md)

The `spork.it` manifest, dependency environments, namespace layout, entry points, compilation, distributions, standalone commands, and troubleshooting.

### [Future Ideas](IDEAS.md)

Exploratory proposals that are not implemented or supported. This document is intentionally separate from the references above.

## Persistent data structures

Spork uses the separately released [`spork-pds`](https://github.com/spork-it/spork-pds) package. Consult that project when using the collections directly from Python:

- [Practical guide](https://github.com/spork-it/spork-pds/blob/main/docs/GUIDE.md)
- [Python API reference](https://github.com/spork-it/spork-pds/blob/main/docs/API.md)
- [Design and complexity](https://github.com/spork-it/spork-pds/blob/main/docs/DESIGN.md)
- [Benchmark methodology](https://github.com/spork-it/spork-pds/blob/main/docs/BENCHMARKS.md)

## Editors and other resources

- [Emacs mode](../editors/emacs/)
- [Neovim support](../editors/nvim/)
- [Project README](../README.md)
- [Changelog](../CHANGELOG.md)
- [Issue tracker](https://github.com/spork-it/spork-lang/issues)

## Verify the examples

Run `make verify-docs` from the repository root. The verifier executes runnable Spork and Python fences, checks `; =>` values and documented errors, and explicitly classifies non-runnable Spork grammar or future-syntax fragments.

## Documentation conventions

- Spork examples use `clojure` code fences for readable Lisp highlighting.
- `; => value` is an exact, machine-checked expectation. Every such claim must produce a verifier assertion; use an ordinary prose comment for nondeterministic or descriptive results. For lazy operations, the value shows logical contents after realization rather than the raw generator representation. Use `vec` or `doall` to realize a lazy result as a persistent vector, or `dorun` to consume it only for side effects.
- Place `&lt;!-- verify-docs: expect-error=ExceptionType --&gt;` immediately before a Spork fence that must fail with that exception.
- Place `&lt;!-- verify-docs: skip=reason --&gt;` immediately before a deliberately non-runnable Spork fence. The reason records why the fence is excluded.
- Hyphenated names are preferred in Spork source. The compiler normalizes hyphens to underscores for Python, so `sorted-vec` resolves to the runtime binding `sorted_vec`.
- Prefer dotted calls for namespace aliases, Python modules, classes, and named object receivers: `(json.loads text)`, `(Path.cwd)`, and `(response.json)`. The leading-dot `(.method receiver args...)` form remains supported for compatibility and for literal or computed receivers that cannot begin a dotted symbol.
- Use `:require` only for Spork namespaces and `:import` only for Python modules. The compiler enforces this distinction.
- `nil`, `true`, and `false` correspond to Python's `None`, `True`, and `False`.
- Collection iteration order is not guaranteed for maps and sets. Examples showing one order should not be treated as ordering guarantees.
