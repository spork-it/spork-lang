# Spork Language Reference

Spork is a Lisp dialect hosted on CPython. It compiles forms to Python AST, uses Python objects and exceptions directly, and supplies Lisp syntax, macros, and persistent collections.

For version information, related references, and shared conventions, see the [documentation index](README.md).

## Table of Contents

1. [Lexical Syntax](#1-lexical-syntax)
2. [Data Structures](#2-data-structures)
3. [Special Forms](#3-special-forms)
4. [Control Flow](#4-control-flow)
5. [Functions](#5-functions)
6. [Type Annotations](#6-type-annotations)
7. [Pattern Matching](#7-pattern-matching)
8. [Classes](#8-classes)
9. [Protocols](#9-protocols)
10. [Namespaces & Modules](#10-namespaces--modules)
11. [Macros](#11-macros)
12. [Async & Generators](#12-async--generators)
13. [Exception Handling](#13-exception-handling)
14. [Transient Data Structures](#14-transient-data-structures)
15. [Python Interop](#15-python-interop)
16. [Error Reporting](#16-error-reporting)

---

## 1. Lexical Syntax

### Identifier Normalization

Spork automatically normalizes identifiers for Python compatibility:

| Spork | Python | Notes |
|-------|--------|-------|
| `my-variable` | `my_variable` | Hyphens → underscores |
| `valid?` | `valid_q` | Question mark → `_q` |
| `math.sin` | `math.sin` | Namespace/module access |
| `foo.bar.baz` | `foo.bar.baz` | Nested namespaces |

> This can cause name collisions if both forms are used in the same scope (e.g. `my-variable` and `my_variable`).

### Reader Macros

Reader macros transform syntax during the read phase, before compilation. Spork provides both core reader macros for quoting/unquoting and extended reader macros prefixed with `#`.

#### Core Reader Macros

| Syntax | Expansion | Description |
|--------|-----------|-------------|
| `'form` | `(quote form)` | Returns unevaluated form |
| `` `form `` | `(quasiquote form)` | Template with unquoting |
| `~form` | `(unquote form)` | Evaluate inside quasiquote |
| `~@form` | `(unquote-splicing form)` | Splice list into quasiquote |
| `^expr` | Decoration metadata | Annotate or decorate the form that follows; its meaning depends on context |
| `;comment` | (ignored) | Line comment |

#### Extended Reader Macros

| Syntax | Description |
|--------|-------------|
| `#(...)` | Anonymous function using `%`/`%1` for its first argument, `%2`-`%N` for later arguments, and `%&` for rest arguments |
| `#[start stop step]` | Slice literal (use `_` for an omitted bound) |
| `#_form` | Discard next form (parsed but not compiled) |
| `#f"..."` | F-string with `{expr}` interpolation |
| `#p"..."` | Path literal (`pathlib.Path`) |
| `#r"..."` | Regex literal (compile-time validated) |
| `#uuid"..."` | UUID literal (compile-time validated) |
| `#inst"..."` | ISO-8601 datetime literal |
| `#=form` | Read-time evaluation |

`#(...)` is documented below under [Anonymous Functions](#anonymous-functions). See [Reader Macros](STDLIB.md#reader-macros) in the Standard Library Reference for detailed examples of the remaining extended forms.

### Literals

```clojure
; Numbers
42          ; integer
3.14        ; float
-17         ; negative

; Strings
"hello"     ; double-quoted string
"line1\nline2"  ; escape sequences

; Keywords evaluate to themselves and may contain hyphens
:name
:my-key

; Calling a keyword looks it up in a map; a second argument is the default
(:name {:name "Alice"})         ; => "Alice"
(:missing {:a 1} "default")     ; => "default"

; Booleans and nil map directly to Python values
true        ; Python True
false       ; Python False
nil         ; Python None
```

---

## 2. Data Structures

Spork uses **persistent (immutable) data structures** from the released `spork-pds` C extension dependency.

The core types are:
- `Vector` - Persistent vector (32-way bit-partitioned trie)
- `Map` - Persistent hash map (HAMT)
- `Set` - Persistent hash set (HAMT)
- `DoubleVector` - Type-specialized vector for floats (float64)
- `IntVector` - Type-specialized vector for integers (int64)
- `SortedVector` - Persistent sorted vector (Red-Black tree)
- `Cons` - Linked list cells

### Vectors

Square brackets create a persistent `Vector`:

```clojure
[1 2 3]
```

See [`Vector`](STDLIB.md#vector) for constructors and collection operations. Type annotations can select `DoubleVector` or `IntVector` storage, as described under [Persistent Data Structure Types](#persistent-data-structure-types).

### Maps

Curly braces containing alternating keys and values create a persistent `Map`:

```clojure
{:name "Alice" :age 30}
```

See [`Map`](STDLIB.md#map) for lookup and update operations.

### Sets

`#{...}` creates a persistent `Set`:

```clojure
#{1 2 3}
```

See [`Set`](STDLIB.md#set) for membership, update, and set operations.

### Lists (Cons Cells)

Quoting a parenthesized form produces a `Cons` list instead of evaluating it as a call:

```clojure
'(1 2 3)
```

See [`Cons`](STDLIB.md#cons-linked-list) for construction and sequence operations.

### SortedVector

Persistent sorted vectors maintain elements in sorted order using a red-black tree. Indexed lookup, insertion, removal, membership, and rank queries are O(log n); full iteration is O(n). Duplicates are retained.

`sorted-vec` is the idiomatic Spork spelling. It resolves to the Python binding `sorted_vec` through identifier normalization, which is also why the value's representation uses an underscore.

The optional `:key` function derives sort keys, and `:reverse true` reverses the configured ordering:

```clojure
(def words-longest-first
  (sorted-vec ["pear" "fig" "banana"] *{:key len :reverse true}))
(vec words-longest-first) ; => ["banana" "pear" "fig"]
```

See [`SortedVector`](STDLIB.md#sortedvector) in the Standard Library Reference for construction, lookup, rank, update, and transient APIs.

### Sequence Abstraction

Persistent collections participate in Spork's sequence operations. See [Sequence Operations](STDLIB.md#sequence-operations) for `seq`, `first`, `rest`, `into`, and related functions.

---

## 3. Special Forms

### Definition

```clojure
; Define a value
(def x 42)

; Define with destructuring
(def [a b] [1 2])
(def {:keys [name age]} person)

; Reassign an existing binding or object attribute
(set! x 100)
(set! obj.attr value)
```

### Test Declarations

`deftest` declares a named, parameterless test at module top level. Its body is compiled and registered but only invoked by `spork test`, so inline tests may live beside regular definitions without running during normal program execution.

```clojure
(deftest addition-works
  "An optional docstring may precede the body."
  (assert (= (+ 2 3) 5)))

(deftest ^async async-operation-works
  (def result (await (fetch-result)))
  (assert (= result 42)))
```

A test passes when its body returns normally and fails when it raises an uncaught exception. Return values are ignored. `^async` is the only supported test metadata. Names must be valid unqualified symbols, duplicate normalized names in one file are invalid, and `deftest` cannot be nested in a function or expression. Discovery is documented under [Testing](PROJECTS.md#testing).

### Let Bindings

```clojure
; Basic let
(let [x 1
      y 2]
  (+ x y))  ; => 3

; Sequential binding (later bindings see earlier ones)
(let [x 1
      y (+ x 1)]
  y)  ; => 2

; Destructuring in let
(let [[a b] [1 2]
      {:keys [name]} {:name "Alice"}]
  (fmt "{}: {}, {}" name a b))  ; => "Alice: 1, 2"
```

### Do Blocks

```clojure
; Execute multiple forms, return last
(do
  (print "side effect")
  (+ 1 2))  ; => 3
```

---

## 4. Control Flow

### If

```clojure
(if condition
  then-expr
  else-expr)

; else is optional (defaults to nil)
(if (> x 0) "positive")
```

### Cond (Multi-way Conditional)

`cond` takes alternating test and result forms and returns the result for the first truthy test. The conventional final test `:else` is a truthy keyword and acts as a fallback.

```clojure
(cond
  (< x 0) "negative"
  (> x 0) "positive"
  :else "zero")
```

### When / Unless

```clojure
; Execute body only when true
(when condition
  (do-something)
  (do-more))

; Execute body only when false
(unless condition
  (do-something))
```

### While Loop

```clojure
(while (< i 10)
  (print i)
  (set! i (inc i)))
```

### For Expression

`for` eagerly evaluates its body once for each input and returns a persistent vector of the body results. It never returns a lazy iterator. `nil` results are retained, and binding patterns support destructuring.

```clojure
(def squares
  (for [x (range 10)] (* x x)))
; => [0 1 4 9 16 25 36 49 64 81]

; Works with any expression, including conditionals
(for [x (range 10)]
  (if (even? x) (* x 2) nil))
; => [0 nil 4 nil 8 nil 12 nil 16 nil]

; Supports destructuring
(def pairs [[1 2] [3 4] [5 6]])
(for [[a b] pairs] (+ a b))
; => [3 7 11]

; Earlier body forms run for effects; the final value is retained
(def recorded (list))
(for [x (range 5)]
  (recorded.append x)
  (let [sq (* x x)] (+ sq 1)))
; => [1 2 5 10 17]
```

Because `for` is an ordinary expression form, it composes directly in calls, conditionals, `let`, markup, and function tail positions. The former `[for ...]` vector-comprehension syntax is no longer supported.

### Effect-only Iteration

Use `doseq` when body results are intentionally discarded. It evaluates eagerly and returns `nil` without constructing a result vector.

```clojure
(doseq [x [1 2 3]]
  (print x))
; prints 1, 2, and 3; returns nil
```

### Sorted For Expression

`sorted-for` eagerly returns a `SortedVector`. It uses the same binding and body positions as `for`, followed by optional `:key` and `:reverse` values.

```clojure
(sorted-for [x (range 10)] (* x x))
; => sorted_vec(0, 1, 4, 9, 16, 25, 36, 49, 64, 81)

; With :key function for custom sorting
(sorted-for [s ["banana" "apple" "fig"]] s :key len)
; => sorted_vec("fig", "apple", "banana")

; With :reverse for descending order
(sorted-for [x [3 1 4 1 5]] x :reverse true)
; => sorted_vec(5, 4, 3, 1, 1)

; A keyword such as :score is a lookup function and can be the sort key
(def score-items
  [{:name "alpha" :score 8} {:name "beta" :score 13}])
(def ranked-items
  (sorted-for [item score-items]
    {:name (:name item) :score (:score item)}
    :key :score :reverse true))
(isinstance ranked-items SortedVector) ; => true
(vec ranked-items)
; => [{:name "beta" :score 13} {:name "alpha" :score 8}]
```

### Loop / Recur (Tail-Call Optimization)

```clojure
; `loop` supplies initial bindings; `recur` replaces them for the next iteration
(loop [i 0
       acc 0]
  (if (>= i 10)
    acc
    (recur (inc i) (+ acc i))))  ; => 45

; `recur` must be in tail position
```

---

## 5. Functions

### Anonymous Functions

```clojure
(fn [x] (* x x))

(fn [x y]
  (let [sum (+ x y)]
    (* sum sum)))
```

#### Shorthand: `#(...)`

The `#(...)` reader macro creates an anonymous function and infers its parameters from placeholders in the body. These placeholders are special only inside `#(...)`:

| Placeholder | Meaning |
|-------------|---------|
| `%` or `%1` | First positional argument |
| `%2`, `%3`, ... | Second, third, and subsequent positional arguments |
| `%&` | All remaining arguments |

For example, `#(+ % 1)` is shorthand for `(fn [x] (+ x 1))`:

```clojure
; `%` receives the first argument
(def increment #(+ % 1))
(increment 2)                         ; => 3

; Numbered placeholders receive arguments by position
(def add #(+ %1 %2))
(add 3 4)                             ; => 7

; `%&` collects a variable number of arguments
(def sum-all #(apply + %&))
(sum-all 1 2 3 4 5)                  ; => 15
```

### Named Functions

`defn` binds a function name. A string immediately after the parameter vector becomes the function's Python docstring.

```clojure
(defn square [x]
  (* x x))

; With docstring
(defn greet [name]
  "Returns a greeting string."
  (fmt "Hello, {}!" name))
```

### Multi-Arity Functions

Instead of one parameter vector, a function may contain several parenthesized clauses. Each clause starts with its own parameter vector, and calls dispatch by argument count.

```clojure
(defn greet
  ([name]
   (greet name "Hello"))
  ([name greeting]
   (fmt "{}, {}!" greeting name)))

(greet "Alice")           ; => "Hello, Alice!"
(greet "Alice" "Hi")      ; => "Hi, Alice!"
```

### Variadic Functions

Within a parameter vector, `& name` collects the remaining positional arguments under `name`.

```clojure
; Rest arguments
(defn sum [& nums]
  (reduce + 0 nums))

(sum 1 2 3 4)  ; => 10

; Mixed positional and rest
(defn log [level & msgs]
  (print level ":" (.join "" (map str msgs))))
```

### Keyword Arguments

In a parameter vector, `*` separates positional parameters from keyword-only parameters. A bare name after `*` is required; `(name default)` supplies a default. `** name` instead collects otherwise-unbound keyword arguments into a persistent map.

At a call site, `*{:key value}` converts entries to Python keyword arguments. The inline spelling `* :key value` is equivalent. A map variable can be splatted as `*{options}`; map variables and literal entries can also be combined inside the braces. More than one splat may follow the positional arguments.

```clojure
; `age` and `email` are required keyword-only parameters
(defn create-user [name * age email]
  {:name name :age age :email email})

(create-user "Alice" *{:age 30 :email "alice@example.com"})
; => {:name "Alice" :age 30 :email "alice@example.com"}

; A two-item list declares a keyword-only parameter and its default
(defn config [host * (port 8080) (debug false)]
  {:host host :port port :debug debug})

(config "localhost")
; => {:host "localhost" :port 8080 :debug false}
(config "example.com" *{:port 3000})
; => {:host "example.com" :port 3000 :debug false}

; Inline keyword arguments follow a bare `*`
(config "example.com" * :port 3000 :debug true)
; => {:host "example.com" :port 3000 :debug true}

; `*{options}` splats every entry in a map variable
(def options {:port 4000 :debug true})
(config "example.com" *{options})
; => {:host "example.com" :port 4000 :debug true}

; Literal entries and map variables may share one splat
(def debug-options {:debug true})
(config "example.com" *{:port 5000 debug-options})
; => {:host "example.com" :port 5000 :debug true}

; `** opts` captures keyword arguments not bound to named parameters
(defn flexible [required ** opts]
  {:required required :opts opts})

(flexible "value" *{:a 1 :b 2})
; => {:required "value" :opts {:a 1 :b 2}}

; The same call syntax works with Python functions and methods
(def template "{name} is {age}")
(template.format *{:name "Alice" :age 30}) ; => "Alice is 30"
```

### Destructuring in Parameters

A vector parameter pattern binds values by position. A map pattern using `{:keys [name age]}` creates local bindings from the map's `:name` and `:age` entries.

```clojure
(defn process-point [[x y]]
  (+ x y))

(defn greet-person [{:keys [name age]}]
  (fmt "{} is {} years old" name age))
```

---

## 6. Type Annotations

Spork supports Python-compatible type annotations using the `^type` prefix syntax. Place the annotation immediately before a variable or parameter; for a return type, place it between `defn` and the function name. Type annotations compile to standard Python annotations, enabling static analysis, IDE support, and runtime introspection.

### Variable Annotations

```clojure
; Simple typed variables
(def ^int max-retries 3)
(def ^str name "Alice")
(def ^float pi 3.14159)
(def ^bool enabled true)

; Compiles to:
; max_retries: int = 3
; name: str = "Alice"
```

### Function Parameter Annotations

```clojure
; Annotated parameters
(defn greet [^str name]
  (fmt "Hello, {}" name))

; Multiple annotations
(defn add [^int x ^int y]
  (+ x y))

; Compiles to:
; def add(x: int, y: int):
;     return x + y

; Mixed annotated and unannotated
(defn format-message [^str prefix message]
  (fmt "{}: {}" prefix message))
```

### Return Type Annotations

```clojure
; Return type before function name
(defn ^int square [^int x]
  (* x x))

; Compiles to:
; def square(x: int) -> int:
;     return x * x

(defn ^str greet [^str name]
  (fmt "Hello, {}!" name))

```

### Generic Types

Common Python and `typing` generic types are available without imports. Annotations are emitted as Python annotations; they do not enforce values at runtime.

```clojure
; Python collection annotations paired with Python collection values
(def ^(List int) numbers (list [1 2 3]))
(def ^(Dict str int) ages (dict [["alice" 30]]))
(def ^(Set str) tags (set ["a" "b"]))
(isinstance numbers list) ; => true
(isinstance ages dict)    ; => true
(isinstance tags set)     ; => true

; Optional (for nullable values)
(defn ^(Optional str) find-name [^int id]
  (if (valid? id)
    (lookup id)
    nil))

; Union types
(def ^(Union int str) value 42)

; Compact Callable syntax: parameter types followed by the return type
(defn apply-fn [^(Callable int int) f ^int x]
  (f x))

; Equivalent syntax with an explicit parameter vector
(defn apply-fn2 [^(Callable [[int] int]) f ^int x]
  (f x))

; Callable with arbitrary additional arguments
(defn ^int apply-update [^(Callable [[...] int]) f ^int value]
  (f value))
```

User-defined generic classes import `Generic` and `TypeVar` from Python's `typing` module. A parenthesized `Generic` base emits subscription syntax rather than a function call, and capitalized generic forms are valid return annotations:

```clojure
(ns example.box
  (:import [typing :refer [Generic TypeVar]]))

(def T (TypeVar "T"))

(defclass Box [(Generic T)]
  (defn __init__ [self ^T value]
    (set! self.value value)))

(defn ^(Box T) box [^T value]
  (Box value))
```

### Available Type Constructors

The following types are available without importing `typing`:

| Type | Description |
|------|-------------|
| `Any` | Any type |
| `Optional` | Value or None |
| `Union` | One of several types |
| `List` | Python list type |
| `Dict` | Python dictionary type |
| `Set` | Python set type |
| `Tuple` | Python tuple type |
| `Callable` | Function type |
| `Iterable` | Iterable type |
| `Iterator` | Iterator type |
| `Sequence` | Sequence protocol |
| `Mapping` | Mapping protocol |
| `Generator` | Generator type |
| `Type` | Type of a class |

### Multi-Arity with Types

Type annotations work with multi-arity functions:

```clojure
(defn ^int add
  ([^int x] x)
  ([^int x ^int y] (+ x y))
  ([^int x ^int y ^int z] (+ x y z)))

; Compiles to function with return type annotation
; and typed local variable bindings inside each arity
```

### Persistent Data Structure Types

Spork's persistent data structure types support generic subscripting for type annotations:

```clojure
(def ^(Vector int) nums [1 2 3])
(def ^(Map str int) scores {"alice" 100})
(def ^(Cons int) items (cons 1 (cons 2 nil)))

; For annotated vector literals, these two forms select specialized storage
(def ^(Vector float) floats [1.0 2.0 3.0])
(def ^(Vector int) ints [1 2 3])
(isinstance floats DoubleVector) ; => true
(isinstance ints IntVector)      ; => true
```

| Type | Description |
|------|-------------|
| `Vector` | Persistent vector (generic) |
| `Map` | Persistent hash map |
| `DoubleVector` | Vector of float64 (with NumPy buffer protocol) |
| `IntVector` | Vector of int64 (with read-only buffer protocol) |
| `SortedVector` | Persistent ordered collection |
| `Cons` | Linked list cell |

### Runtime Introspection

Annotations use Python's postponed evaluation so generic forward references are safe on every supported Python version. Use `typing.get_type_hints` when resolved runtime objects are needed; raw `__annotations__` values may be strings:

```clojure
(ns annotation-example
  (:import [typing :refer [get_type_hints]]))

(defn ^int add [^int x ^int y] (+ x y))
(def hints (get_type_hints add))

(= (get hints "x") int)      ; => true
(= (get hints "y") int)      ; => true
(= (get hints "return") int) ; => true
```

---

## 7. Pattern Matching

### Match Expression

`match` evaluates its target once, then tests alternating pattern and result forms in source order. The first match wins; if no pattern matches, it raises `MatchError`. Use `_` as an explicit fallback.

<!-- verify-docs: skip=grammar-template -->
```clojure
(match value
  pattern1 result1
  pattern2 result2
  _ default-result)
```

### Pattern Types

```clojure
; Literal patterns compare by value; `_` matches anything
(match x
  1 "one"
  2 "two"
  _ "other")

; `^type` checks the value's type, then binds the following name
(match x
  (^int n) (fmt "integer: {}" n)
  (^str s) (fmt "string: {}" s)
  _ "unknown")

; Vector patterns bind by position; `&` binds the unmatched tail
(match coll
  [] "empty"
  [x] (fmt "one: {}" x)
  [x y] (fmt "two: {}, {}" x y)
  [x & rest] (fmt "many, first: {}" x))

; Map patterns require literal entries and bind symbols to other values
(match m
  {:type :circle :radius r} (* 3.14 r r)
  {:type :square :side s} (* s s)
  _ 0)

; `:when` accepts a match only when its guard is truthy
(match x
  (n :when (> n 0)) "positive"
  (n :when (< n 0)) "negative"
  _ "zero")
```

### Pattern-Dispatched Functions

Multi-arity `defn` clauses may use destructuring patterns and a `:when` guard. Clauses with the same arity are tested in source order, and the first matching clause runs. If no arity, pattern, and guard match, the function raises `MatchError`.

```clojure
(defn area
  ([{:keys [type radius]} :when (= type :circle)]
   (* 3.14 radius radius))
  ([{:keys [type width height]} :when (= type :rectangle)]
   (* width height))
  ([{:keys [type side]} :when (= type :square)]
   (* side side)))
```

---

## 8. Classes

### Basic Class Definition

`defclass` takes a class name, an optional vector of base classes, and a body of methods, fields, or class-level definitions. An empty base vector (`[]`) declares no explicit base class.

```clojure
(defclass Point []
  (defn __init__ [self x y]
    (set! self.x x)
    (set! self.y y))

  (defn distance [self other]
    (let [dx (- other.x self.x)
          dy (- other.y self.y)]
      (** (+ (* dx dx) (* dy dy)) 0.5))))
```

### Inheritance

```clojure
(defclass ColorPoint [Point]
  (defn __init__ [self x y color]
    (.__init__ (super) x y)  ; (super).__init__(x, y)
    (set! self.color color)))
```

### Decorators

Decorator metadata appears after `defn` or `defclass` and before the function or class name. External Python decorators must be imported; Python built-ins such as `staticmethod` and `classmethod` are already available.

```clojure
(ns example.classes
  (:import [dataclasses :refer [dataclass]]))

(defclass ^dataclass Person []
  (field name str)
  (field age int 0))

(defclass Counter []
  (defn ^staticmethod create []
    (Counter))

  (defn ^classmethod from-value [cls value]
    (let [c (cls)]
      (set! c.value value)
      c)))
```

### Class Fields

Inside any class, `(field name type)` emits an annotated field without a default, while `(field name type default)` includes a default. This is especially useful for dataclasses. `field` is a Spork class form; it does not need to be imported from `dataclasses`.

```clojure
(ns example.config
  (:import [dataclasses :refer [dataclass]]))

(defclass ^dataclass Config []
  (field host str "localhost")
  (field port int 8080)
  (field debug bool false))
```

---

## 9. Protocols

Protocols provide polymorphic dispatch similar to Clojure protocols or type classes.

### Defining Protocols

```clojure
(defprotocol IShape
  "Protocol for geometric shapes."
  (area [self])
  (perimeter [self]))

; Structural protocol (duck typing based on methods)
(defprotocol ^structural ICloseable
  (close [self]))
```

### Extending Types

```clojure
; Extend a type to implement a protocol
(extend-type Circle
  IShape
  (area [self] (* 3.14 self.radius self.radius))
  (perimeter [self] (* 2 3.14 self.radius)))

; Extend multiple types for one protocol
(extend-protocol IShape
  Rectangle
  (area [self] (* self.width self.height))
  (perimeter [self] (* 2 (+ self.width self.height)))

  Square
  (area [self] (* self.side self.side))
  (perimeter [self] (* 4 self.side)))
```

### Using Protocols

```clojure
; Call protocol methods
(area my-circle)
(perimeter my-rectangle)

; Explicit extensions also register the type with the protocol ABC
(isinstance my-object IShape)
```

---

## 10. Namespaces & Modules

### Namespace Declaration

```clojure
(ns my.app.core
  (:require
    [my.utils :refer [helper-fn]]
    [external.lib :refer :all])
  (:import
    [spork.pds :as pds]
    [array :as arr]
    [os.path :as osp]
    [collections :refer [defaultdict Counter]]
    [math :refer [sin cos]]))
```

### Require Options (for Spork namespaces)

Use `:require` only for Spork namespaces. It loads compile-time macros as well as runtime definitions. Python modules are rejected by `:require`; load them with `:import`.

<!-- verify-docs: skip=namespace-fragments -->
```clojure
; Alias the namespace; this makes short.foo available
[some.long.module :as short]

; Specific imports into current namespace
[module :refer [fn1 fn2]]

; Import all public symbols
[module :refer :all]
```

Attempting to require a Python module is a compile-time error:

<!-- verify-docs: expect-error=SyntaxError -->
```clojure
(ns invalid.require
  (:require [json :as j]))
```

### Import Options (for Python modules)

Use `:import` for Python modules. This makes the dependency's origin explicit and avoids compile-time macro loading. Python modules cannot be loaded with `:require`.

```clojure
; Inside (ns ...) use (:import ...)
(ns my.app
  (:import
    [os]                              ; import os
    [json :as j]                      ; import json as j
    [pathlib :refer [Path]]           ; from pathlib import Path
    [collections :refer [defaultdict Counter]]  ; from collections import ...
    [math :refer [sin :as s cos]]     ; from math import sin as s, cos
    [os.path :as osp]))               ; import os.path as osp

; Access with dot notation
(print (os.getcwd))
(print (j.dumps (dict [["a" 1]])))
(print (s 0.5))
```

### Importing Macros

Macros use the same `:require` syntax as regular definitions; the compiler determines which referred symbols are macros. There is no separate macro-import form.

```clojure
(ns my.app
  (:require [my.macros :refer [my-macro]]
            [other.lib :as lib :refer [foo]]))

; A referred macro is called without qualification
(my-macro some args)

; An alias provides qualified access
(lib.some-macro arg)

; :refer :all imports all public macros and definitions
(ns another.app
  (:require [my.macros :refer :all]))
```

### Dotted Access

Dotted symbols are the canonical spelling for qualified namespace calls, Python module calls, class methods, and methods on named objects. Unlike Clojure, Spork uses dots rather than slashes for qualified names.

```clojure
(ns my.app
  (:require [std.string :as str])
  (:import [math :as m]
           [array :as arr]))

(str.join ", " ["a" "b" "c"])  ; => "a, b, c"
(m.sqrt 16)                     ; => 4.0
(arr.array "i" [1 2 3])         ; Python standard-library array

(def values (list [3 1 2]))
(values.sort)
(vec values)                       ; => [1 2 3]
```

A dotted symbol compiles as one Python attribute chain, so `client.session.get` works for nested attributes as long as the chain begins with a symbol. Qualified macros must also use this spelling, such as `(lib.some-macro arg)`; leading-dot method syntax is a runtime call and does not macro-expand.

---

## 11. Macros

### Defining Macros

```clojure
(defmacro unless [test & body]
  `(if ~test nil (do ~@body)))
```

### Quasiquoting

```clojure
; ` creates a template
; ~ inserts an evaluated value
; ~@ inserts each value from a sequence into the surrounding form

(defmacro debug [expr]
  `(let [val# ~expr]
     (print '~expr "=" val#)
     val#))
```

### Auto-gensym

Inside a quasiquoted template, appending `#` to a symbol creates a unique generated symbol. Repeated uses of the same suffixed name within that template resolve to the same generated symbol, preventing accidental capture of a caller's bindings:

```clojure
(defmacro swap! [a b]
  `(let [tmp# ~a]
     (set! ~a ~b)
     (set! ~b tmp#)))
```

---

## 12. Async & Generators

### Async Functions

Place the `^async` compiler flag before the function name. `await` and `async-for` may only appear inside an async function. Like `for`, `async-for` eagerly returns a persistent vector after consuming the asynchronous iterable; it does not return a lazy async iterator.

```clojure
(defn ^async fetch-data [url]
  (let [response (await (http.get url))]
    (await (response.json))))

; Eagerly transform an asynchronous iterable
(defn ^async load-items []
  (async-for [item (async-iterator)]
    (await (transform item))))
```

### Generators

Place `^generator` before the function name when its body uses `yield` or `yield-from`.

```clojure
(defn ^generator count-up [start]
  (loop [n start]
    (yield n)
    (recur (inc n))))

; Yield from (delegation)
(defn ^generator chain [& iterables]
  (doseq [it iterables]
    (yield-from it)))
```

---

## 13. Exception Handling

### Try / Catch / Finally

```clojure
(try
  (risky-operation)
  (catch ValueError e
    (print "Value error:" e)
    :error)
  (catch Exception e
    (print "General error:" e)
    :error)
  (finally
    (cleanup)))
```

### Throw

<!-- verify-docs: expect-error=ValueError -->
```clojure
(throw (ValueError "invalid input"))
```

### Assert

The prelude `assert` macro raises `AssertionError` when its test is falsy. See [`assert`](STDLIB.md#assert) in the Standard Library Reference for usage.

---

## 14. Transient Data Structures

Transients are mutable builders for `Vector`, `Map`, `Set`, `SortedVector`, `DoubleVector`, and `IntVector`. Operations ending in `!` mutate the builder; `persistent!` returns an immutable value and invalidates the transient. The original persistent collection is never changed.

`with-mutable` scopes that lifecycle and returns the persistent result automatically:

```clojure
(def original [1 2 3])
(def updated
  (with-mutable [builder original]
    (conj! builder 4)))

original ; => [1 2 3]
updated  ; => [1 2 3 4]
```

The available mutation operations and Python-compatible mutable APIs vary by transient type. See [Transient Operations](STDLIB.md#transient-operations) in the Standard Library Reference for the complete API and interoperability examples.

---

## 15. Python Interop

### Calling Python with Keyword Arguments

The [function call syntax described above](#keyword-arguments) also applies to Python callables. Inside a splat, Spork keyword keys become Python keyword names. Outside a splat, a keyword remains a Spork `Keyword` value.

```clojure
; Keyword keys in a splat become Python string keys
(dict *{:name "Alice" :age 30})
; => {"name" "Alice" "age" 30}

; Python methods accept the same syntax
(def template "{name} is {age}")
(template.format *{:name "Bob" :age 25})
; => "Bob is 25"

; Multiple splats may follow the positional arguments
(dict *{:a 1} *{:b 2 :c 3})
; => {"a" 1 "b" 2 "c" 3}

; Without `*`, :name is a value and can be called as a map lookup
(:name {:name "Alice"})            ; => "Alice"
(dict * :name "Alice")             ; => {"name" "Alice"}
```

### Attribute and Method Access

Prefer dotted symbols when the receiver has a name:

```clojure
obj.attr                    ; obj.attr
(obj.method arg1 arg2)      ; obj.method(arg1, arg2)
(set! obj.attr val)         ; obj.attr = val
```

A dotted symbol must begin with a symbol. The leading-dot form remains supported for compatibility and is useful when the receiver is a literal or computed expression:

```clojure
(.upper "hello")                ; "hello".upper()
(.method (DocObject) arg1)      ; DocObject().method(arg1)
```

`call` is an explicit receiver-first equivalent. The general dot form accesses attributes and subscripts; because it produces an ordinary value, it can also be placed in call position:

```clojure
(call obj method arg1)           ; obj.method(arg1)
(. obj attr)                     ; obj.attr
((. (DocObject) method) arg1)    ; DocObject().method(arg1)
(. coll 0)                       ; coll[0]
(. coll (+ index 1))             ; coll[index + 1]
(. coll (slice start stop))      ; coll[start:stop]
```

In the general dot form, a symbol after the object names an attribute; an integer or expression is a subscript. Use `get` for ordinary dynamic indexing. All method-call spellings remain supported, but documentation and new code should use `(obj.method args...)` whenever the receiver can begin a dotted symbol.

### Python Builtins

Common Python built-in functions are available:

```clojure
(print "hello")
(len [1 2 3])                    ; => 3
(= (type 42) int)                ; => true
(isinstance 42 int)              ; => true
(str 42)                         ; => "42"
(int "42")                       ; => 42
(= (type (list [1 2 3])) list)  ; => true
(= (type (dict [["name" "Alice"]])) dict) ; => true
```

### Operators

Operators are written as the first item in a parenthesized call. Thus `(^ a b)` is bitwise XOR, `(~ x)` is bitwise NOT, and `(& a b)` is bitwise AND. These are distinct from prefix `^type` metadata, `~form` unquote syntax, and `& rest` in a parameter vector.

```clojure
; Comparison (chainable)
(= a b c)             ; a == b == c
(!= a b)              ; a != b
(not= a b)            ; a != b (Lisp-style alias)
(< 1 5 10)            ; 1 < 5 < 10
(<= a b c)            ; a <= b <= c
(> a b)               ; a > b
(>= a b)              ; a >= b

; Logical
(and a b c)
(or a b c)
(not x)

; Bitwise (symbol and verbose forms)
(| a b)               ; bitwise or  (also: bit-or)
(& a b)               ; bitwise and (also: bit-and)
(^ a b)               ; bitwise xor (also: bit-xor)
(~ x)                 ; bitwise not (also: bit-not)
(<< x n)              ; left shift  (also: bit-shift-left)
(>> x n)              ; right shift (also: bit-shift-right)

; Membership
(in item coll)        ; item in coll
```

### Context Managers (with)

The binding vector normally contains alternating binding and context-manager expressions. It may contain several pairs, a destructuring pattern, or a context-manager call with no preceding binding.

```clojure
; Basic with
(with [f (open "file.txt" "r")]
  (print (f.read)))

; Multiple bindings
(with [f1 (open "in.txt")
       f2 (open "out.txt" "w")]
  (f2.write (f1.read)))

; Without binding (for side effects)
(with [(some-context)]
  (do-work))

; Destructuring
(with [[reader writer] (create-pipe)]
  (process reader writer))
```

### Slice Syntax

The `#[start stop step]` reader macro creates a Python slice; `_` marks an omitted bound. Pass the resulting slice to `get` or use a `slice` expression in the general dot form:

```clojure
(get coll #[2 8 2])
(. coll (slice 2 8 2))
```

See [Reader Macros](STDLIB.md#reader-macros) in the Standard Library Reference for complete slice patterns and examples.

---

## 16. Error Reporting

Spork provides **source-mapped error reporting**. When runtime errors occur, tracebacks point to the original `.spork` source files with accurate line numbers and code context—not the generated Python code.

### Traceback Example

Given this Spork code:

<!-- verify-docs: expect-error=ZeroDivisionError -->
```clojure
;; example.spork
(defn divide [a b]
  (/ a b))

(defn nested-call [x]
  (let [y (divide x 0)]
    (+ y 10)))

(defn deep-stack []
  (nested-call 42))

(deep-stack)
```

Running it produces a traceback whose source-mapped portion is:

```
Error: division by zero
Traceback (most recent call last):
  File "example.spork", line 12, in <module>
    (deep-stack)
    ~~~~~^~~~~~~
  File "example.spork", line 10, in deep_stack
    (nested-call 42))
    ^^^^^^^^^^^^^^^^
  File "example.spork", line 6, in nested_call
    (let [y (divide x 0)]
            ^^^^^^^^^^^^
  File "example.spork", line 3, in divide
    (/ a b))
    ^^^^^^^
ZeroDivisionError: division by zero
```

### Error Types

Spork surfaces Python's standard exception types with Spork source locations:

| Error Type | Example Cause |
|------------|---------------|
| `ZeroDivisionError` | `(/ x 0)` |
| `TypeError` | `(+ 1 "string")` — type mismatch in operations |
| `NameError` | Using an undefined variable like `undefined-var` |
| `AttributeError` | `(. nil some-method)` — attribute access on nil |
| `IndexError` | `(nth [1 2] 10)` — index out of bounds |
| `AssertionError` | `(assert false "message")` |
| `SyntaxError` | Missing closing parenthesis, unterminated string |
| `KeyError` | Missing required key in map destructuring |

### Undefined Variable Errors

<!-- verify-docs: expect-error=NameError -->
```clojure
(defn calculate [x]
  (+ x undefined-var))

(calculate 10)
```

Relevant traceback excerpt:

```
Error: name 'undefined_var' is not defined
  File "example.spork", line 2, in calculate
    (+ x undefined-var))
         ~~~~~~~~~^~~~
NameError: name 'undefined_var' is not defined
```

Note that the error message shows the normalized Python name (`undefined_var`) but the source location points to the original Spork code.

### Type Errors

<!-- verify-docs: expect-error=TypeError -->
```clojure
(defn add-numbers [a b]
  (+ a b))

(add-numbers 10 "oops")
```

Relevant traceback excerpt:

```
Error: unsupported operand type(s) for +: 'int' and 'str'
  File "example.spork", line 2, in add_numbers
    (+ a b))
    ^^^^^^^
TypeError: unsupported operand type(s) for +: 'int' and 'str'
```

### Assertion Errors

<!-- verify-docs: expect-error=AssertionError -->
```clojure
(defn validate-positive [n]
  (assert (> n 0) "Expected positive number")
  n)

(validate-positive -5)
```

Relevant traceback excerpt:

```
Error: Expected positive number
  File "example.spork", line 2, in validate_positive
    (assert (> n 0) "Expected positive number")
AssertionError: Expected positive number
```

### Syntax Errors

Syntax errors are caught at compile time and include location information:

<!-- verify-docs: expect-error=SyntaxError -->
```clojure
(defn broken [x]
  (let [y 10]
    (+ x y)
; Missing closing parens
```

Relevant error:

```
SyntaxError: unterminated list at line 2, expected )
```

### How Source Mapping Works

Spork compiles to Python AST with source location information preserved:

1. The Spork reader tracks line and column numbers for every form
2. The compiler attaches these locations to generated AST nodes via `lineno` and `col_offset`
3. The compiled code object references the original `.spork` filename
4. Python's traceback mechanism uses this information to display the original source

This means you can debug Spork code naturally using standard Python tools (debuggers, profilers, exception handlers) without needing to understand the generated Python.

---

## Appendix: Expression vs Statement Contexts

Python distinguishes statements (which produce no value) from expressions. Spork determines the context from a form's position:

- A top-level form or a non-final form in a body has its value discarded.
- A binding initializer, function argument, conditional branch, or value-returning final form must produce a value.
- `do` may appear in either context; when its value is needed, it returns its final form.

When a statement-oriented construct such as `let`, `try`, or `with` must produce a value, the compiler moves it into a generated helper function and calls that function immediately. For example:

```clojure
(def result (let [x 1] (+ x 2)))
```

compiles roughly to:

```python
def _wrapper():
    x = 1
    return x + 2

result = _wrapper()
```

---

## Appendix: Feature Comparison

| Feature | Python | Spork | Implementation |
|---------|--------|-------|----------------|
| Tail Recursion | No built-in optimization | Explicit `loop`/`recur` | Compiles to a loop |
| Data Structures | Mutable and immutable built-ins | Persistent collection literals | `spork-pds` tries and trees |
| Conditionals | `if`/`elif`/`else`, `match` | `if`, `cond`, `match` | Compiles to Python control flow |
| Metaprogramming | Decorators, metaclasses | Macros and decorators | AST transformation |
| Variable Scope | Function, global, and `nonlocal` | Python scopes plus lexical `let` bindings | Scoped helper functions when needed |
| Function Arity | Defaults and variadic parameters | Defaults, variadic parameters, and multi-arity clauses | Python signatures or runtime dispatch |
| Destructuring | Sequence unpacking and patterns | Nested vector and map patterns | Recursive assignment or pattern tests |
| Imports | `import`/`from` | `ns` with `:require` and `:import` | Macro discovery for required Spork namespaces |
| Protocols | ABCs and duck typing | `defprotocol` | Runtime dispatch table |
| Batch Mutation | Mutable built-in collections | `transient`/`persistent!` | Controlled mutable views |
