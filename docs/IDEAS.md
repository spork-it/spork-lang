# Future Ideas

This document records exploratory designs. Nothing here is part of the supported language, CLI, or project-manifest format, and the syntax may change or never be implemented.

For implemented behavior, use the canonical documentation at [spork.sh/docs](https://spork.sh/docs/).

## Dynamic module loading

### Motivation

Spork currently resolves normal imports through the module-level `ns` form. A runtime loading form could support optional integrations and modules selected from configuration while keeping the loaded name scoped to a body.

### Sketch

<!-- verify-docs: skip=future-syntax -->
```clojure
; Load a module and bind it for the body.
(with-module [json "json"]
  (json.dumps {:status "ok"}))

; Run the body only when the module can be loaded.
(with-module? [feature "optional_feature"]
  (feature.enable))
```

Open design questions include:

- whether module names are symbols, strings, or either;
- whether loading supports Spork namespaces, Python modules, or both;
- what `with-module?` returns when the module is absent;
- how aliases and referred names interact with lexical scope;
- whether loading is cached through Python's normal module cache;
- how static tools and the LSP report dynamically introduced names.

## Plugin system

### Motivation

A plugin system could let separately installed packages extend compiler and tooling behavior without requiring changes in the Spork repository.

Possible extension points include:

- compiler lifecycle hooks;
- runtime initialization hooks;
- traceback and debugger hooks;
- CLI subcommands;
- reader forms;
- injected builtins or macros;
- REPL commands;
- LSP capabilities.

For example, a profiler plugin might recognize `^profile` metadata and wrap selected function bodies with timing instrumentation:

```bash
python -m pip install spork-profiler
```

A project could then enable and configure the installed plugin in `spork.it` rather than activating every discoverable package globally.

### Design constraints

Any plugin design should address:

- **Explicit activation:** installing a package should not silently execute arbitrary hooks in every Spork process.
- **Discovery:** entry points or another standard packaging mechanism should identify plugins without scanning imports.
- **Ordering:** hook order and conflicts must be deterministic.
- **Isolation:** one project's configuration should not unexpectedly affect another project.
- **Compatibility:** plugins need a declared Spork API/version range.
- **Diagnostics:** startup and compilation errors should identify the responsible plugin.
- **Tooling:** the REPL, compiler, build command, and LSP need a consistent activated plugin set.
- **Security:** compiler hooks and read-time extensions execute code with the user's permissions and must be treated as trusted dependencies.

A reserved namespace such as `spork.plugins.profiler` could make plugin-provided APIs recognizable, but namespace injection should not hide the package that owns the implementation.

## Proposal process

Before promoting an idea into the references:

1. define user-facing semantics and failure behavior;
2. prototype the smallest useful API;
3. add compiler/runtime and tooling tests;
4. document compatibility and security implications;
5. move the implemented behavior to the appropriate reference document.
