# Spork

[![Tests](https://github.com/spork-it/spork-lang/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/spork-it/spork-lang/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/spork-lang)](https://pypi.org/project/spork-lang/)

Spork is a Lisp hosted on CPython. It compiles to Python AST, interoperates directly with Python libraries, and adds macros, expression-oriented syntax, immutable collections, and project tooling.

## Highlights

- Direct access to Python modules and objects—no FFI layer or separate VM.
- Lisp macros and homoiconic syntax.
- Persistent vectors, maps, sets, and related types from [`spork-pds`](https://github.com/spork-it/spork-pds).
- Pattern matching, destructuring, async/await, protocols, decorators, and Python type annotations.
- Source-mapped tracebacks that point back to `.spork` files.
- A REPL, nREPL server, LSP server, and project commands in one CLI.

Spork supports CPython 3.10 through 3.14, including free-threaded CPython 3.14.

## Installation

Install the CLI in an isolated environment with `pipx`:

```bash
pipx install spork-lang
```

Use `pip` when adding Spork to an existing Python environment:

```bash
python -m pip install spork-lang
```

On Linux, macOS, or WSL, the installer script is also available:

```bash
curl https://raw.githubusercontent.com/spork-it/spork-lang/refs/heads/main/install.sh | sh
```

## Quick start

Start the REPL:

```text
$ spork
Spork REPL - A Lisp for Python
user> (+ 1 2 3)
6
user> (doall (map inc [1 2 3]))
[2 3 4]
```

Or create `hello.spork`:

```clojure
(defn greet [name]
  (fmt "Hello, {}!" name))

(print (greet "Spork"))
```

Run it with:

```text
$ spork hello.spork
Hello, Spork!
```

Spork collections are immutable and structurally shared:

```clojure
(def original {:name "Spork" :version 1})
(def updated (assoc original :version 2))

(print original) ; {:name 'Spork' :version 1}
(print updated)  ; {:name 'Spork' :version 2}
```

## Python interoperability

Import Python modules and call them directly:

```clojure
(ns example
  (:require [std.json :as json])
  (:import [pathlib :refer [Path]]))

(def path (Path "data.json"))
(print (json.dumps {:path (str path)}))
```

To import `.spork` modules from Python, import `spork` once to install its import hook:

```python
import spork
from my_spork_module import greet

print(greet("Python"))
```

Spork exposes the separately distributed persistent collections under the `spork.pds` namespace:

```python
from spork.pds import vec

original = vec(1, 2, 3)
updated = original.conj(4)
```

See the [`spork-pds` documentation](https://github.com/spork-it/spork-pds/tree/main/docs) for its Python API, design, and benchmarks.

## Projects

Create and run a project:

```bash
spork new my-project
cd my-project
spork sync
spork run
```

A `spork.it` manifest defines metadata, dependencies, source paths, and the entry point. Libraries can also declare a unified `:api`; Spork then generates idiomatic package-level Spork and Python APIs, version metadata, generic `.pyi` stubs, and `py.typed` from one annotated implementation namespace.

Common commands include:

| Command | Purpose |
| --- | --- |
| `spork repl` | Start a project-aware REPL |
| `spork sync` | Create the project environment and install dependencies |
| `spork run` | Run the configured entry point |
| `spork test` | Run declared Spork and Python tests |
| `spork build` | Compile sources to Python in `.spork-out/` |
| `spork dist` | Build a wheel and source distribution |
| `spork lsp` | Start the language server |

Run `spork --help` for the complete CLI reference.

## Documentation

- [Changelog](CHANGELOG.md)
- [Documentation index](docs/README.md)
- [Language reference](docs/LANG.md)
- [Standard library reference](docs/STDLIB.md)
- [Projects and CLI](docs/PROJECTS.md)
- [Examples](examples/)
- [Emacs mode](editors/emacs/) and [Neovim support](editors/nvim/)
- [`spork-pds` API, design, and benchmarks](https://github.com/spork-it/spork-pds/tree/main/docs)

## Development

```bash
git clone https://github.com/spork-it/spork-lang.git
cd spork-lang
make venv
make test
.venv/bin/python -m pytest
```

Use `make help` for development, packaging, and cleanup targets.

## License

[MIT](LICENSE)
