# Command provider example

This source-only package declares one top-level `greet` command in `spork.it`.
The provider owns all arguments after that name through its
`command(context, argv)` function.

Validate and package it from this directory:

```bash
spork check
spork dist --clean
```

The wheel and source distribution contain this entry-point metadata:

```toml
[project.entry-points."spork.commands.v1"]
greet = "spork_greeter.cli:command"
```

The generated distribution requires `spork-runtime` but does not require
`spork-lang` unless compiler APIs are added as a normal project dependency.
