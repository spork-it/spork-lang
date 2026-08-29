# Projects and CLI

This guide covers `spork.it`, project-aware commands, dependency environments, compilation, and distribution. For language syntax, see the [Language Reference](LANG.md); for core and `std.*` APIs, see the [Standard Library Reference](STDLIB.md).

## Create a project

```bash
spork new hello-spork
cd hello-spork
spork sync
spork test
spork run
```

`spork new` creates a project with this layout:

```text
hello-spork/
├── spork.it
├── src/
│   └── hello_spork/
│       └── core.spork
├── tests/
│   └── hello_spork/
│       └── core_test.spork
├── .gitignore
└── README.md
```

Project names are normalized to lower-case Lisp-style names. Underscores become hyphens and unsupported characters are removed.

Project-aware commands locate a project by searching the current directory and its parents for `spork.it`. They use the first (nearest) manifest found, so they may be run from any subdirectory of the project.

## The `spork.it` manifest

A manifest is a Spork map containing project metadata and tooling settings:

```clojure
{:name "hello-spork"
 :version "0.1.0"
 :description "A small Spork application"
 :requires-python ">=3.10"
 :spork-version ">=0.4.0,<0.5"
 :dependencies ["httpx>=0.27" "rich"]
 :dev-dependencies []
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
| `:requires-python` | no | `">=3.10"` | Python compatibility written to package metadata. |
| `:spork-version` | no | build version | Compatible `spork-lang` version specifier for built distributions. |
| `:api` | no | none | Generate public Spork and Python package APIs from one canonical namespace. |
| `:dependencies` | no | `[]` | Runtime package requirements accepted by `pip`. |
| `:dev-dependencies` | no | `[]` | Local tools installed by `spork sync --dev`. |
| `:optional-dependencies` | no | `{}` | Named Python package extras, such as `{:docs ["sphinx>=8"]}`. |
| `:source-paths` | no | `["src"]` | Directories searched for Spork namespaces and build inputs. |
| `:test-paths` | no | `["tests"]` | Directories searched by `spork test`. |
| `:main` | no | none | Entry point used by `spork run`, in `namespace:function` form. |
| `:readme` | no | `README.md` if present | README included in distribution metadata. |
| `:license` / `:license-file` | no | none / detected `LICENSE*` | SPDX license expression and license file. |
| `:authors` | no | `[]` | Author maps containing `:name` and/or `:email`. |
| `:keywords` / `:classifiers` | no | `[]` | PyPI search terms and trove classifiers. |
| `:urls` | no | `{}` | Labeled project links included in package metadata. |

Unknown keys are preserved by the configuration loader but are not interpreted by the current project commands.

### Dependencies

Each dependency is a normal `pip` requirement string:

```clojure
:dependencies ["requests>=2.32"
               "numpy>=2,<3"]
```

Add or remove runtime dependencies from any directory below the project root:

```bash
spork add httpx "rich>=13"
spork remove httpx rich
```

Each command reports the absolute path of the nearest `spork.it` it changes. Requirements added with `spork add` use normal `pip` syntax. `spork remove` accepts a distribution name and removes its configured requirement even when that requirement contains extras or a version constraint.

After changing dependencies, run:

```bash
spork sync
```

This creates an isolated `.venv/` when needed and installs the dependencies and the Spork runtime. Include development tools when working on the project with:

```bash
spork sync --dev
```

An existing environment is not automatically resynchronized on every `spork run`.

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

A public package namespace can also live at `acme/tools/__init__.spork`. This allows `(:require [acme.tools :as tools])` while implementation namespaces remain below the package. Public package initializers are normally generated through `:api`.

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
| `spork add <package...>` | Adds or updates runtime requirements in the nearest `spork.it`. |
| `spork remove <package...>` | Removes runtime requirements from the nearest `spork.it`. |
| `spork sync` | Creates `.venv` and installs the manifest dependencies and Spork runtime. |
| `spork run [args...]` | Loads and calls the configured entry point. Creates the environment if it is missing. |
| `spork test` | Discovers and runs declared and legacy Spork tests. |
| `spork build` | Compiles all `.spork` files under `:source-paths` into `.spork-out/`. |
| `spork dist` | Builds compiled output, then creates a wheel and source distribution in `dist/`. |
| `spork clean` | Removes `.venv/`. |
| `spork clean --all` | Also removes build and distribution artifacts. |
| `spork lsp` | Starts the Language Server Protocol server on standard input/output. |
| `spork version` | Prints the Spork, Python, and platform versions. |

Use `spork <command> --help` for command-specific options. Install any project-specific development dependencies before testing with `spork sync --dev`.

## Testing

Declare a test with the top-level `deftest` form. Test bodies are registered when a namespace loads but are not executed by `spork run`, direct file execution, normal namespace loading, or project builds.

```clojure
(ns hello-spork.core)

