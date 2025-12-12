# Spork Language Reference

Spork is a Lisp dialect that compiles to Python, featuring persistent data structures, macros, and seamless Python interop.

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
| `^expr form` | `(Decorated expr form)` | Metadata/decorators |
| `;comment` | (ignored) | Line comment |

#### Extended Reader Macros

| Syntax | Description |
|--------|-------------|
| `#(...)` | Hoisted lambda with `%`, `%1`-`%N`, `%&` args |
| `#[start stop step]` | Slice literal (use `_` for None) |
| `#_form` | Discard next form (parsed but not compiled) |
| `#f"..."` | F-string with `{expr}` interpolation |
| `#p"..."` | Path literal (`pathlib.Path`) |
| `#r"..."` | Regex literal (compile-time validated) |
| `#uuid"..."` | UUID literal (compile-time validated) |
| `#inst"..."` | ISO-8601 datetime literal |
| `#=form` | Read-time evaluation |

See the [Standard Library Reference](STDLIB.md#reader-macros) for detailed documentation and examples of each reader macro.

### Literals

```clojure
; Numbers
42          ; integer
3.14        ; float
-17         ; negative

; Strings
"hello"     ; double-quoted string
"line1\nline2"  ; escape sequences

; Keywords
:name       ; keyword (self-evaluating symbol)
:my-key     ; keywords can have hyphens

; Keywords are callable for map lookup
(:name {:name "Alice"})         ; => "Alice"
(:missing {:a 1} "default")     ; => "default" (with default)
(map :name users)               ; great for extracting values

; Booleans and nil
true        ; Python True
false       ; Python False
nil         ; Python None

; Keyword argument splat (for function calls)
*{:name "Alice" :age 30}        ; splats as name="Alice", age=30
```

---

## 2. Data Structures

Spork provides **persistent (immutable) data structures** implemented as a C extension for performance.

The core types are:
- `Vector` - Persistent vector (32-way bit-partitioned trie)
- `Map` - Persistent hash map (HAMT)
- `Set` - Persistent hash set (HAMT)
- `DoubleVector` - Type-specialized vector for floats (float64)
- `IntVector` - Type-specialized vector for integers (int64)
- `SortedVector` - Persistent sorted vector (Red-Black tree)
- `Cons` - Linked list cells

### Vectors

```clojure
[1 2 3]              ; literal syntax -> Vector
(vec 1 2 3)          ; constructor function

; Operations
(nth v 0)            ; get element by index
(conj v 4)           ; add element (returns new vector)
(assoc v 1 99)       ; set element (returns new vector)
(pop v)              ; remove last element
(count v)            ; length
(+ v1 v2)            ; concatenation

; Type-specialized vectors for numeric performance
; Note: vec-f64 and vec_f64 are equivalent due to identifier normalization
(vec-f64 1.0 2.0 3.0)  ; DoubleVector (float64)
(vec-i64 1 2 3)        ; IntVector (int64)
```

### Maps

```clojure
{:a 1 :b 2}          ; literal syntax -> Map
(hash-map :a 1 :b 2) ; constructor function

; Operations
(get m :a)           ; get value (nil if missing)
(get m :x :default)  ; get with default
(:a m)               ; keywords are callable for lookup
(:x m :default)      ; with default value
(assoc m :c 3)       ; add/update key
(dissoc m :a)        ; remove key
(count m)            ; number of entries
```

### Sets

```clojure
#{1 2 3}             ; literal syntax -> Set
(hash-set [1 2 3])   ; constructor from iterable

; Operations
(conj s 4)           ; add element (returns new set)
(disj s 2)           ; remove element (returns new set)
(contains? s 1)      ; check membership
(in 1 s)             ; alternative membership check
(count s)            ; number of elements

; Set operations
(bit-or s1 s2)       ; union
(bit-and s1 s2)      ; intersection
(bit-xor s1 s2)      ; symmetric difference

; Comparison
(= s1 s2)            ; equality (order-independent)
(< s1 s2)            ; proper subset
(<= s1 s2)           ; subset
(> s1 s2)            ; proper superset
(>= s1 s2)           ; superset
```

### Lists (Cons Cells)

```clojure
'(1 2 3)             ; quoted list
(cons 0 lst)         ; prepend element

; Operations
(first lst)          ; head
(rest lst)           ; tail
```

### SortedVector

Persistent sorted vectors maintain elements in sorted order using a Red-Black tree. All operations are O(log n).

```clojure
; Creating sorted vectors
(sorted_vec [3 1 4 1 5 9])    ; => sorted_vec(1, 1, 3, 4, 5, 9)
(sorted_vec)                   ; empty sorted vector

; With key function (sort by result of key-fn)
(sorted_vec ["banana" "apple" "cherry"] :key len)
; => sorted_vec("apple", "banana", "cherry")

; Reverse order
(sorted_vec [3 1 4] :reverse true)  ; => sorted_vec(4, 3, 1)

; Basic operations
(conj sv 2)          ; add element, maintains sorted order
(disj sv 3)          ; remove one occurrence of element
(nth sv 0)           ; get element by index (O(log n))
(first sv)           ; smallest element (or largest if reversed)
(last sv)            ; largest element (or smallest if reversed)
(count sv)           ; number of elements

; Search operations
(contains? sv 5)     ; check if element exists (O(log n))
(.index_of sv 5)     ; index of element, or -1 if not found
(.rank sv 5)         ; count of elements less than given value
```

### Sequence Abstraction

All collections support the sequence protocol:

```clojure
(seq coll)           ; convert to sequence
(first coll)         ; first element
(rest coll)          ; remaining elements
(into [] coll)       ; pour into target collection
```

---

## 3. Special Forms

### Definition

```clojure
; Define a value
(def x 42)

; Define with destructuring
(def [a b] [1 2])
(def {:keys [name age]} person)

; Mutation (for existing bindings)
(set! x 100)
(set! obj.attr value)
```

### Let Bindings

```clojure
; Basic let
(let [x 1
      y 2]
  (+ x y))

; Sequential binding (later bindings see earlier ones)
(let [x 1
      y (+ x 1)]
  y)  ; => 2

; Destructuring in let
(let [[a b] [1 2]
      {:keys [name]} {:name "Alice"}]
  (str name ": " a ", " b))
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

### For Loop

```clojure
; For is a statement (for side effects)
(for [x [1 2 3]]
  (print x))
```

### Vector Comprehension

```clojure
; Square brackets with for creates a vector (efficient, uses transients)
(def squares [for [x (range 10)] (* x x)])
; => [0 1 4 9 16 25 36 49 64 81]

; Works with any expression, including conditionals
[for [x (range 10)] (if (even? x) (* x 2) nil)]
; => [0 nil 4 nil 8 nil 12 nil 16 nil]

; Supports destructuring
(def pairs [[1 2] [3 4] [5 6]])
[for [[a b] pairs] (+ a b)]
; => [3 7 11]

; Can use let and other expressions in body
[for [x (range 5)] (let [sq (* x x)] (+ sq 1))]
; => [1 2 5 10 17]
```

### Sorted Vector Comprehension

```clojure
; Use sorted-for to build a sorted vector from a comprehension
[sorted-for [x (range 10)] (* x x)]
; => sorted_vec(0, 1, 4, 9, 16, 25, 36, 49, 64, 81)

; With :key function for custom sorting
[sorted-for [s ["banana" "apple" "fig"]] s :key len]
; => sorted_vec("fig", "apple", "banana")

; With :reverse for descending order
[sorted-for [x [3 1 4 1 5]] x :reverse true]
; => sorted_vec(5, 4, 3, 1, 1)

; Combine :key and :reverse
[sorted-for [item items] 
            {:name (:name item) :score (:score item)}
            :key :score :reverse true]
; => sorted by score, highest first

; Real-world example: rank GitHub repos by stars
[sorted-for [repo repos]
            {:name repo :stars (fetch-stars repo)}
            :key :stars :reverse true]
```

### Loop / Recur (Tail-Call Optimization)

```clojure
; Loop with explicit recursion point
(loop [i 0
       acc 0]
  (if (>= i 10)
    acc
    (recur (inc i) (+ acc i))))

; recur MUST be in tail position
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

The `#(...)` reader macro provides a concise syntax for simple anonymous functions:

```clojure
; Using % for the single argument
(map #(+ % 1) [1 2 3])              ; => [2 3 4]
(filter #(> % 5) [3 6 2 8])         ; => [6 8]

; Multiple args: %1, %2, etc.
(reduce #(+ %1 %2) [1 2 3 4])       ; => 10

; Rest args with %&
(def sum-all #(apply + %&))
(sum-all 1 2 3 4 5)                 ; => 15
```

See [Reader Macros](#reader-macros) for more details.

### Named Functions

```clojure
(defn square [x]
  (* x x))

; With docstring
(defn greet [name]
  "Returns a greeting string."
  (str "Hello, " name "!"))
```

### Multi-Arity Functions

```clojure
(defn greet
  ([name]
   (greet name "Hello"))
  ([name greeting]
   (str greeting ", " name "!")))

(greet "Alice")           ; => "Hello, Alice!"
(greet "Alice" "Hi")      ; => "Hi, Alice!"
```

### Variadic Functions

```clojure
; Rest arguments
(defn sum [& nums]
  (reduce + 0 nums))

(sum 1 2 3 4)  ; => 10

; Mixed positional and rest
(defn log [level & msgs]
  (print level ":" (apply str msgs)))
```

### Keyword Arguments

Keyword arguments use the `*{:key value}` syntax - a map prefixed with `*` that splats as keyword arguments. There is also a shorthand for keyword-only arguments using `*` followed by `:keyword value`. As well as splatting a map using `*{mapname}` this will map the keys to symbols or kwargs.

```clojure
; Keyword-only arguments (after *)
(defn create-user [name * age email]
  {:name name :age age :email email})

; Call with *{...} syntax for keyword args
(create-user "Alice" * :age 30 :email "alice@example.com")

; Keyword-only with defaults
(defn config [host * (port 8080) (debug false)]
  {:host host :port port :debug debug})

(config "localhost")                            ; uses defaults
(config "example.com" *{:port 3000})            ; override port only
(config "example.com" * :port 3000 :debug true) ; override port only

; Multiple kwarg splats are allowed (after positional args)
(make-request "POST" "/api" *{:headers h} *{:body b :timeout 30})

; Kwargs collection with **
(defn flexible [required ** opts]
  {:required required :opts opts})

(flexible "value" *{:a 1 :b 2})               ; opts = {"a": 1, "b": 2}

; Works with Python functions too
(.format "{name} is {age}" *{:name "Alice" :age 30})
```

### Destructuring in Parameters

```clojure
(defn process-point [[x y]]
  (+ x y))

(defn greet-person [{:keys [name age]}]
  (str name " is " age " years old"))
```

---

## 6. Type Annotations

Spork supports Python-compatible type annotations using the `^type` prefix syntax. Type annotations are compiled to standard Python annotations, enabling static analysis, IDE support, and runtime introspection.

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
  (str "Hello, " name))

; Multiple annotations
(defn add [^int x ^int y]
  (+ x y))

; Mixed annotated and unannotated
(defn format-message [^str prefix message]
  (str prefix ": " message))

; Compiles to:
; def add(x: int, y: int):
;     return x + y
```

### Return Type Annotations

```clojure
; Return type before function name
(defn ^int square [^int x]
  (* x x))

(defn ^str greet [^str name]
  (str "Hello, " name "!"))

; Compiles to:
; def square(x: int) -> int:
;     return x * x
```

### Generic Types 

Common generic types are available without imports:

```clojure
; List, Dict, Set, Tuple (Python typing)
(def ^(List int) numbers [1 2 3])
(def ^(Dict str int) ages {"alice" 30})
(def ^(Set str) tags #{"a" "b"})

; Optional (for nullable values)
(defn ^(Optional str) find-name [^int id]
  (if (valid? id)
    (lookup id)
    nil))

; Union types
(def ^(Union int str) value 42)

; Callable (both syntaxes work)
(defn apply-fn [^(Callable int int) f ^int x]
  (f x))

; Or with Python-style nested brackets:
(defn apply-fn2 [^(Callable [[int] int]) f ^int x]
  (f x))

; Compiles to:
; numbers: List[int] = vec(1, 2, 3)
; def find_name(id: int) -> Optional[str]:
```

### Available Type Constructors

The following types are available without importing `typing`:

| Type | Description |
|------|-------------|
| `Any` | Any type |
| `Optional` | Value or None |
| `Union` | One of several types |
| `List` | List/sequence type |
| `Dict` | Dictionary/mapping type |
| `Set` | Set type |
| `Tuple` | Fixed-length tuple |
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
(def ^(Set str) tags #{"a" "b" "c"})
(def ^(Cons int) items (cons 1 (cons 2 nil)))

; Type-specialized vectors for numeric data
; These are automatically selected when using ^(Vector float) or ^(Vector int)
(def ^(Vector float) floats [1.0 2.0 3.0])  ; -> DoubleVector
(def ^(Vector int) ints [1 2 3])            ; -> IntVector
```

| Type | Description |
|------|-------------|
| `Vector` | Persistent vector (generic) |
| `Map` | Persistent hash map |
| `DoubleVector` | Vector of float64 (with NumPy buffer protocol) |
| `IntVector` | Vector of int64 (with NumPy buffer protocol) |
| `Cons` | Linked list cell |

### Runtime Introspection

Type annotations are available at runtime via `__annotations__`:

```clojure
(defn ^int add [^int x ^int y] (+ x y))

(print (. add __annotations__))
; => {'x': <class 'int'>, 'y': <class 'int'>, 'return': <class 'int'>}
```

---

## 7. Pattern Matching

### Match Expression

```clojure
(match value
  pattern1 result1
  pattern2 result2
  _ default-result)
```

### Pattern Types

```clojure
; Literals
(match x
  1 "one"
  2 "two"
  _ "other")

; Type patterns
(match x
  ^int n (str "integer: " n)
  ^str s (str "string: " s)
  _ "unknown")

; Sequence patterns
(match coll
  [] "empty"
  [x] (str "one: " x)
  [x y] (str "two: " x ", " y)
  [x & rest] (str "many, first: " x))

; Map patterns
(match m
  {:type :circle :radius r} (* 3.14 r r)
  {:type :square :side s} (* s s)
  _ 0)

; Guards
(match x
  (n :when (> n 0)) "positive"
  (n :when (< n 0)) "negative"
  _ "zero")
```

### Multi-Dispatch Functions

```clojure
(defn area
  ([{:type :circle :radius r}]
   (* 3.14 r r))
  ([{:type :rectangle :width w :height h}]
   (* w h))
  ([{:type :square :side s}]
   (* s s)))
```

---

## 8. Classes

### Basic Class Definition

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
    (call (super) __init__ x y)
    (set! self.color color)))
