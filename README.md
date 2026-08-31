# Spork

[![Tests](https://github.com/spork-it/spork-lang/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/spork-it/spork-lang/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/spork-lang)](https://pypi.org/project/spork-lang/)

Spork is a Lisp hosted on CPython. It compiles to Python AST, interoperates directly with Python libraries, and adds macros, expression-oriented forms, immutable persistent collections, source-mapped errors, and one project-aware CLI.

Spork is pre-1.0 and supports CPython 3.10–3.14.

## Install

On Linux, macOS, or WSL, use the reviewed installer hosted with the documentation:

```bash
curl -fsSL https://spork.sh/install | sh
```

Or install the CLI with `pipx`:

```bash
pipx install spork-lang
```

## Try it

Create `hello.spork`:

```clojure
(defn greet [name]
  (fmt "Hello, {}!" name))

(print (greet "Spork"))
```

Run it directly:

```bash
spork hello.spork
```

Create an isolated project when the program grows:

```bash
spork new hello-spork
cd hello-spork
spork sync
spork check
spork test
spork run
```

A project’s `spork.it` declares dependencies, source paths, an entry point, and a compatible `spork-lang` range. Project commands automatically use the compatible toolchain synchronized into `.venv`.

## Documentation

The canonical documentation is maintained at [spork.sh/docs](https://spork.sh/docs/):

- [Getting started](https://spork.sh/docs/getting-started/)
- [Language reference](https://spork.sh/docs/reference/language/)
- [Standard library reference](https://spork.sh/docs/reference/standard-library/)
- [Project and CLI reference](https://spork.sh/docs/reference/tooling/)
- [Editors](https://spork.sh/docs/editors/) and [examples](https://spork.sh/docs/examples/)

Release changes remain in [CHANGELOG.md](CHANGELOG.md). Repository-owned engineering notes remain under `docs/`; public documentation belongs on `spork.sh`.

## Package boundaries

Compiled Spork distributions depend on [`spork-runtime`](https://spork.sh/docs/packages/spork-runtime/) rather than the compiler. Persistent collections are supplied by the standalone [`spork-pds`](https://spork.sh/docs/packages/spork-pds/) extension.

## Development

```bash
git clone https://github.com/spork-it/spork-lang.git
cd spork-lang
make venv
make test
```

Use `make help` for development, packaging, and cleanup targets.

## License

[MIT](LICENSE)
