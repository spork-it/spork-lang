# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

This history was backfilled from release tags, commit history, and published release notes.

## [Unreleased]

### Added

- Added immutable command provider, context, and specification primitives with a shared raw-argument invocation contract for core and future extension commands.
- Added a static core command registry and isolated parser construction for each core command.
- Added `ProjectRuntime` for loading values and invoking functions directly from unbuilt project source or installed Spork namespaces.
- Added project-aware `CommandContext.load_entry`, `invoke_entry`, and `require_project` operations.
- Added recursive read-only access to package-specific manifest configuration.
- Added typed `:commands` declarations with reserved-name, target, description, and normalized identifier validation.
- Added generated `spork.commands.v1` entry points and command payload verification for wheels and source distributions.
- Added static `spork check` diagnostics for package command namespaces, functions, and target kinds.
- Added a minimal source-only command-provider example.

### Changed

- Separated top-level legacy/file dispatch from core command parsing while preserving existing command syntax and project-toolchain delegation.
- Refactored `spork run` to use the shared project runtime while retaining environment bootstrap, normalized entry names, process statuses, and source tracebacks.

## [0.5.3] - 2026-08-30

### Added

- Added eager `(for [binding collection] body...)` expressions that return persistent vectors, including destructuring, nested expressions, and enclosing-local updates.
- Added eager `(async-for [binding async-collection] body...)` expressions that resolve to persistent vectors inside async functions.
- Added eager `(sorted-for [binding collection] body :key key-fn :reverse bool)` expressions that return `SortedVector` values.

### Changed

- Removed the special `[for ...]` and `[sorted-for ...]` vector-literal comprehension syntax in favor of ordinary expression forms.
- Removed the redundant `for-all` prelude macro; use `(for ...)` directly.
- Documented `doseq` as the explicit allocation-free form for effect-only iteration.

## [0.5.2] - 2026-08-30

### Fixed

- Preserve preconfigured project source roots when executing an entrypoint, so `spork run` can resolve required sibling namespaces under configured `:source-paths`.

## [0.5.1] - 2026-08-29

### Added

- Added project-local CLI delegation so synchronized projects consistently run with the compatible `spork-lang` installed in `.venv`.

### Changed

- `spork sync` now resolves `:spork-version` when the active launcher is incompatible while preserving an exact compatible active or editable toolchain.

## [0.5.0] - 2026-08-29

### Added

- Added `spork check` for project-wide reader/compiler validation, namespace-path and duplicate checks, Spork/Python import resolution, referred-export validation, `:main` and generated `:api` validation, and versioned JSON diagnostics with stable codes.
- Added a reusable project namespace and symbol index that checks configured source and test paths without producing build artifacts or executing ordinary module forms.

### Changed

- Removed the in-tree runtime and Spork-source standard library in favor of the separately released `spork-runtime` dependency, including its Python-backed `std.*` namespaces and prelude macros.
- Built Spork project distributions now depend directly on `spork-runtime` instead of pulling in the `spork-lang` compiler; `:spork-version` is enforced as a build-time compiler constraint.
- Enforced a one-way compiler-to-runtime dependency by moving Spork source namespace loading behind a compiler-installed runtime provider.
- `spork test` now discovers only files containing top-level `deftest` declarations; convention-named script-style test files are no longer supported.
- Converted the language suite to granular declared tests and a cross-platform native test harness.

### Fixed

- Ignore yields owned by nested generator helpers when validating whether an enclosing function requires `^generator`.

## [0.4.4] - 2026-08-29

### Changed

- Refactored compiler code generation into focused internal modules without changing user-visible behavior.

## [0.4.3] - 2026-08-29

### Fixed

- Emit anonymous function definitions before their first expression-statement use, including callbacks declared inside `deftest` bodies.

## [0.4.2] - 2026-08-29

### Added

- Added top-level `deftest` declarations, inline source-test discovery, async test execution, and individual native Spork test reporting.

### Changed