```

### Decorators

```clojure
(defclass ^dataclass Person []
  (field name str)
  (field age int 0))

(defclass Counter []
  ^staticmethod
  (defn create []
    (Counter))

  ^classmethod
  (defn from-value [cls value]
    (let [c (cls)]
      (set! c.value value)
      c)))
```

### Fields (for dataclasses)

```clojure
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

; Check if type satisfies protocol
(satisfies? IShape my-object)
```

---

## 10. Namespaces & Modules

### Namespace Declaration

```clojure
(ns my.app.core
  (:require
    [spork.pds :as pds]
    [my.utils :refer [helper-fn]]
    [external.lib :refer :all])
  (:import
    [numpy :as np]
    [os.path :as osp]
    [collections :refer [defaultdict Counter]]
    [math :refer [sin cos]]))
```

### Require Options (for Spork namespaces)

```clojure
; Alias - access with dot notation: pds.vec, short.foo
[some.long.module :as short]

; Specific imports into current namespace
[module :refer [fn1 fn2]]

; Import all public symbols
[module :refer :all]
```

### Import Options (for Python modules)

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
(print os.getcwd)
(print (j.dumps {:a 1}))
(print (math.sin 0.5))
```

### Importing Macros

Macros are imported via the standard `:require` form, just like regular functions. The compiler automatically detects whether a referred symbol is a macro or a regular def:

