# Spork

[![Tests](https://github.com/spork-it/spork-lang/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/spork-it/spork-lang/actions/workflows/test.yml) 
![PyPI - Version](https://img.shields.io/pypi/v/spork-lang)

Spork is a Lisp that runs on Python. It gives you the expressive power of macros, immutable data structures, and a modern REPL driven development experience.

Spork compiles to Python AST and can be imported directly via a standard import hook. This gives you seamless interoperability with existing Python libraries and tools. No wrappers (unless you want a lispy one) or FFI layers are needed, just continue using your favorite Python libraries.

Spork adds features that Python natively lacks, such as:

*  **Persistent Data Structures** that are immutable by default with [near-free snapshot](#performance) copies
*  **Predictable data flow** with no hidden mutation or shared state surprises
*  **Expression oriented syntax** that reduces boilerplate and enables powerful macros


## **Alpha Warning**

Spork is currently in alpha. The language, standard library, and tooling are all under active development. Breaking changes may occur between releases. We welcome feedback, issues, and contributions!

## What Spork Isn't

To avoid any confusions, here's what Spork is not:

*  **Not a Python Replacement:** The runtime of Spork _is_ Python.
*  **Not a new VM or JIT:** Spork compiles to Python AST and runs on CPython.
*  **Not an abstraction over Python:** Spork embraces Python rather than hiding it.
*  **Not a strict clone of Clojure:** Spork's ideas rhyme but we still try our best to be "Pythonic".
*  **Not a fork of Hy:** While both are Lisps on Python, Spork has a different design philosophy.

## Philosophy

Spork is built on a few core opinions:

1.  **The Python Ecosystem is Great:** We want access to NumPy, PyTorch, Django, and the massive repository of PyPI packages. We do not want to rewrite the world.
2.  **Data Integrity:** Python's mutable defaults are convenient for scripts but dangerous for systems. Spork fixes this at the foundation. `[1 2 3]` isn't a Python list; it is a persistent vector. Your data is immutable by default, ensuring that state management remains predictable as complexity grows.
3.  **Unified Tooling:** Spork includes a unified toolchain to manage compilation, REPL, and testing, similar to `cargo` or `go`. It handles the bridge between Spork source and the Python environment so you don't have to configure build hooks manually.
4.  **Pragmatism:** We believe a hosted language should not fight its host. Spork compiles directly to Python AST. When you need raw performance or side effects, the escape hatch to Python's native mutability and types is always open.

> It's a philosophy that tries to balance expressiveness and restraint, plenty of room to create, while minimizing room to trip.

## Installation

### As a User

The recommended way to install Spork is via the `install.sh` script or `pipx`. Both options isolate the tool environment while making the CLI globally available.

**Prerequisites:** Python 3.10+ and pip installed.

**Using the `install.sh` script (Linux/MacOS/WSL):**

Recommended for most users as it doesn't rely on anything but Python. Spork will be installed to `~/.local/bin/spork` and a virtual environment will be created at `~/.spork/venv`. Upgrading is as simple as re-running the script.

```bash title="Install Spork via install.sh"
$ curl https://raw.githubusercontent.com/spork-it/spork-lang/refs/heads/main/install.sh | sh
```

**Using Pipx (Linux/MacOS/Windows/WSL):**

Recommended if you already use `pipx` to manage your Python CLI tools.

```bash title="Install Spork via pipx"
$ pipx install spork-lang
```

Continue to the [Quick Start](#quick-start) section for details.

**Using Pip (Linux/MacOS/Windows/WSL):**

Recommended when you are embedding Spork in an existing Python project.

```bash title="Install Spork via pip"
$ pip install spork-lang
```

Continue to the [Using Spork in an existing Python project](#using-spork-in-an-existing-python-project) section for details.

### For Developing Spork

If you wish to contribute to Spork or modify the compiler:

You'll first need to clone the repository and set up the virtual environment.

```bash title="Set up Spork Development Environment"
$ git clone https://github.com/spork-it/spork-lang.git

$ cd spork-lang

# Sets up virtual environment and builds C extensions
$ make venv

# Run the test suite
$ make test

# Enter the Spork REPL using the development environment
$ bin/spork 
```

## Quick Start

### The REPL

Once installed, simply run `spork` to enter the Read-Eval-Print Loop.

```bash
$ spork
Spork REPL - A Lisp for Python
user> (+ 1 2 3)
6
user> (map inc [1 2 3])
[2 3 4]
```

### Hello world

Create a file named `hello.spork`:

```clojure title="hello.spork"
;; hello.spork
(defn greet [name]
  (print (fmt "Hello, {}!" name)))

(greet "Spork")
```

Run it with:

```bash title="Run hello.spork"
$ spork hello.spork
Hello, Spork!
```

## Core Language Features

### Immutable Data Structures

Spork provides Persistent Data Structures (PDS) implemented in C for performance. These are the default literals in the language.

```clojure
;; Vectors
(def v [1 2 3])
(def v2 (conj v 4))
(print v)  ; [1 2 3] - original is unchanged
(print v2) ; [1 2 3 4] - new structure sharing memory with old

;; Maps
(def m {:name "Spork" :version 1})
(def m2 (assoc m :version 2))
(print m)  ; {:name "Spork", :version 1}
(print m2) ; {:name "Spork", :version 2}

;; Sets
(def s #{1 2 3})
(contains? s 2) ; true

; create new subset of s without 2
(def s2 (disj s 2)) 
(print s)  ; #{1 2 3}
(print s2) ; #{1 3}
```

### Python Interop

Spork compiles to Python, so interop is seamless.

```clojure
;; Imports
(ns examples
  (:import [os] [random] [antigravity]) ; Python stdlibs
  (:require [std.json :as j])           ; spork stdlib

;; Method calls (dot syntax)
(def text "hello world")
(.upper text) ; "HELLO WORLD"

;; Attribute access
(print os.name) ; e.g. "posix" or "nt"

;; Mixing Python types (escape hatch)
(def py-list (list [1 2 3])) ; Convert Spork Vector to Python list
(.append py-list 4)          ; Mutate it in place
(py-list.append 5)           ; alternative call syntax

(print py-list) ; [1, 2, 3, 4, 5]

(def data {:name "Spork" :version 1.0}) ; Immutable Spork Map
(print (j.dumps data)) ; '{"name": "Spork", "version": 1.0, "nums": [1, 2, 3, 4, 5]}'
```

> Python objects and Spork objects interoperate freely, no wrappers or FFI layers.
 thanks to structural sharing
### Async/Await

Spork has first-class support for Python's async/await ecosystem.

```clojure
;; a simple async function to fetch JSON data
(defn ^async fetch-data [^str url]
  (async-with [session (aiohttp.ClientSession)]
    (async-with [resp (.get session url)]
      (await (.json resp)))))
```

### Pattern Matching

Spork includes structural pattern matching out of the box. With `match`, you can destructure and branch on data shapes concisely.

```clojure 
(defn describe [x]
  (match x
    0 "zero"
    (^int n) (+ "integer: " (str n))
    [a b] (+ "vector pair: " (str a) ", " (str b))
    {:keys [name]} (+ "Hello " name)
    _ "something else"))
```

### Annotations & Decorators (Metadata)

Spork supports Python type hints using metadata syntax. These compile down to standard Python type annotations.

```clojure
(defn ^int add [^int x ^int y]
  (+ x y))
```

Compiles to:

```python
def add(x: int, y: int) -> int:
    return x + y
```

This also applies to decorators in Python like @staticmethod or @classmethod.

```clojure
(defclass MyClass []
  (defn ^staticmethod static-method [^str msg]
    (print msg)))

(MyClass.static-method "Hello from static method") 
```

### Macros

As a Lisp, Spork allows you to extend the compiler via macros.

```clojure
(defmacro unless [test & body]
  `(if ~test
     nil
     (do ~@body)))

(unless (= (add 1 1) 3)
  (print "Math still works"))
```

### Examples

> Below is a complete Spork program that demonstrates macros, Python interop, pattern matching, type annotations, and persistent data structures while fetching data from the GitHub API. [GitHub Stars Project](examples/stars)

```clojure title="stars/core.spork"
(ns stars.core
  (:import
    [requests]
    [time :as t]))

;; Simple profiling macro using Python's time.perf_counter
(defmacro profile [label & body]
  `(let [start# (t.perf_counter)
         result# (do ~@body)
         end# (t.perf_counter)
         elapsed# (- end# start#)]
     (print (+ ~label " took " (str elapsed#) "s"))
     result#))

;; Fetch the star count for a given GitHub repo full name
(defn ^int fetch-stars [^str full-name]
  (let [resp (requests.get (+ "https://api.github.com/repos/" full-name))]
    (match resp.status_code
      200 (get (resp.json) "stargazers_count")
      404 0                                     ; missing repo → 0 stars
      _   (throw (RuntimeError "GitHub API error")))))

;; Get top repos by star count
(defn top-repos [names]
  ;; Returns a SortedVector of Maps with :name and :stars
  [sorted-for [full-name names]
                 {:name full-name
                  :stars (fetch-stars full-name)}
              :key :stars :reverse true])

(defn main []
  (let [repos ["pallets/flask"
               "django/django"
               "tiangolo/fastapi"
               "psf/requests"]
        ranked (profile "GitHub fetch" (top-repos repos))]
    (for [row ranked]
      (let [{:keys [name stars]} row]
        (print stars "-" name)))))

(main)
;; Example Output:
; GitHub fetch took 0.1801389280008152s
; 92823 - tiangolo/fastapi
; 86079 - django/django
; 70890 - pallets/flask
; 53551 - psf/requests
```


## Error Reporting

Spork provides source-mapped error reporting, meaning that runtime errors point to the original `.spork` source files with accurate line numbers and code context—not the generated Python code.

### Example

Given this Spork file:

```clojure title="math.spork"
;; math.spork
(defn divide [a b]
  (/ a b))

(defn nested-call [x]
  (let [y (divide x 0)]
    (+ y 10)))

(defn deep-stack []
  (nested-call 42))

(deep-stack)
```

Running it produces a traceback that references the original Spork source:

```
Error: division by zero
Traceback (most recent call last):
  File "math.spork", line 12, in <module>
    (deep-stack)
    ~~~~~^~~~~~~
  File "math.spork", line 10, in deep_stack
    (nested-call 42))
    ^^^^^^^^^^^^^^^^
  File "math.spork", line 6, in nested_call
    (let [y (divide x 0)]
            ^^^^^^^^^^^^
  File "math.spork", line 3, in divide
    (/ a b))
    ^^^^^^^
ZeroDivisionError: division by zero
```


## Spork Project Management

For standalone Spork projects, `spork.it` files provide a unified manifest similar to `cargo.toml` or `package.json`. Saving you from managing virtual environments, dependencies, and build scripts manually.

Note: If you are just adding Spork files to an existing Python application, you don't need a `spork.it` file. See [Using Spork in an existing Python project](#using-spork-in-an-existing-python-project) for details.

### Creating a Project

Spork includes a scaffolding tool to set up a standard project structure with dependency management.

```bash
$ spork new my-project
✓ Created new Spork project: .../my-project

Next steps:
  cd my-project
  spork run       # Run the project entrypoint
  spork repl      # Start the REPL in the project context
  
$ cd my-project/

$ tree
.
├── README.md
├── spork.it
└── src
    └── my-project
        └── core.spork

3 directories, 3 files

$ spork run
Project venv not found, initializing...
Creating virtual environment at .../my-project/.venv...
  ✓ Created virtual environment
  ✓ Upgraded pip
  ✓ Installed spork-lang (copied from current environment)
✓ All dependencies installed

Welcome to my-project!
```

### Project Structure (`spork.it`)

This generates a `spork.it` configuration file (the Spork equivalent of pyproject.toml), a source directory, and a test directory.


Spork aims to unify the fragmented Python tooling ecosystem. A project is defined by a `spork.it` file:

```clojure title="spork.it"
{:name "my-project"
 :version "0.1.0"
 :dependencies ["requests" "numpy>=1.20"]
 :source-paths ["src"]
 :test-paths ["tests"]
 :main "my-project.core:main"}
```

Commands:
*   `spork sync`: Creates a virtual environment and installs dependencies defined in `spork.it`.
*   `spork run`: Runs the project's main function.
*   `spork repl`: Starts a REPL with the project's source roots and dependencies loaded.
*   `spork build`: Compiles Spork source files to Python `.py` files in a `.spork-out/` directory.
*   `spork dist`: Builds a distributable package (wheel & archives) for the project.

## Using Spork in an existing Python project

1. Install Spork:

```bash
$ pip install spork-lang
```

2. Import `spork` **once** at startup to register the import hooks:

```python
# e.g. in your app's __init__.py or main.py
import spork
```
> This uses a standard `importlib` hook to allow importing `.spork` files as if they were Python modules.

3. Create a Spork module:

```clojure
;; my_module.spork
(defn add [x y]
  (+ x y))
  ```

4. Import it from Python:

```python
from my_module import add
print(add(1, 2))  # 3
```
> If you forget step 2 (`import spork`), Python will just say `ModuleNotFoundError: No module named 'my_module'` because the .spork import hook hasn’t been installed yet.

### Using Spork Persistent Data Structures from Python
You can use Spork's persistent data structures directly in Python by importing them from the `spork.runtime.pds` module. This gives Python developers access to the same immutable collections used in Spork.

```python
from spork.runtime.pds import Vector, vec

v: Vector = vec([1, 2, 3])
v2 = v.conj(4)
print(v)   # Vector([1, 2, 3])
print(v2)  # Vector([1, 2, 3, 4])
```


## Why Lisp?

Spork is a Lisp because we believe in Homoiconicity: the code is represented by the language's own data structures.

1.  **Metaprogramming:** Because code is data, you can write code that writes code (Macros). This allows you to add features that look like language primitives (like the `match` or `unless` examples above) without waiting for the compiler developers to implement them.
2.  **Structural Editing:** Tools like Parinfer or Paredit make editing code structurally (moving entire blocks, expressions, or function bodies) significantly faster and less error-prone than editing line-based languages like Python.
3.  **Expression Oriented:** In Spork, almost everything is an expression that returns a value. `if`, `let`, and `do` blocks all return values, reducing the need for temporary variables and side effects.

> Lisp's superpower is treating code as data, which means Spork can grow with you, not just run what you write. It's like having a language that politely asks: "Would you like to customize the universe today?"


## Under the Hood

Spork is not just a syntax skin; it is a runtime system optimized for the Python memory model.

*   **Native Persistence:** Spork's data structures are not wrappers. They are custom C extensions.
    *   **Vectors:** 32-way Bit-Partitioned Tries (similar to Clojure/Rust im-rs).
    *   **SortedVector:** Persistent Red Black Tree built for sorted collections.
    *   **Maps & Sets:** Hash Array Mapped Tries (HAMT).
*   **Transient Internals:** The runtime utilizes mutable "Transients" internally to construct immutable results. This ensures that Spork remains performant at the boundary between mutation and persistence, giving you safety without the typical "copy-everything" penalty.
*   **Source Mapping:** We track every AST node back to its origin. When an error happens, Spork points to *your* code, not the generated Python.

### Performance

Spork prioritizes safety over raw mutation speed. 

*  **Reads:** Comparable to native Python collections 
*  **Updates:** Slower than raw mutation, but significantly faster than defensive copying.
*  **Snapshots:** Orders of magnitude faster. Because of structural sharing, "copying" a Spork Vector is effectively free.

Comparison of Spork Persistent Vector vs Native Python List for common operations:

| Operation (N=100k) | Python (Native) | Spork (PDS) | Difference |
| :--- | :--- | :--- | :--- |
| **Read** (Random Index) | ~0.8 ms | ~2.2 ms | ~2.8x Slower |
| **Write** (Append) | ~5.8 ms | ~8.2 ms | ~1.4x Slower |
| **Copy & Update** | 143.13 µs | **1.44 µs** | **~100x Faster** |

> Note: Spork includes specialized `IntVector` and `DoubleVector` types. These support the Buffer Protocol but need further testing and benchmarking to verify zero-copy interop performance (promising early results).

## Roots

*   **Clojure:** The primary inspiration for our syntax and the sequence abstraction. We admire Clojure's discipline, but Spork is native to Python, not a JVM port.
*   **Rust/Cargo:** The inspiration for our unified tooling and project structure (`spork.it`).
*   **Python:** The host we love to live in. Spork is designed to be a good citizen of the Python ecosystem.


## Editor Support

Spork ships with early Neovim and Emacs modes located in the repository (`editors/` directory). These provide basic syntax highlighting and are useful for experimentation, but are not yet feature-complete. We recommend Parinfer or similar structural editing tools, these are not a replacement for them.

We have plans to author and maintain the core editor modes/plugins as first-class projects in the Spork ecosystem because we believe that editor support is essential for a great developer experience.

### Current support includes:
*  [Emacs](editors/emacs): major mode, syntax rules, REPL integration with symbol lookup and evaluation.
    -  REPL server can be started within Emacs using `C-c C-j` or `M-x spork-jack-in RET`
    -  Evaluate buffer, region, or current expression with `C-c C-b`, `C-c C-r`, and `C-c C-c` respectively.
        * The output will be displayed in a separate REPL buffer.
    -  Documentation and type information available via `C-c C-d` on a symbol and `C-c i` for the inspector (currently basic).
    -  bug with `rainbow-delimiters-mode` incorrectly highlighting on closing `]` with spork-mode.
    -  `parinfer-rust-mode` seems to work well with spork-mode for structural editing.
*  [Neovim](editors/nvim): syntax highlighting, basic indentation, and LSP integration
    -  LSP server implementation with:
        *  Completion (builtins and symbols)
        *  Go-to-Definition
        *  Diagnostics (line errors, error reporting needs improved)
        *  Hover support
    -  Currently using Vim scripts for syntax highlighting and indentation rules once tree sitter grammar is available we will migrate to that.

Emacs `spork-mode` is currently more feature complete than the LSP mode, but both are under active development.

### Currently missing:
*  **Tree Sitter Grammar:** A Tree Sitter grammar for Spork would enable advanced syntax highlighting, code folding, and structural navigation in editors that support Tree Sitter.
*  **LSP Features:** The Spork LSP server needs testing and additional features to feel like a solid experience.
    -  Refactoring support (rename symbol, extract function)
    -  Static analysis and type checking (call out to python based tools or build our own?)
    -  Code formatting support
    -  Code actions and quick fixes
    -  Better diagnostics and error reporting
    -  Macro expansion view
*  **Neovim:**
    -  Planned network REPL integration for evaluation and interactive development.
    -  Inspector integration for drilling into data structures.
*  **VSCode:** No official support yet, but planned via LSP once the server is more mature.

These modes are evolving quickly and will improve over time. Contributions are welcome!

## Roadmap

*  **Language:**
    -  Additional persistent data structures (deque anyone?)
    -  Error reporting improvements in codegen and macro expansion
    -  Expand the Spork standard library with more utilities and data structures
    -  Testing needs a major overhaul (right now it's asserts in spork files)
*  **Tooling:**
    -  Expand `spork` CLI with testing, linting, and formatting commands
    -  Improve build process and packaging options
    -  Set up integrations with the Python packaging ecosystem and static analysis tools
    -  REPL/nREPL improvements (multi-line editing, auto completion, history search)
*  **Editor Support:**
    -  Complete and polish Emacs and Neovim modes
    -  Add VSCode support via LSP and textmate grammar extension
    -  Tree Sitter grammar for advanced syntax features
*  **Presence:**
    -  Tutorials and guides
    -  Example projects and libraries
    -  Website with documentation and resources
    
## Documentation

Check out the [docs](docs) folder for more detailed documentation on language features, the standard library, and benchmarks of the persistent data structures.


## License

[MIT License](LICENSE)
