
# Spork

[![Tests](https://github.com/spork-it/spork-lang/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/spork-it/spork-lang/actions/workflows/test.yml)

Spork is a language designed to bring structural integrity to the Python ecosystem. It combines the massive ecosystem of Python with a modern, expression-oriented Lisp syntax.

While Spork compiles to Python AST, it introduces a new engine for your data: Persistent Data Structures implemented in a C extension under the hood. These immutable collections prevent a whole class of bugs related to unintended mutation, while still allowing efficient updates via structural sharing. Spork is built for developers who want the productivity of Python with the safety and expressiveness of a modern Lisp.

## Philosophy

Spork is built on a few core opinions:

1.  **The Python Ecosystem is Great:** We want access to NumPy, PyTorch, Django, and the massive repository of PyPI packages. We do not want to rewrite the world.
2.  **Data Integrity:** Python's mutable defaults are convenient for scripts but dangerous for systems. Spork fixes this at the foundation. `[1 2 3]` isn't a Python list; it is a persistent vector. Your data is immutable by default, ensuring that state management remains predictable as complexity grows.
3.  **Unified Tooling:** Spork includes a unified toolchain to manage compilation, REPL, and testing, similar to `cargo` or `go`. It handles the bridge between Spork source and the Python environment so you don't have to configure build hooks manually.
4.  **Pragmatism:** We believe a hosted language should not fight its host. Spork compiles directly to Python AST. When you need raw performance or side effects, the escape hatch to Python's native mutability and types is always open.

## **Alpha Warning**

Spork is currently in alpha. The language, standard library, and tooling are all under active development. Breaking changes may occur between releases. We welcome feedback, issues, and contributions!

## Installation

### As a User

The recommended way to install Spork is via `pipx`, which isolates the tool environment while making the CLI globally available.

**Prerequisites:** Python 3.10+ and a C compiler (for the persistent data structures extension).

Directly from PyPi (using pipx or pip):

```bash
$ pipx install spork-lang

# or to a local environment
# pip install spork-lang 
```

To uninstall:

```bash
$ pipx uninstall spork-lang
```

### For Development

If you wish to contribute to Spork or modify the compiler:

You'll first need to clone the repository and setup the virtual environment.

```bash
$ git clone https://github.com/spork-it/spork-lang.git

$ cd spork-lang

```


```bash
# Sets up virtual environment and builds C extensions
make venv

# Run the test suite
make test
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

## Language Overview

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
(print os.name)

;; Mixing Python types (escape hatch)
(def py-list (list [1 2 3])) ; Convert Spork Vector to Python list
(.append py-list 4)          ; Mutate it in place

(print py-list) ; [1, 2, 3, 4]

(def data {:name "Spork" :version 1.0}) ; Immutable Spork Map
(print (j.dumps data)) ; '{"name": "Spork", "version": 1.0}'
```

### Pattern Matching

Spork includes structural pattern matching out of the box.

```clojure
(defn describe [x]
  (match x
    0 "zero"
    (^int n) (+ "integer: " (str n))
    [a b] (+ "vector pair: " (str a) ", " (str b))
    {:keys [name]} (+ "Hello " name)
    _ "something else"))
```

### Type Annotations

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

### Output from all of the above examples

```sh
$ spork readme.spork
[1 2 3]
[1 2 3 4]
{:name 'Spork' :version 1}
{:name 'Spork' :version 2}
#{1 2 3}
#{1 3}
posix
py-list before: [1, 2, 3]
py-list after: [1, 2, 3, 4]
Json: {"name": "Spork", "version": 1.0}
Math still works
```

## Error Reporting

Spork provides source-mapped error reporting, meaning that runtime errors point to the original `.spork` source files with accurate line numbers and code context—not the generated Python code.

### Example

Given this Spork file:

```clojure
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


## Project Management

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

```clojure
{:name "my-project"
 :version "0.1.0"
 :dependencies ["requests" "numpy>=1.20"]
 :source-paths ["src"]
 :test-paths ["tests"]
 :main "my-project.core/main"}
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

Spork is a Lisp because we believe in **Homoiconicity**: the code is represented by the language's own data structures.

1.  **Metaprogramming:** Because code is data, you can write code that writes code (Macros). This allows you to add features that look like language primitives (like the `match` or `unless` examples above) without waiting for the compiler developers to implement them.
2.  **Structural Editing:** Tools like Parinfer or Paredit make editing code structurally (moving entire blocks, expressions, or function bodies) significantly faster and less error-prone than editing line-based languages like Python.
3.  **Expression Oriented:** In Spork, almost everything is an expression that returns a value. `if`, `let`, and `do` blocks all return values, reducing the need for temporary variables and side effects.

## Under the Hood

Spork is not just a syntax skin; it is a runtime system optimized for the Python memory model.

*   **Native Persistence:** Spork's data structures are not wrappers. They are custom C extensions.
    *   **Vectors:** 32-way Bit-Partitioned Tries (similar to Clojure/Rust im-rs).
    *   **Maps & Sets:** Hash Array Mapped Tries (HAMT).
*   **Transient Internals:** The runtime utilizes mutable "Transients" internally to construct immutable results. This ensures that Spork remains performant at the boundary between mutation and persistence, giving you safety without the typical "copy-everything" penalty.
*   **Source Mapping:** We track every AST node back to its origin. When an error happens, Spork points to *your* code, not the generated Python.

## Roots

*   **Clojure:** The primary inspiration for our syntax and the sequence abstraction. We admire Clojure's discipline, but Spork is native to Python, not a JVM port.
*   **Rust/Cargo:** The inspiration for our unified tooling and project structure (`spork.it`).
*   **Python:** The host we love to live in. Spork is designed to be a good citizen of the Python ecosystem.

## Documentation
Checkout the [docs](docs) folder for more detailed documentation on language features, the standard library, and some benchmarks of the persistent data structures.

## License

[MIT License](LICENSE)