```clojure
; Import macros via :require :refer - compiler handles discovery
(ns my.app
  (:require [my.macros :refer [my-macro]]     ; my-macro is automatically recognized as a macro
            [other.lib :as lib :refer [foo]])) ; foo could be a macro or a function

; Use the macro
(my-macro some args)

; Qualified macro access via alias
(lib.some-macro arg)

; :refer :all imports all macros and defs
(ns another.app
  (:require [my.macros :refer :all]))
```

### Dot Notation for Namespace Access

Unlike Clojure, Spork uses dot notation for all namespace/module access:

```clojure
; All namespace/module access uses dot notation
(ns my.app
  (:require [std.string :as str]
            [math :as m])
  (:import [numpy :as np]))

; Access via dots (not slashes)
(str.join ", " ["a" "b" "c"])  ; => "a, b, c"
(m.sqrt 16)                     ; => 4.0
(np.array [1 2 3])              ; numpy array
```

---

## 11. Macros

### Defining Macros

```clojure
(defmacro unless [test & body]
  `(if ~test nil (do ~@body)))

(defmacro with-timer [& body]
  `(let [start# (time.time)]
     (let [result# (do ~@body)]
       (print "Elapsed:" (- (time.time) start#))
       result#)))
```

### Quasiquoting

```clojure
; ` - quasiquote (template)
; ~ - unquote (evaluate)
; ~@ - unquote-splicing (flatten list)

(defmacro debug [expr]
  `(let [val# ~expr]
     (print '~expr "=" val#)
     val#))
```

### Auto-gensym

Use `#` suffix to generate unique symbols:

```clojure
(defmacro swap! [a b]
  `(let [tmp# ~a]
     (set! ~a ~b)
     (set! ~b tmp#)))
```

---

## 12. Async & Generators

### Async Functions

```clojure
(defn ^async fetch-data [url]
  (let [response (await (http.get url))]
    response.json))

; Async for
(async-for [item (async-iterator)]
  (process item))
```

### Generators

```clojure
(defn ^generator count-up [start]
  (loop [n start]
    (yield n)
    (recur (inc n))))

; Yield from (delegation)
(defn ^generator chain [& iterables]
  (for [it iterables]
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

```clojure
(throw (ValueError "invalid input"))
```

### Assert

```clojure
(assert (> x 0) "x must be positive")
```

---

## 14. Transient Data Structures

Transients provide **mutable** versions of persistent collections for efficient batch operations. Available for `Vector`, `Map`, `Set`, `SortedVector`, `DoubleVector`, and `IntVector`.

### Creating Transients

```clojure
(def v [1 2 3])
(def tv (transient v))  ; Create mutable version

; SortedVector transients preserve sort options
(def sv (sorted_vec [3 1 4] :key abs :reverse true))
(def tsv (transient sv))
```

### Mutating Operations

```clojure
; Vector operations
(conj! tv 4)         ; Add element (mutates in place)
(assoc! tv 0 100)    ; Set by index
(pop! tv)            ; Remove last element

; Map operations
(def tm (transient {:a 1}))
(assoc! tm :b 2)     ; Add/update key
(dissoc! tm :a)      ; Remove key
(conj! tm [:c 3])    ; Add pair

; Set operations
(def ts (transient #{1 2 3}))
(conj! ts 4)         ; Add element
(disj! ts 2)         ; Remove element

; SortedVector operations
(def tsv (transient (sorted_vec [1 3 5])))
(conj! tsv 2)    ; Add element (maintains sort order)
(conj! tsv 4)    ; => now contains 1, 2, 3, 4, 5
(conj! tsv 3)    ; Remove element
```

### Converting Back to Persistent

```clojure
(def v2 (persistent! tv))  ; Lock and return immutable
; tv can no longer be used after persistent!
```

### The `with-mutable` Macro

The recommended way to work with transients is the `with-mutable` macro, which handles the `transient` and `persistent!` calls automatically:

```clojure
; Returns persistent collection when done
(with-mutable [m {:a 1}]
  (assoc! m :b 2)
  (assoc! m :c 3))
; => {:a 1 :b 2 :c 3}

(with-mutable [v [1 2 3]]
  (.append v 4)
  (.append v 5))
; => [1 2 3 4 5]
```

> Note: Inside `with-mutable`, vectors/maps/sets behave like mutable collections and expose a Python-like API for better compatibility with outside code. 

### Python Protocol Support

Transient collections implement Python's mutable collection ABCs, making them compatible with Python libraries:

| Transient Type | Python Protocol | Equivalent To |
|----------------|-----------------|---------------|
| `TransientMap` | `MutableMapping` | `dict` |
| `TransientVector` | `MutableSequence` | `list` |
| `TransientSet` | `MutableSet` | `set` |

This enables using Python methods directly on transients:

```clojure
; TransientVector: .append, .extend, len, in, iteration
(with-mutable [v []]
  (.extend v [1 2 3])
  (.append v 4)
  (print (len v))        ; 4
  (print (in 2 v)))      ; True

; TransientMap: .get, .keys, .values, .items, len, in, iteration
(with-mutable [m {}]
  (assoc! m :a 1)
  (print (.get m :a))    ; 1
  (for [k m] (print k))) ; iterates keys

; TransientSet: .add, .discard, .remove, .clear, len, in, iteration
(with-mutable [s #{}]
  (.add s 1)
  (.add s 2)
  (.discard s 1)
  (.remove s 2))         ; raises KeyError if missing
```

You can pass transients to Python libraries expecting mutable collections:

```clojure
(with-mutable [config {}]
  (some-python-lib.load-config config)
  ; config now contains modifications from Python
  )
```

### Typical Pattern

```clojure
; Efficient batch building
(defn build-vector [n]
  (let [t (transient [])]
    (for [i (range n)]
      (conj! t i))
    (persistent! t)))

; The `into` function uses transients internally
(into [] (range 1000))
```

---

## 15. Python Interop

### Keyword Arguments

Use `*{...}` or `* :key val :key val` to pass keyword arguments to Python (and Spork) functions. If using shorthand `*` it must be followed by keyword arguments:

```clojure
; Basic keyword arguments
(some-func 1 2 *{:name "Alice" :age 30})
; => some_func(1, 2, name="Alice", age=30)

; Works with Python methods
(.format "{name} is {age}" *{:name "Bob" :age 25})
; => "Bob is 25"

; Multiple kwarg splats are allowed (after positional args)
(f pos1 pos2 *{:a 1} *{:b 2 :c 3})

; Keywords as values are distinct from kwargs
(get m :name)              ; :name is passed as a Keyword value
(:name m)                  ; keyword as function for lookup
(f * :name "x")           ; name="x" keyword argument
```

### Attribute Access

```clojure
; Dot notation
obj.attr              ; get attribute
(set! obj.attr val)   ; set attribute

; Method calls
(.method obj arg1 arg2)
(. obj method arg1 arg2)
```

### Python Builtins

Common Python built-in functions are available:

```clojure
(print "hello")
(len coll)
(type obj)
(isinstance obj SomeClass)
(str x)
(int s)
(list coll)
(dict pairs)
```

### Operators

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

```clojure
; Basic with
(with [f (open "file.txt" "r")]
  (print (.read f)))

; Multiple bindings
(with [f1 (open "in.txt")
       f2 (open "out.txt" "w")]
  (.write f2 (.read f1)))

; Without binding (for side effects)
(with [(some-context)]
  (do-work))

; Destructuring
(with [[reader writer] (create-pipe)]
  (process reader writer))
```

### Slice Syntax

Spork provides the `#[...]` reader macro for clean slice syntax:

```clojure
; Slice literal syntax (preferred)
(get my-vec #[start stop])       ; items from start to stop-1
(get my-vec #[start stop step])  ; with step
(get my-vec #[_ _ -1])           ; reverse (use _ for None)

; Examples with vectors
(def v [0 1 2 3 4 5 6 7 8 9])
(get v #[2 5])                   ; => [2 3 4]
(get v #[_ _ -1])                ; => [9 8 7 6 5 4 3 2 1 0]
(get v #[0 8 2])                 ; => [0 2 4 6]
(get v #[5 _])                   ; => [5 6 7 8 9]

; Works with Python lists too
(def py-list (list [1 2 3 4 5]))
(get py-list #[1 4])             ; => [2, 3, 4]

; Alternative: Python method call syntax
(. coll (slice start end))
(. coll (slice start end step))
```

See [Reader Macros](#reader-macros) for more details on `#[...]`.

---

## 16. Error Reporting

Spork provides **source-mapped error reporting**. When runtime errors occur, tracebacks point to the original `.spork` source files with accurate line numbers and code context—not the generated Python code.

### Traceback Example

Given this Spork code:

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

Running it produces:

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

```clojure
(defn calculate [x]
  (+ x undefined-var))

(calculate 10)
```

Produces:

```
Error: name 'undefined_var' is not defined
  File "example.spork", line 2, in calculate
    (+ x undefined-var))
         ~~~~~~~~~^~~~
NameError: name 'undefined_var' is not defined
```

Note that the error message shows the normalized Python name (`undefined_var`) but the source location points to the original Spork code.

### Type Errors

```clojure
(defn add-numbers [a b]
  (+ a b))

(add-numbers 10 "oops")
```

Produces:

```
Error: unsupported operand type(s) for +: 'int' and 'str'
  File "example.spork", line 2, in add_numbers
    (+ a b))
    ^^^^^^^
TypeError: unsupported operand type(s) for +: 'int' and 'str'
```

### Assertion Errors

```clojure
(defn validate-positive [n]
  (assert (> n 0) "Expected positive number")
  n)

(validate-positive -5)
```

Produces:

```
Error: Expected positive number
  File "example.spork", line 2, in validate_positive
    (assert (> n 0) "Expected positive number")
AssertionError: Expected positive number
```

### Syntax Errors

Syntax errors are caught at compile time and include location information:

```clojure
(defn broken [x]
  (let [y 10]
    (+ x y)
; Missing closing parens
```

Produces:

```
SyntaxError: unterminated list, expected )
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

Python distinguishes statements (no value) from expressions. Spork bridges this gap:

- **Statement context**: Top level, inside `do`, function bodies
- **Expression context**: Function arguments, variable bindings

When a statement-like construct (`let`, `try`, `with`) appears in expression context, Spork wraps it in an immediately-invoked function:

```clojure
; This expression context let:
(def result (let [x 1] (+ x 2)))

; Compiles roughly to:
; def _wrapper():
;     x = 1
;     return x + 2
; result = _wrapper()
```

---

## Appendix: Feature Comparison

| Feature | Python | Spork | Implementation |
|---------|--------|-------|----------------|
| Tail Recursion | No (stack overflow) | Yes (`recur`) | Compiles to while loop |
| Data Structures | Mutable | Immutable | C extension (HAMT) |
| Conditionals | `if/elif/else` | `cond`, `match` | Decision tree compilation |
| Metaprogramming | Decorators | Macros | AST transformation |
| Variable Scope | Function/global | Block (`let`) | IIFE simulation |
| Function Arity | Default args | Overloading | Runtime dispatch |
| Destructuring | Tuple unpacking | Deep map/vec | Recursive assignment |
| Imports | `import` | `ns :require` | Unified import with auto macro discovery |
| Protocols | ABC | `defprotocol` | Runtime dispatch table |
| Transients | N/A | `transient`/`persistent!` | Mutable batch operations |
