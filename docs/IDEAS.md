# Future Ideas


## Dynamic Module Loading

Spork currently supports importing at the module level, but there is no method to dynamically load modules at runtime. This feature would allow for more flexibility in loading modules at runtime but still allow some controll over the scope of the loaded module.

```clojure
; load a module and bind it to a symbol
(with-module [binding module-name ...] body)

; bind if found
(with-module? [binding module-name ...] body)
```

## Plugin System

Allow extending Spork itself with lifecycle hooks at various points. This would let users install new language features using pip. 

- Compiler Hooks
- Runtime Hooks
- Debugger Hooks
- New commands
- Reader macros
- Inject builtins/macros
- Custom REPL commands

For example if there was a profiler plugin, it could hit a pre-compile hook and look for any Decorations like ^profile and inject some extra expressions around the function calls. 

```sh
$ pip install spork-profiler

# or added spork.it requirements
```

Now that it's installed into your environment when spork runs it will autoload that plugin and inject profiler hooks wherever defined. This could be incorperated into the spork.it config system so projects could individually turn on and off Spork plugins and configure them.


One other part I was thinking that this could add is injecting these plugins into the spork namespace so they could be imported like `spork.profiler` and be better associated with Spork itself.
