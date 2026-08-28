# Projects and CLI

This guide covers `spork.it`, project-aware commands, dependency environments, compilation, and distribution. For language syntax, see the [Language Reference](LANG.md); for core and `std.*` APIs, see the [Standard Library Reference](STDLIB.md).

## Create a project

```bash
spork new hello-spork
cd hello-spork
spork sync
spork run
```

`spork new` creates a project with this layout:

```text
hello-spork/
├── spork.it
├── src/
│   └── hello_spork/
│       └── core.spork
├── .gitignore
└── README.md
```

Project names are normalized to lower-case Lisp-style names. Underscores become hyphens and unsupported characters are removed.

Project-aware commands locate a project by searching the current directory and its parents for `spork.it`, so they may be run from a subdirectory of the project.

## The `spork.it` manifest

A manifest is a Spork map containing project metadata and tooling settings:

```clojure
{:name "hello-spork"
 :version "0.1.0"
 :description "A small Spork application"
 :dependencies ["httpx>=0.27" "rich"]
 :source-paths ["src"]
 :test-paths ["tests"]
 :main "hello-spork.core:main"}
```

Paths are relative to the directory containing `spork.it`.

| Key | Required | Default | Purpose |
| --- | --- | --- | --- |
| `:name` | yes | — | Project and distribution name. |
| `:version` | yes | — | Project version string. |
| `:description` | no | none | Distribution description. |
| `:dependencies` | no | `[]` | Package requirements accepted by `pip`. |
| `:source-paths` | no | `["src"]` | Directories searched for Spork namespaces and build inputs. |
| `:test-paths` | no | `["tests"]` | Declares test source locations; no project test command consumes this setting yet. |
| `:main` | no | none | Entry point used by `spork run`, in `namespace:function` form. |

Unknown keys are preserved by the configuration loader but are not interpreted by the current project commands.

### Dependencies

Each dependency is a normal `pip` requirement string:

```clojure
:dependencies ["requests>=2.32"
               "numpy>=2,<3"]
```

After changing dependencies, run:

```bash
spork sync
```

This creates an isolated `.venv/` when needed and installs the dependencies and the Spork runtime. An existing environment is not automatically resynchronized on every `spork run`.

### Source paths and namespaces

A namespace maps to a `.spork` file below a source path. For example:

```text
src/acme/tools/core.spork
```

contains:

```clojure
(ns acme.tools.core)
```

and can be required as:

```clojure
(ns acme.app
  (:require [acme.tools.core :as tools]))
```

Hyphens in Spork identifiers are normalized to underscores for Python compatibility. Use the Lisp-style spelling in Spork source and keep namespace declarations consistent with their paths.

## Entry points and arguments

Given this manifest entry:

```clojure
:main "hello-spork.core:main"
```

`spork run` loads the namespace and calls `main`. If `:main` contains only a namespace, the function name defaults to `main`.

```clojure
(ns hello-spork.core)

(defn main [& args]
  (print "arguments:" args)
  0)
```

Pass command-line arguments after `run`:

```bash
spork run one two
```

Arguments arrive as strings. If the entry point returns an integer, Spork uses it as the process exit status. Override the manifest entry point for one invocation with:

```bash
spork run --main other.namespace:start one two
```

## Project commands

| Command | Behavior |
| --- | --- |
| `spork repl` | Starts a REPL with project source paths and `.venv` packages available. Creates the environment if it is missing. |
| `spork sync` | Creates `.venv` and installs the manifest dependencies and Spork runtime. |
| `spork run [args...]` | Loads and calls the configured entry point. Creates the environment if it is missing. |
| `spork build` | Compiles all `.spork` files under `:source-paths` into `.spork-out/`. |
| `spork dist` | Builds compiled output, then creates a wheel and source distribution in `dist/`. |
| `spork clean` | Removes `.venv/`. |
| `spork clean --all` | Also removes build and distribution artifacts. |
| `spork lsp` | Starts the Language Server Protocol server on standard input/output. |
| `spork version` | Prints the Spork, Python, and platform versions. |

Use `spork <command> --help` for command-specific options.

## Build output

```bash
spork build --clean
```

The default output is `.spork-out/`. Each source module produces Python source plus a source-map sidecar:

```text
.spork-out/
├── pyproject.toml
└── hello_spork/
    ├── __init__.py
    ├── core.py
    └── core.spork.map.json
```

The generated Python is useful for inspection and Python tooling. Runtime tracebacks still refer to the original `.spork` source locations.

Choose another output directory with `spork build --out-dir PATH`.

## Build distributions

```bash
spork dist --clean
```

By default this rebuilds `.spork-out/` and creates both a wheel and source distribution in `dist/`. The generated package metadata includes the current `spork-lang` version and the dependencies from `spork.it`.

Useful variants:

```bash
spork dist --wheel-only
spork dist --sdist-only
spork dist --no-build       # reuse existing compiled output
spork dist --dist-dir artifacts
```

Because project packaging is still alpha, inspect generated metadata and test the artifacts in a clean environment before publishing them.

## Standalone commands

A manifest is not required for individual files or command-line expressions:

```bash
spork script.spork
spork -c '(print (+ 1 2 3))'
spork -e script.spork       # print generated Python
spork -i script.spork       # run, then enter the REPL
```

Run `spork` without arguments to start a standalone REPL.

## Troubleshooting

### Project not found

Run the command inside the directory containing `spork.it` or one of its descendants. Check that the filename is exactly `spork.it`.

### Namespace not found

Verify all three locations agree:

1. the directory below a configured `:source-paths` entry;
2. the `.spork` filename;
3. the name in the file's `(ns ...)` declaration.

For `src/acme/core.spork`, the expected namespace is `acme.core`.

### A dependency cannot be imported

Run `spork sync` after editing `:dependencies`. If the environment is stale or damaged, recreate it:

```bash
spork clean
spork sync
```

### Editor integration

Use `spork lsp` for LSP clients or `spork --nrepl` for nREPL clients. Repository integrations are available for [Emacs](../editors/emacs/) and [Neovim](../editors/nvim/).