- `spork test` now runs only Spork tests with the native runner; Python test framework integration and the `--spork-only`/`--python-only` switches were removed.
- New projects use `deftest` in their generated test module.

### Fixed

- Preserve macro invocation locations so assertion failures point at the assertion call in Spork tracebacks.

## [0.4.1] - 2026-08-29

### Added

- `spork add` and `spork remove` commands for editing runtime dependencies in the nearest parent `spork.it`.

## [0.4.0] - 2026-08-29

### Added

- Unified `:api` manifest configuration for generating package-level Spork and Python APIs from one canonical namespace.
- Generated `__init__.spork` package namespaces, including support for idiomatic forms such as `(:require [spork-state :as state])`.
- Python runtime bridges for AOT-compiled Spork consumers, preserving Spork-specific names such as predicates and bang functions.
- Support for resolving package namespaces through `__init__.spork`.

### Changed

- Replaced the short-lived `:python-api` manifest key with target-specific `:spork` and `:python` sections under `:api`.
- Project tests now build generated public APIs before running Spork tests that depend on them.

### Fixed

- Normalize all Spork punctuation when resolving referred symbols, including names ending in `?` or `!`.

## [0.3.8] - 2026-08-29

### Fixed

- Postpone annotations during direct Spork execution as well as AOT compilation, making recursive and class-local generic references portable to Python 3.10 and newer.
- Document resolved runtime annotation inspection through `typing.get_type_hints`.

## [0.3.7] - 2026-08-29

### Added

- Manifest-driven `:python-api` generation for Python package exports, aliases, version metadata, `__all__`, `py.typed`, package stubs, and per-module stubs.
- Generic stub emission for `TypeVar`, `Generic[T]`, typed properties, callable signatures, optional arguments, and generic return values.
- Build-time validation for missing exports, duplicate aliases, and collisions with hand-written package files.

### Changed

- AOT modules use postponed annotations.
- Generic class bases, capitalized generic annotations, and `Callable[..., T]` compile to their corresponding Python typing forms.

## [0.3.6] - 2026-08-29

### Fixed

- Use ASCII-safe CLI status output so builds and tests work with default Windows console encodings.

## [0.3.5] - 2026-08-29

### Fixed

- Compile documented `^property` method metadata correctly.

## [0.3.4] - 2026-08-29

### Fixed

- Make `spork sync` install the exact published `spork-lang` toolchain together with its transitive dependencies, including `spork-pds`.

## [0.3.3] - 2026-08-29

### Added

- Publishable project builds that compile Spork libraries into importable Python packages.
- Runtime bootstrap and normal Python import lowering for generated modules.
- Installed-package Spork namespace discovery, copied `.spork` sources, source maps, package metadata, and wheel/sdist integration coverage.

### Fixed

- Clean build behavior and namespace resolution for both local and installed project dependencies.

## [0.3.2] - 2026-08-29

### Changed

- Standardized dotted calls for Spork namespaces, Python modules, and named object receivers.
- Enforced `:require` for Spork namespaces and `:import` for Python modules.

### Added

- Document-local LSP completion, hover, and navigation for imports and aliases.

### Fixed

- Spork source inspection on Python 3.12.

## [0.3.1] - 2026-08-28

### Changed

- Adopted `spork.pds` as the public persistent-data-structure namespace.
- Tightened dependencies and streamlined branch CI after extracting `spork-pds`.
- Expanded and machine-verified the language documentation.

### Fixed

- Compile `Callable` annotations containing parameter lists.

## [0.3.0] - 2026-08-28

### Changed