(defn greet [name]
  (+ "Hello, " name "!"))

(deftest greet-works
  (assert (= (greet "Spork") "Hello, Spork!")))
```

`spork test` discovers:

- `test_*.spork` and `*_test.spork` recursively below `:test-paths`, preserving support for existing script-style test files; and
- any `.spork` file containing a direct top-level `deftest` below either `:source-paths` or `:test-paths`.

Each declared test runs independently, and an uncaught exception marks only that declaration as failed. Async declarations written as `(deftest ^async name ...)` are awaited by the runner. Files are isolated in separate processes. A convention-named legacy file with no declarations remains one test: its top-level forms run as before, and any uncaught exception fails the file.

A `deftest` name must be a valid unqualified symbol, declarations take no parameters, `^async` is the only supported test metadata, and duplicate normalized names in one file are rejected. Test files should not mix declarations with top-level assertions because top-level code runs while the file is being loaded, before declared tests begin.

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
    ├── core.spork
    └── core.spork.map.json
```

The generated Python initializes the Spork runtime and lowers project `:require` clauses to normal Python imports, so it can be imported without the Spork CLI. Original `.spork` files are copied beside it for source inspection and for Spork consumers of an installed package. Hand-written `.py`, `.pyi`, and `py.typed` files under source roots are also copied for projects that do not configure a generated API.

Choose another output directory with `spork build --out-dir PATH`.

### Generated public APIs and typing

Libraries can expose idiomatic package-level APIs to both languages without maintaining facade files by adding `:api` to `spork.it`:

```clojure
:api
{:from "my-spork-library.core"
 :spork {:namespace "my-spork-library"
         :exports ["Widget" "make-widget" "widget?"]}
 :python {:package "my-spork-library"
          :exports ["Widget" "make-widget" "widget?"]
          :aliases {"widget?" "is-widget"}
          :version true
          :typed true}}
```

`:from` identifies the one canonical implementation namespace. The `:spork` section generates `my_spork_library/__init__.spork`, making `(:require [my-spork-library :as library])` resolve to the declared public exports. The `:python` section generates explicit imports in `my_spork_library/__init__.py`, including both `widget_q` and its `is_widget` alias. Each target has its own export list so Spork APIs can retain names such as `swap!` and `atom?` while Python exposes conventional identifiers.

With `:version true`, the Python initializer receives `__version__` directly from the manifest. With `:typed true`, every compiled Spork module receives a generated `.pyi`, the Python package receives `__init__.pyi`, and `py.typed` is created automatically. Existing non-empty hand-written files at generated paths are rejected rather than overwritten. Either the `:spork` or `:python` section may be omitted when a library only needs one target.

Spork annotations become Python signatures and generic stubs:

```clojure
(ns my-spork-library.core
  (:import [typing :refer [Callable Generic TypeVar]]))

(def T (TypeVar "T"))

(defclass Box [(Generic T)]
  (defn __init__ [self ^T value]
    (set! self._value value))

  (defn ^property ^T value [self]
    self._value))

(defn ^(Box T) box [^T value]
  (Box value))

(defn ^T update [^(Box T) boxed ^(Callable [[...] T]) function]
  (function boxed.value))
```

A parenthesized `Generic` base compiles to Python subscription syntax (`Generic[T]`). Capitalized generic return types such as `^(Box T)` are recognized as annotations, and `Callable` accepts `...` for arbitrary arguments. AOT modules use postponed annotation evaluation, so forward and recursive generic references are safe.

The generated package files are build artifacts: do not add source `__init__.spork`, `__init__.py`, `__init__.pyi`, module `.pyi`, or `py.typed` files at paths owned by `:api`.

## Build distributions

```bash
spork dist --clean
```

By default this rebuilds `.spork-out/` and creates both a wheel and source distribution in `dist/`. The generated package metadata includes the configured Spork compatibility range, runtime dependencies, optional extras, README, license, authors, classifiers, and project URLs from `spork.it`. `--clean` removes stale build and distribution output before rebuilding.

Useful variants:

```bash
spork dist --wheel-only
spork dist --sdist-only
spork dist --no-build       # reuse existing compiled output
spork dist --dist-dir artifacts
```

### Consuming a published Spork library

Add the normal PyPI requirement to another project's manifest:

```clojure
:dependencies ["my-spork-library>=1,<2"]
```

After `spork sync`, packaged Spork source is discovered directly from the project's site-packages and can be required normally:

<!-- verify-docs: skip=external-package -->
```clojure
(ns my.app
  (:require [my-spork-library :as library]))
```

The same wheel exposes its compiled modules to Python using normalized package names:

```pycon
>>> from my_spork_library.core import public_function
```

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