- Moved persistent data structures into the separately released [`spork-pds`](https://github.com/spork-it/spork-pds) package.
- Replaced `import-macros` with macro discovery through `ns` `:require` clauses.
- Converted `spork-lang` into a universal pure-Python wheel.

### Added

- Expanded x64 and ARM64 CI coverage across Linux, Windows, and macOS.

## [0.2.1] - 2025-12-12

### Changed

- Updated `cibuildwheel` to 3.3.0 for Python 3.14 wheel builds.

## [0.2.0] - 2025-12-12

### Added

- Python 3.14 support.
- Free-threaded CPython support for the bundled persistent data structures.
- Python 3.14 and free-threaded build and test jobs.

## [0.1.8] - 2025-12-11

### Added

- Extended reader macros for anonymous functions, slices, discarded forms, f-strings, paths, regular expressions, UUIDs, datetimes, and read-time evaluation.
- More Pythonic keyword-argument support.
- Comprehensive reader-macro tests and documentation.

## [0.1.7] - 2025-12-10

### Added

- Transient upgrade support for `IntVector` and `DoubleVector`.
- Generated persistent-data-structure benchmark reports.

## [0.1.6] - 2025-12-10

### Added

- `SortedVector` JSON serialization support.

### Changed

- Simplified namespace and macro-import internals and removed remnants of the earlier namespace design.

## [0.1.5] - 2025-12-09

### Changed

- Refactored and cleaned up the bundled persistent-data-structure C extension.
- Expanded fuzz testing and memory tracking.
- Expanded Windows CI and platform build coverage.

### Fixed

- C compiler warnings and Windows/macOS compatibility issues in the persistent-data-structure extension.

## [0.1.4] - 2025-12-09

### Added

- Pickle support for persistent data structures through `__reduce__`.
- Persistent collection fuzz-testing infrastructure and CI coverage.

## [0.1.3] - 2025-12-09

### Added

- `spork version` command.

### Fixed

- Ensure distributions generated by `spork dist` declare the Spork runtime dependency.

## [0.1.2] - 2025-12-09

### Added

- `async-with` language form and asynchronous project example.

### Changed

- Project entry points use the Python-style `namespace:function` format.
- Expanded project and language documentation.

## [0.1.1] - 2025-12-08

### Added

- Persistent `SortedVector`, including compiler/runtime integration and comprehensive tests.
- `stars` example project and expanded standard-library documentation.

## [0.1.0] - 2025-12-08

### Added

- Initial alpha release of the Spork Lisp-to-Python AST compiler.
- Expression-oriented Lisp syntax, immutable collection literals, macros, destructuring, pattern matching, protocols, classes, exceptions, generators, and async support.
- Bundled C-backed persistent vectors, maps, sets, typed vectors, transients, and lazy sequence operations.
- Python interoperability, type annotations, source-mapped errors, standard-library namespaces, and JSON support.
- CLI, REPL, nREPL server, LSP server, project scaffolding, dependency management, builds, distributions, editor support, and initial documentation.

[Unreleased]: https://github.com/spork-it/spork-lang/compare/v0.5.3...HEAD
[0.5.3]: https://github.com/spork-it/spork-lang/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/spork-it/spork-lang/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/spork-it/spork-lang/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/spork-it/spork-lang/compare/v0.4.4...v0.5.0
[0.4.4]: https://github.com/spork-it/spork-lang/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/spork-it/spork-lang/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/spork-it/spork-lang/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/spork-it/spork-lang/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/spork-it/spork-lang/compare/v0.3.8...v0.4.0
[0.3.8]: https://github.com/spork-it/spork-lang/compare/v0.3.7...v0.3.8
[0.3.7]: https://github.com/spork-it/spork-lang/compare/v0.3.6...v0.3.7
[0.3.6]: https://github.com/spork-it/spork-lang/compare/v0.3.5...v0.3.6
[0.3.5]: https://github.com/spork-it/spork-lang/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/spork-it/spork-lang/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/spork-it/spork-lang/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/spork-it/spork-lang/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/spork-it/spork-lang/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/spork-it/spork-lang/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/spork-it/spork-lang/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/spork-it/spork-lang/compare/v0.1.8...v0.2.0
[0.1.8]: https://github.com/spork-it/spork-lang/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/spork-it/spork-lang/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/spork-it/spork-lang/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/spork-it/spork-lang/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/spork-it/spork-lang/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/spork-it/spork-lang/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/spork-it/spork-lang/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/spork-it/spork-lang/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/spork-it/spork-lang/tree/v0.1.0
