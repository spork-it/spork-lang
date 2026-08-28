# Spork Standard Library Reference

This reference covers the values and functions available in every Spork namespace, the automatically loaded prelude macros, reader syntax, and the bundled `std.*` modules.

> **Version note:** Spork is alpha software. This reference describes the current `main` branch and may be ahead of the latest PyPI release.

For special forms and language semantics, use the [Language Reference](LANG.md). For project commands and `spork.it`, use [Projects and CLI](PROJECTS.md).

## Conventions

- Hyphenated Spork names normalize to underscored Python bindings: `take-while` and `take_while` resolve to the same function.
- `; => value` is an exact, machine-checked expectation. For a lazy operation, it shows logical contents after realization rather than the raw Python generator representation.
- Use `vec` or `doall` to realize a lazy result as a persistent vector. Use `dorun` to consume it only for side effects.
- Collection iteration order is not guaranteed for maps and sets. Examples showing one order should not be used as ordering assertions.

## Table of Contents

1. [Built-in Types](#built-in-types)
2. [Core Functions](#core-functions)
   - [Sequence operations](#sequence-operations)
   - [Transient operations](#transient-operations)
   - [Lazy sequences](#lazy-sequence-functions)
   - [Reducers and transformations](#predicates-on-sequences)
   - [Numeric and bitwise functions](#numeric-functions)
3. [Reader Macros](#reader-macros)
4. [Prelude Macros](#prelude-macros)
5. [Standard Library Modules](#standard-library-modules)
   - [`std.string`](#stdstring)
   - [`std.map`](#stdmap)
   - [`std.json`](#stdjson)

---

## Built-in Types

Spork provides persistent, immutable data structures implemented in C for performance.

### Vector

Persistent vectors provide efficient random access and updates. Vectors are created using square bracket syntax.

```clojure
; Creating vectors
[1 2 3 4 5]           ; literal syntax
(vec 1 2 3)           ; => [1 2 3]

; Basic operations
(conj [1 2] 3)        ; => [1 2 3]
(nth [1 2 3] 1)       ; => 2
(nth [1 2] 5 :default) ; => :default (with default)
(assoc [1 2 3] 1 42)  ; => [1 42 3]
(count [1 2 3])       ; => 3
(first [1 2 3])       ; => 1
(rest [1 2 3])        ; => (2 3)
(last [1 2 3])        ; => 3
(.pop [1 2 3])        ; => [1 2]
```

**Specialized Vectors:**
```clojure
; DoubleVector - Optimized for 64-bit floats
(isinstance (vec-f64 1.0 2.0 3.0) DoubleVector) ; => true

; an annotated vector literal can select specialized storage
(def ^(Vector float) v [1.0 2.0 3.0])
(isinstance v DoubleVector) ; => true

; IntVector - Optimized for 64-bit integers
(isinstance (vec-i64 1 2 3) IntVector) ; => true
```

### Map

Persistent hash maps accept any hashable key. Maps are created using curly brace syntax.

```clojure
; Creating maps
{:a 1 :b 2}              ; literal syntax
(hash-map :a 1 :b 2)     ; => {:a 1 :b 2}

; Basic operations
(assoc {:a 1} :b 2)      ; => {:a 1 :b 2}
(dissoc {:a 1 :b 2} :a)  ; => {:b 2}
(get {:a 1} :a)          ; => 1
(get {:a 1} :b)          ; => nil
(get {:a 1} :b 42)       ; => 42 (with default)
(:a {:a 1})              ; => 1 (keywords are callable)
(:missing {:a 1} "nope") ; => "nope" (with default)
(count {:a 1 :b 2})      ; => 2
(contains? {:a 1} :a)    ; => true
(.keys {:a 1 :b 2})      ; iterable view of keys
(.values {:a 1 :b 2})    ; iterable view of values
```

### Set

Persistent sets. Sets are created using `#{}` syntax.

```clojure
; Creating sets
#{1 2 3}               ; literal syntax
(hash-set [1 2 3])     ; => #{1 2 3}

; Basic operations
(conj #{1 2} 3)        ; => #{1 2 3}
(disj #{1 2 3} 2)      ; => #{1 3}
(contains? #{1 2} 1)   ; => true
(contains? #{1 2} 5)   ; => false
(count #{1 2 3})       ; => 3

; Set operations
(| #{1 2} #{2 3})      ; => #{1 2 3} (union)
(& #{1 2} #{2 3})      ; => #{2} (intersection)
(- #{1 2 3} #{2})      ; => #{1 3} (difference)
```

### Cons (Linked List)

Singly linked lists created by `cons`, quoting, and eager sequence conversion with `seq`.

```clojure
; Creating lists
(cons 1 nil)              ; => (1)
(cons 1 (cons 2 nil))     ; => (1 2)
(cons 0 '(1 2 3))         ; => (0 1 2 3)

; Basic operations
(first (cons 1 (cons 2 nil)))  ; => 1
(rest (cons 1 (cons 2 nil)))   ; => (2)
(first nil)                    ; => nil
(rest nil)                     ; => nil
```

### Keyword

Interned symbols that evaluate to themselves. Prefixed with `:`. Keywords are callable for map lookup.

```clojure
; Keywords as values
:my-keyword                      ; a keyword
:namespaced.keyword              ; with namespace

; Keywords as functions (map lookup)
(:name {:name "Alice" :age 30})  ; => "Alice"
(:missing {:name "Alice"})       ; => nil
(:missing {:name "Alice"} "default")  ; => "default"

; Great for extracting from collections
(map :name [{:name "Alice"} {:name "Bob"}])  ; => ("Alice" "Bob")
(filter :active [{:active true} {:active false}])  ; => ({:active true})
```

### Symbol

Represents identifiers in Spork code. Used for variable and function names.

```clojure
'my-symbol      ; quoted symbol
'foo.bar        ; namespaced symbol
```

### SortedVector

Persistent sorted vectors retain duplicates in sorted order using a red-black tree. Indexed lookup, insertion, removal, membership, and rank queries are O(log n); full iteration is O(n). `sorted-vec` is the idiomatic spelling, while representations use the normalized runtime name `sorted_vec`.

```clojure
; Creating sorted vectors
(sorted-vec [3 1 4 1 5 9])      ; => sorted_vec(1, 1, 3, 4, 5, 9)
(sorted-vec)                     ; => sorted_vec()

; With key function (sort by result of key-fn)
(sorted-vec ["banana" "apple" "cherry"] *{:key len})
; => sorted_vec("apple", "banana", "cherry")

; With keyword as key (for sorting maps/dicts)
(sorted-vec [{:name "Bob" :age 25} {:name "Alice" :age 30}] *{:key :age})
; => [{:name "Bob" :age 25} {:name "Alice" :age 30}]

; Reverse order
(sorted-vec [3 1 4] *{:reverse true})  ; => sorted_vec(4, 3, 1)

; Combine key and reverse
(sorted-vec items *{:key :score :reverse true})
; => [{:name "two" :score 20} {:name "one" :score 10}]
```

**Basic Operations:**
```clojure
(def sv (sorted-vec [5 2 8 1 9]))

(count sv)           ; => 5
(first sv)           ; => 1 (minimum element)
(last sv)            ; => 9 (maximum element)
(nth sv 2)           ; => 5 (element at index 2)
(nth sv 10 :default) ; => :default (with default value)
(get sv 0)           ; => 1 (same as nth)
(get sv -1)          ; => 9 (negative indexing supported)
```

**Adding and Removing Elements:**
```clojure
(def sv (sorted-vec [1 3 5]))

(conj sv 2)          ; => sorted_vec(1, 2, 3, 5) - inserts in sorted position
(conj sv 3)          ; => sorted_vec(1, 3, 3, 5) - duplicates allowed
(disj sv 3)          ; => sorted_vec(1, 5) - removes one occurrence
(disj sv 99)         ; => sorted_vec(1, 3, 5) - no-op if not found
```

**Search Operations:**
```clojure
(def sv (sorted-vec [10 20 30 40 50]))

(contains? sv 30)    ; => true (O(log n) search)
(contains? sv 25)    ; => false
(.index_of sv 30)    ; => 2 (index of element)
(.index_of sv 25)    ; => -1 (not found)
(.rank sv 25)        ; => 2 (count of elements < 25)
(.rank sv 100)       ; => 5 (all elements are less)
```

**Iteration:**
```clojure
; Iterates in sorted order
(for [x (sorted-vec [3 1 4 1 5])]
  (print x))
; prints one value per line: 1, 1, 3, 4, 5

; Convert to vector
(vec (sorted-vec [3 1 4]))  ; => [1 3 4]
```

**Sorted Vector Comprehension:**
```clojure
; Use sorted-for to build a sorted vector from a comprehension
[sorted-for [x (range 10)] (* x x)]
; => sorted_vec(0, 1, 4, 9, 16, 25, 36, 49, 64, 81)

; With :key function
[sorted-for [s ["banana" "apple" "fig"]] s :key len]
; => sorted_vec("fig", "apple", "banana")

; With :reverse
[sorted-for [x [3 1 4 1 5]] x :reverse true]
; => sorted_vec(5, 4, 3, 1, 1)

; Real-world example: rank items by score
[sorted-for [item items]
            {:name (:name item) :score (:score item)}
            :key :score :reverse true]
; => [{:name "two" :score 20} {:name "one" :score 10}]
```

**Transient Operations:**
```clojure
; For batch operations, use transients
(def sv (sorted-vec [1 3 5]))
(def tsv (transient sv))

(conj! tsv 2)           ; mutates in place
(conj! tsv 4)
(disj! tsv 3)
(def result (persistent! tsv))  ; => sorted_vec(1, 2, 4, 5)

; Transient preserves key and reverse settings
(def sv (sorted-vec items *{:key :score :reverse true}))
(def tsv (transient sv))   ; still sorts by :score, reversed
```

**Equality and Hashing:**
```clojure
; Equal if same elements in same order
(= (sorted-vec [3 1 2]) (sorted-vec [1 2 3]))  ; => true
(= (sorted-vec [1 2]) (sorted-vec [1 2 3]))    ; => false

; Can be used as map keys (hashable)
(def cache {(sorted-vec [1 2 3]) "result"})
```

---

## Core Functions

### Sequence Operations

#### `first`
Returns the first element of a collection, or `nil` if empty.
```clojure
(first [1 2 3])      ; => 1
(first '(a b c))     ; => a
(first "hello")      ; => "h"
(first [])           ; => nil
(first nil)          ; => nil

; The first map key is unspecified
(def first-key (first {:a 1 :b 2}))
(contains? {:a 1 :b 2} first-key) ; => true
```

#### `rest`
Returns a sequence of all elements except the first. Returns `nil` when there is no remaining element.
```clojure
(rest [1 2 3])    ; => (2 3)
(rest [1])        ; => nil
(rest [])         ; => nil
(rest nil)        ; => nil
(rest "hello")    ; => ("e" "l" "l" "o")
```

#### `seq`
Eagerly converts an iterable to a `Cons` sequence, or returns `nil` for an empty input. Map entries become two-element vectors. Use the original lazy functions when eager conversion is not needed.
```clojure
(seq [1 2 3])     ; => (1 2 3)
(seq [])          ; => nil
(seq nil)         ; => nil
(seq "hi")        ; => ("h" "i")
(seq {:a 1})      ; => ([:a 1])

; Common pattern for checking if collection has elements
(if (seq coll)
  (print "has elements")
  (print "empty"))
```

#### `nth`
Returns the element at index n (0-based). Throws error if index out of bounds unless default provided.
```clojure
(nth [1 2 3] 0)          ; => 1
(nth [1 2 3] 1)          ; => 2
(nth [1 2 3] 2)          ; => 3
(nth [1 2 3] 5 :default) ; => :default
(nth "hello" 1)          ; => "e"

; Works with any sequential collection
(nth '(a b c) 1)         ; => b
```

#### `conj`
Adds one element to a collection. The position depends on the collection type: the end for vectors, sorted position for sorted vectors, and the front for lists.
```clojure
; Vectors add at end
(conj [1 2] 3)           ; => [1 2 3]

; Lists add at front
(conj '(1 2) 0)          ; => (0 1 2)

; Sets add element
(conj #{1 2} 3)          ; => #{1 2 3}
(conj #{1 2} 2)          ; => #{1 2} (already present)

; Maps add entry
(conj {:a 1} [:b 2])     ; => {:a 1 :b 2}
```

#### `assoc`
Associates a key with a value. Works on maps (any key) and vectors (index).
```clojure
; Maps
(assoc {:a 1} :b 2)           ; => {:a 1 :b 2}
(assoc {:a 1} :a 99)          ; => {:a 99} (replace)

; Vectors (by index)
(assoc [1 2 3] 1 42)          ; => [1 42 3]
(assoc [1 2 3] 0 :first)      ; => [:first 2 3]
```

#### `dissoc`
Removes a key from a map. Returns map unchanged if key not present.
```clojure
(dissoc {:a 1 :b 2} :a)       ; => {:b 2}
(dissoc {:a 1 :b 2} :c)       ; => {:a 1 :b 2} (key not present)
```

#### `disj`
Removes an element from a set. Returns set unchanged if element not present.
```clojure
(disj #{1 2 3} 2)        ; => #{1 3}
(disj #{1 2 3} 5)        ; => #{1 2 3} (not present)

; Also removes one matching value from a SortedVector
(disj (sorted-vec [1 2 2 3]) 2) ; => sorted_vec(1, 2, 3)
```

#### `get`
Returns the value for a key, with optional default. Works on maps, indexed collections, slices, and strings.
```clojure
; Maps
(get {:a 1 :b 2} :a)         ; => 1
(get {:a 1} :b)              ; => nil
(get {:a 1} :b :not-found)   ; => :not-found

; Vectors (by index)
(get [1 2 3] 1)              ; => 2
(get [1 2 3] 10)             ; => nil
(get [1 2 3] 10 :oops)       ; => :oops

; Strings
(get "hello" 1)              ; => "e"
```

#### `count`
Returns the number of elements in a collection.
```clojure
(count [1 2 3])         ; => 3
(count {:a 1 :b 2})     ; => 2
(count #{1 2 3 4})      ; => 4
(count "hello")         ; => 5
(count nil)             ; => 0
(count [])              ; => 0
```

#### `contains?`
Returns true if key is present in collection. For maps and sets, checks keys/elements. For vectors, checks if index exists.
```clojure
; Maps (checks keys)
(contains? {:a 1 :b 2} :a)   ; => true
(contains? {:a 1 :b 2} :c)   ; => false

; Sets (checks elements)
(contains? #{1 2 3} 2)       ; => true
(contains? #{1 2 3} 5)       ; => false

; Vectors (checks INDEX, not value!)
(contains? [1 2 3] 0)        ; => true (index 0 exists)
(contains? [1 2 3] 2)        ; => true (index 2 exists)
(contains? [1 2 3] 5)        ; => false (index 5 doesn't exist)
```

#### `empty`
Returns an empty collection of the same type.
```clojure
(empty [1 2 3])         ; => []
(empty {:a 1 :b 2})     ; => {}
(empty #{1 2 3})        ; => #{}
(empty '(1 2 3))        ; => nil
```

#### `into`
Pours all elements from one collection into another. Useful for converting between collection types.
```clojure
; Convert list to vector
(into [] '(1 2 3))           ; => [1 2 3]

; Convert vector to set
(into #{} [1 2 2 3 3 3])     ; => #{1 2 3}

; Build map from pairs
(into {} [[:a 1] [:b 2]])    ; => {:a 1 :b 2}

; Add to an existing collection
(into [0] [1 2 3])           ; => [0 1 2 3]

; Realize a lazy transformation into a chosen collection
(into [] (map inc [1 2 3]))   ; => [2 3 4]
```

### Transient Operations

Transients provide efficient batch updates to persistent collections. Use them when building up a collection through many operations.

#### `transient`
Creates a transient (mutable) version of a collection.
```clojure
(def tv (transient [1 2 3]))
(def tm (transient {:a 1}))
(def ts (transient #{1 2}))
```

#### `persistent!`
Converts a transient back to a persistent collection. The transient should not be used after this.
```clojure
(persistent! (transient [1 2 3]))  ; => [1 2 3]

; Common pattern: build then persist
(-> (transient [])
    (conj! 1)
    (conj! 2)
    (conj! 3)
    (persistent!))  ; => [1 2 3]
```

#### `conj!`
Adds to a transient collection (mutates in place). Returns the transient.
```clojure
(def tv (transient []))
(conj! tv 1)
(conj! tv 2)
(persistent! tv)  ; => [1 2]
```

#### `assoc!`
Associates in a transient map or vector.
```clojure
(def tm (transient {:a 1}))
(assoc! tm :b 2)
(assoc! tm :c 3)
(persistent! tm)  ; => {:a 1 :b 2 :c 3}

(def tv (transient [1 2 3]))
(assoc! tv 1 42)
(persistent! tv)  ; => [1 42 3]
```

#### `dissoc!`
Removes from a transient map.
```clojure
(def tm (transient {:a 1 :b 2 :c 3}))
(dissoc! tm :b)
(persistent! tm)  ; => {:a 1 :c 3}
```

#### `disj!`
Removes from a transient set.
```clojure
(def ts (transient #{1 2 3 4}))
(disj! ts 2)
(disj! ts 4)
(persistent! ts)  ; => #{1 3}
```

#### `pop!`
Removes last element from transient vector.
```clojure
(def tv (transient [1 2 3 4]))
(pop! tv)
(pop! tv)
(persistent! tv)  ; => [1 2]
```

#### SortedVector Transient Operations

SortedVector has its own transient type with methods that maintain sorted order:

```clojure
; Create transient from sorted vector
(def sv (sorted-vec [1 3 5 7]))
(def tsv (transient sv))

; Add elements (maintains sorted order)
(conj! tsv 2)    ; now contains 1, 2, 3, 5, 7
(conj! tsv 4)    ; now contains 1, 2, 3, 4, 5, 7
(conj! tsv 6)    ; now contains 1, 2, 3, 4, 5, 6, 7

; Remove elements
(disj! tsv 3)    ; now contains 1, 2, 4, 5, 6, 7
(disj! tsv 99)   ; no-op, element not present

; Convert back to persistent
(def result (persistent! tsv))  ; => sorted_vec(1, 2, 4, 5, 6, 7)

; Transient preserves key function and reverse settings
(def sv (sorted-vec items *{:key :score :reverse true}))
(def tsv (transient sv))
(conj! tsv new-item)  ; still sorted by :score in reverse
```

Note: After calling `persistent!`, the transient can no longer be used.

#### `with-mutable`
Executes body with a transient collection, automatically converting back to persistent when done. This is the recommended way to work with transients.
```clojure
; Build up a map
(def result
  (with-mutable [m {:a 1}]
    (assoc! m :b 2)
    (assoc! m :c 3)))
; => {:a 1 :b 2 :c 3}

; Build up a vector
(with-mutable [v [1 2 3]]
  (.append v 4)
  (.append v 5))
; => [1 2 3 4 5]

; Build up a set
(with-mutable [s #{1 2}]
  (.add s 3)
  (.add s 4))
; => #{1 2 3 4}
```

**Python Protocol Support:**

Transient collections implement Python's mutable collection protocols, making them compatible with Python libraries that expect mutable collections:

- `TransientMap` implements `MutableMapping` (like `dict`)
- `TransientVector` implements `MutableSequence` (like `list`)
- `TransientSet` implements `MutableSet` (like `set`)

This means you can use Python methods directly:
```clojure
; TransientVector supports .append, .extend, iteration
(with-mutable [v []]
  (.extend v [1 2 3])
  (.append v 4))

; TransientMap supports .get, .keys, .values, .items, iteration
(with-mutable [m {}]
  (assoc! m :a 1)
  (print (.keys m))
  (print (.values m)))

; TransientSet supports .add, .discard, .remove, .clear, iteration
(with-mutable [s #{}]
  (.add s 1)
  (.add s 2)
  (.discard s 1))
```

You can also pass transients to Python libraries that expect mutable collections:
```clojure
(with-mutable [config {}]
  ; Pass to a Python library that modifies dicts
  (some-python-lib.configure config)
  ; config now contains the modifications
  )
```

**Typical Transient Pattern:**
```clojure
(defn build-vector [n]
  (loop [tv (transient [])
         i 0]
    (if (< i n)
      (recur (conj! tv i) (inc i))
      (persistent! tv))))

(build-vector 5)  ; => [0 1 2 3 4]
```

### Lazy Sequence Functions

These functions return Python generators. Calling one does not realize its result; use `vec`, `doall`, iteration, or a reducer to consume it. `partition`, `partition-all`, `reverse`, and sorting helpers materialize their input when consumed and therefore are not suitable for infinite inputs.

#### `map`
Applies a function to each element of one or more collections.
```clojure
; Single collection
(map inc [1 2 3])              ; => (2 3 4)
(map str [1 2 3])              ; => ("1" "2" "3")

; Multiple collections (stops at shortest)
(map + [1 2 3] [10 20 30])     ; => (11 22 33)
(map + [1 2] [10 20 30])       ; => (11 22)
(map (fn [a b] [a b]) [1 2 3] [:a :b :c])
; => ([1 :a] [2 :b] [3 :c])

; With anonymous function
(map (fn [x] (* x x)) [1 2 3 4])  ; => (1 4 9 16)

; With keyword (extracts from maps)
(map :name [{:name "Alice"} {:name "Bob"}])  ; => ("Alice" "Bob")
```

#### `filter`
Returns elements for which predicate returns true.
```clojure
(filter even? [1 2 3 4 5 6])      ; => (2 4 6)
(filter odd? [1 2 3 4 5 6])       ; => (1 3 5)
(filter pos? [-2 -1 0 1 2])       ; => (1 2)
(filter #(isinstance % str) [1 "a" 2 "b"]) ; => ("a" "b")

; Filter with keyword (truthy values)
(filter :active [{:active true :name "A"}
                 {:active false :name "B"}
                 {:active true :name "C"}])
; => ({:active true :name "A"} {:active true :name "C"})

; Filter with set membership
(filter #(contains? #{2 4 6} %) [1 2 3 4 5 6]) ; => (2 4 6)
```

#### `take`
Returns first n elements.
```clojure
(take 3 [1 2 3 4 5])       ; => (1 2 3)
(take 10 [1 2 3])          ; => (1 2 3) (fewer than n)
(take 0 [1 2 3])           ; => ()
(take 5 (range))           ; => (0 1 2 3 4) (from infinite seq)
```

#### `take-while`
Returns elements while predicate is true, stops at first false.
```clojure
(take-while pos? [1 2 3 0 -1 5])     ; => (1 2 3)
(take-while even? [2 4 6 7 8 10])    ; => (2 4 6)
(take-while #(< % 5) [1 2 3 4 5 6])  ; => (1 2 3 4)
```

#### `drop`
Drops first n elements, returns rest.
```clojure
(drop 2 [1 2 3 4 5])       ; => (3 4 5)
(drop 10 [1 2 3])          ; => ()
(drop 0 [1 2 3])           ; => (1 2 3)
```

#### `drop-while`
Drops elements while predicate is true, returns rest.
```clojure
(drop-while pos? [1 2 3 0 -1 5])     ; => (0 -1 5)
(drop-while even? [2 4 6 7 8 10])    ; => (7 8 10)
(drop-while #(< % 5) [1 2 3 4 5 6])  ; => (5 6)
```

#### `concat`
Concatenates sequences together.
```clojure
(concat [1 2] [3 4])           ; => (1 2 3 4)
(concat [1 2] [3 4] [5 6])     ; => (1 2 3 4 5 6)
(concat [1 2] nil [3 4])       ; => (1 2 3 4)
(concat "ab" "cd")             ; => ("a" "b" "c" "d")
```

#### `repeat`
Returns a sequence of `x` repeated `n` times, using `(repeat x n)`. Without `n`, the result is infinite.
```clojure
(repeat "x" 3)              ; => ("x" "x" "x")
(repeat 0 5)                ; => (0 0 0 0 0)
(take 4 (repeat :a))        ; => (:a :a :a :a) (infinite)
(vec (repeat [1 2] 3))      ; => [[1 2] [1 2] [1 2]]
```

#### `cycle`
Returns an infinite cycle of collection elements.
```clojure
(take 7 (cycle [1 2 3]))    ; => (1 2 3 1 2 3 1)
(take 5 (cycle [:a :b]))    ; => (:a :b :a :b :a)
(take 6 (cycle "ab"))       ; => ("a" "b" "a" "b" "a" "b")
```

#### `iterate`
Returns infinite sequence: x, (f x), (f (f x)), ...
```clojure
(take 5 (iterate inc 0))        ; => (0 1 2 3 4)
(take 5 (iterate #(* 2 %) 1))   ; => (1 2 4 8 16)
(take 4 (iterate rest [1 2 3])) ; => ([1 2 3] (2 3) (3) nil)
```

#### `range`
Returns an integer range with Python's `range` semantics. With no arguments it is an infinite generator starting at zero.
```clojure
(range 5)            ; => (0 1 2 3 4)
(range 1 5)          ; => (1 2 3 4)
(range 0 10 2)       ; => (0 2 4 6 8)
(range 10 0 -1)      ; => (10 9 8 7 6 5 4 3 2 1)
(take 5 (range))     ; => (0 1 2 3 4) (infinite)
```

#### `interleave`
Interleaves elements from multiple sequences. Stops at shortest.
```clojure
(interleave [1 2 3] [:a :b :c])        ; => (1 :a 2 :b 3 :c)
(interleave [1 2] [:a :b :c])          ; => (1 :a 2 :b)
(interleave [1 2 3] [:a :b :c] ["x" "y" "z"])  
; => (1 :a "x" 2 :b "y" 3 :c "z")
```

#### `interpose`
Interposes separator between elements.
```clojure
(interpose :sep [1 2 3])          ; => (1 :sep 2 :sep 3)
(interpose ", " ["a" "b" "c"])    ; => ("a" ", " "b" ", " "c")
(apply + (map str (interpose "-" [1 2 3]))) ; => "1-2-3"
```

#### `partition`
Partitions into groups of n elements. Drops incomplete final group.
```clojure
(partition 2 [1 2 3 4 5 6])       ; => ([1 2] [3 4] [5 6])
(partition 2 [1 2 3 4 5])         ; => ([1 2] [3 4]) (drops 5)
(partition 3 [1 2 3 4 5 6 7 8 9]) ; => ([1 2 3] [4 5 6] [7 8 9])

; Optional step follows the collection (sliding window)
(partition 2 [1 2 3 4] 1)         ; => ([1 2] [2 3] [3 4])
(partition 3 [1 2 3 4 5] 1)       ; => ([1 2 3] [2 3 4] [3 4 5])
```

#### `partition-all`
Like partition but includes incomplete final group.
```clojure
(partition-all 2 [1 2 3 4 5])     ; => ([1 2] [3 4] [5])
(partition-all 3 [1 2 3 4 5])     ; => ([1 2 3] [4 5])
(partition-all 3 [1 2])           ; => ([1 2])

; Optional step follows the collection
(partition-all 3 [1 2 3 4] 1)     ; => ([1 2 3] [2 3 4] [3 4] [4])
```

#### `keep`
Returns non-nil results of (f item).
```clojure
(keep #(if (even? %) %) [1 2 3 4 5 6])  ; => (2 4 6)
(keep (fn [x] x) [1 nil 2 nil 3])      ; => (1 2 3)
(keep :name [{:name "A"} {} {:name "B"}])  ; => ("A" "B")

; Difference from filter: keep uses the RESULT of f
(keep #(if (pos? %) (* % 10)) [-1 0 1 2])  ; => (10 20)
```

#### `keep-indexed`
Like keep but f receives index and item.
```clojure
(keep-indexed #(if (even? %1) %2) [:a :b :c :d :e])  
; => (:a :c :e)  (items at even indices)

(keep-indexed #(if (> %1 1) %2) [:a :b :c :d])
; => (:c :d)  (items where index > 1)
```

#### `map-indexed`
Like map but f receives index and item.
```clojure
(map-indexed (fn [i x] [i x]) [:a :b :c])
; => ([0 :a] [1 :b] [2 :c])
(map-indexed #(.format "{}: {}" %1 %2) ["a" "b" "c"])
; => ("0: a" "1: b" "2: c")

(map-indexed (fn [i x] {:index i :value x}) [10 20 30])
; => ({:index 0 :value 10} {:index 1 :value 20} {:index 2 :value 30})
```

#### `dedupe`
Removes consecutive duplicates.
```clojure
(dedupe [1 1 2 2 3 1 1])     ; => (1 2 3 1)
(dedupe [1 2 3 4])           ; => (1 2 3 4) (no consecutive dups)
(dedupe [:a :a :a :b :b :a]) ; => (:a :b :a)
```

#### `distinct`
Removes all duplicates (not just consecutive).
```clojure
(distinct [1 2 1 3 2 4 3])   ; => (1 2 3 4)
(distinct [:a :b :a :c :b])  ; => (:a :b :c)
(distinct "abracadabra")     ; => ("a" "b" "r" "c" "d")
```

#### `flatten`
Flattens nested sequences into a single flat sequence.
```clojure
(flatten [[1 2] [3 4]])              ; => (1 2 3 4)
(flatten [[1 [2 3]] [[4] 5]])        ; => (1 2 3 4 5)
(flatten [1 [2 [3 [4 [5]]]]])        ; => (1 2 3 4 5)
(flatten [1 2 3])                    ; => (1 2 3)
```

#### `mapcat`
Maps then concatenates results. Equivalent to (apply concat (map f coll)).
```clojure
(mapcat #(repeat % 2) [1 2 3])       ; => (1 1 2 2 3 3)
(mapcat reverse [[1 2] [3 4]])       ; => (2 1 4 3)
(mapcat #(range %) [1 2 3])          ; => (0 0 1 0 1 2)

; Useful for "expanding" each element
(mapcat (fn [x] [x (* x 10)]) [1 2 3])  ; => (1 10 2 20 3 30)
```

### Predicates on Sequences

#### `some`
Returns first truthy result of (pred item), or nil if none.
```clojure
(some even? [1 3 5 6 7])         ; => true
(some even? [1 3 5 7])           ; => nil
(some #(> % 5) [1 2 3 4])        ; => nil
(some #(> % 5) [1 2 6 4])        ; => true

; Find an element using set membership
(some #(if (contains? #{3 5 7} %) %) [1 2 3 4]) ; => 3

; Return actual matching value
(some #(if (> % 5) %) [1 3 6 2]) ; => 6
```

#### `every`
Returns true if `(pred item)` is truthy for every item. Empty inputs, including `nil`, return true.
```clojure
(every even? [2 4 6 8])         ; => true
(every even? [2 4 5 6])         ; => false
(every pos? [1 2 3])            ; => true
(every #(isinstance % str) ["a" "b" "c"]) ; => true
(every (fn [x] x) [1 2 nil 3]) ; => false
```

#### `not-every`
Returns true if the predicate is falsy for at least one item.
```clojure
(not-every even? [2 4 6 8])     ; => false
(not-every even? [2 4 5 6])     ; => true
(not-every pos? [1 -1 2])       ; => true
```

#### `not-any`
Returns true if the predicate is falsy for every item.
```clojure
(not-any even? [1 3 5 7])       ; => true
(not-any even? [1 3 4 5])       ; => false
(not-any neg? [1 2 3])          ; => true
(not-any #(isinstance % str) [1 2 3]) ; => true
```

### Reduction Functions

#### `reduce`
Reduces a collection using a function. With 2 args, uses first element as initial value.
```clojure
; Sum
(reduce + [1 2 3 4])             ; => 10
(reduce + 0 [1 2 3 4])           ; => 10 (explicit init)
(reduce + 100 [1 2 3 4])         ; => 110

; Product (`*` is call syntax, so wrap it when passing it as a value)
(reduce #(* %1 %2) [1 2 3 4])    ; => 24

; Build string
(reduce + ["a" "b" "c"])         ; => "abc"

; Custom accumulator
(reduce (fn [acc x] (conj acc (* x 2)))
        []
        [1 2 3])                 ; => [2 4 6]

; Find max
(reduce max [3 1 4 1 5 9])       ; => 9
```

#### `reductions`
Returns lazy sequence of intermediate reduce values.
```clojure
(reductions + [1 2 3 4])         ; => (1 3 6 10)
(reductions + 0 [1 2 3 4])       ; => (0 1 3 6 10)
(reductions #(* %1 %2) [1 2 3 4]) ; => (1 2 6 24)
(reductions conj [] [1 2 3])     ; => ([] [1] [1 2] [1 2 3])
```

### Collection Transformations

#### `zipmap`
Creates a map from parallel sequences of keys and values.
```clojure
(zipmap [:a :b :c] [1 2 3])      ; => {:a 1 :b 2 :c 3}
(zipmap [1 2 3] [:a :b :c])      ; => {1 :a 2 :b 3 :c}
(zipmap [:a :b] [1 2 3])         ; => {:a 1 :b 2} (stops at shorter)

; Create lookup from list
(zipmap (range) ["a" "b" "c"])   ; => {0 "a" 1 "b" 2 "c"}
```

#### `group-by`
Groups elements by result of f.
```clojure
(group-by even? [1 2 3 4 5 6])   
; => {false [1 3 5] true [2 4 6]}

(group-by count ["a" "bb" "ccc" "dd" "e"])
; => {1 ["a" "e"] 2 ["bb" "dd"] 3 ["ccc"]}

(group-by :type [{:type :a :v 1} {:type :b :v 2} {:type :a :v 3}])
; => {:a [{:type :a :v 1} {:type :a :v 3}] :b [{:type :b :v 2}]}

(group-by first ["apple" "ant" "banana" "bear"])
; => {"a" ["apple" "ant"] "b" ["banana" "bear"]}
```

#### `frequencies`
Returns map of elements to their counts.
```clojure
(frequencies [1 1 2 3 2 1])      ; => {1 3 2 2 3 1}
(frequencies "abracadabra")      ; => {"a" 5 "b" 2 "r" 2 "c" 1 "d" 1}
(frequencies [:a :b :a :c :a :b]); => {:a 3 :b 2 :c 1}
```

#### `reverse`
Returns reversed sequence.
```clojure
(reverse [1 2 3 4])              ; => (4 3 2 1)
(reverse "hello")                ; => ("o" "l" "l" "e" "h")
(reverse '(a b c))               ; => (c b a)
(apply + (reverse "hello"))      ; => "olleh"
```

#### `sort`
Realizes its input and returns a sorted `Vector`. Optional Python-style `:key` and `:reverse-order` keyword arguments control ordering.
```clojure
(sort [3 1 4 1 5 9 2 6])                    ; => [1 1 2 3 4 5 6 9]
(sort ["c" "a" "b"])                        ; => ["a" "b" "c"]
(sort [3 1 4 1 5] * :reverse-order true)     ; => [5 4 3 1 1]
(sort ["aaa" "b" "cc"] * :key len)           ; => ["b" "cc" "aaa"]
```

#### `sort-by`
Realizes its input and returns a `Vector` ordered by a key function.
```clojure
(sort-by count ["aaa" "b" "cc"]) ; => ["b" "cc" "aaa"]
(sort-by :age [{:age 30} {:age 20} {:age 25}])
; => [{:age 20} {:age 25} {:age 30}]

(sort-by :name [{:name "Charlie"} {:name "Alice"} {:name "Bob"}])
; => [{:name "Alice"} {:name "Bob"} {:name "Charlie"}]
```

Use `sort` with `:reverse-order true` when descending order is required.

#### `split-at`
Realizes the input and returns a Python tuple containing two vectors.
```clojure
(split-at 2 [1 2 3 4 5])         ; => ([1 2], [3 4 5])
(split-at 0 [1 2 3])             ; => ([], [1 2 3])
(split-at 10 [1 2 3])            ; => ([1 2 3], [])
```

#### `split-with`
Realizes the input and returns two vectors split at the first falsy predicate result.
```clojure
(split-with #(< % 3) [1 2 3 4 1 2]) ; => ([1 2], [3 4 1 2])
(split-with pos? [1 2 0 3 4])        ; => ([1 2], [0 3 4])
(split-with even? [2 4 6 7 8])       ; => ([2 4 6], [7 8])
```

### Sequence Realization

#### `doall`
Consumes an iterable and returns its results as a persistent `Vector`.
```clojure
(doall (map print [1 2 3]))      ; => [nil nil nil]
; also prints each value on its own line
(def realized (doall (map inc (range 5))))
realized                          ; => [1 2 3 4 5]
```

#### `dorun`
Forces realization, returns nil. Use for side effects when you don't need the results.
```clojure
(dorun (map print [1 2 3]))      ; => nil
; also prints each value on its own line

; More memory efficient than doall when you don't need results
(dorun (map #(save-to-db %) large-collection))
```

#### `realized?`
Distinguishes raw Python generator objects from concrete or sequence values. It returns false for a generator even after that generator has been partly or fully consumed; it does not track realization progress.
```clojure
(def lazy-nums (map inc [1 2 3]))
(realized? lazy-nums)            ; => false
(first lazy-nums)                ; => 2 (and consumes that element)
(realized? lazy-nums)            ; => false
(realized? (doall lazy-nums))    ; => true
```

### Numeric Functions

#### `inc` / `dec`
Increment/decrement by 1.
```clojure
(inc 5)         ; => 6
(inc -1)        ; => 0
(inc 0.5)       ; => 1.5

(dec 5)         ; => 4
(dec 0)         ; => -1
(dec 1.5)       ; => 0.5
```

#### `+` / `-` / `*` / `/`
Arithmetic operations. Support variable number of arguments.
```clojure
; Addition
(+ 5)           ; => 5
(+ 1 2)         ; => 3
(+ 1 2 3 4 5)   ; => 15

; Subtraction
(- 5)           ; => 5 (a single operand is unchanged)
(- 0 5)         ; => -5
(- 10 3)        ; => 7
(- 10 3 2 1)    ; => 4

; Multiplication
(* 5)           ; => 5
(* 2 3)         ; => 6
(* 2 3 4)       ; => 24

; Division
(/ 10 2)        ; => 5.0
(/ 20 2 2)      ; => 5.0
(/ 7 2)         ; => 3.5
```

#### `mod`
Modulus (remainder). Result has same sign as divisor.
```clojure
(mod 10 3)      ; => 1
(mod 11 3)      ; => 2
(mod -10 3)     ; => 2
(mod 10 -3)     ; => -2
```

#### `quot`
Integer floor division, matching Python's `//` semantics.
```clojure
(quot 10 3)     ; => 3
(quot 11 3)     ; => 3
(quot -10 3)    ; => -4
(quot 10 -3)    ; => -4
```

#### `max` / `min`
Return the maximum or minimum of arguments, or of one iterable argument.
```clojure
(max 1 5 3)         ; => 5
(max -1 -5 -3)      ; => -1
(apply max [1 5 3]) ; => 5 (with collection)

(min 1 5 3)         ; => 1
(min -1 -5 -3)      ; => -5
(apply min [1 5 3]) ; => 1
```

#### `abs`
Absolute value.
```clojure
(abs 5)         ; => 5
(abs -5)        ; => 5
(abs 0)         ; => 0
(abs -3.14)     ; => 3.14
```

### Bitwise Operations

Bitwise operations have both verbose names and symbol aliases for a more traditional Lisp feel.

```clojure
; Bitwise OR - bit-or or |
(bit-or 1 2)           ; => 3       (0001 | 0010 = 0011)
(| 5 3)                ; => 7       (0101 | 0011 = 0111)

; Bitwise AND - bit-and or &
(bit-and 7 3)          ; => 3       (0111 & 0011 = 0011)
(& 5 3)                ; => 1       (0101 & 0011 = 0001)

; Bitwise AND NOT (clear bits)
(difference 7 2)       ; => 5       (0111 & ~0010 = 0101)
(difference 15 3)      ; => 12      (1111 & ~0011 = 1100)

; Bitwise XOR - bit-xor or ^
(bit-xor 5 3)          ; => 6       (0101 ^ 0011 = 0110)
(^ 7 7)                ; => 0       (same values = 0)

; Bitwise NOT (complement) - bit-not or ~
(bit-not 0)            ; => -1
(~ -1)                 ; => 0
(~ 5)                  ; => -6

; Left shift - bit-shift-left or <<
(bit-shift-left 1 4)   ; => 16      (1 << 4 = 10000)
(<< 3 2)               ; => 12      (11 << 2 = 1100)

; Right shift - bit-shift-right or >>
(bit-shift-right 16 2) ; => 4       (10000 >> 2 = 100)
(>> 15 2)              ; => 3       (1111 >> 2 = 11)
```

#### Symbol Aliases Summary

| Verbose Name      | Symbol | Description              |
|-------------------|--------|--------------------------|
| `bit-or`          | `\|`   | Bitwise OR               |
| `bit-and`         | `&`    | Bitwise AND              |
| `bit-xor`         | `^`    | Bitwise XOR              |
| `bit-not`         | `~`    | Bitwise NOT (complement) |
| `bit-shift-left`  | `<<`   | Left shift               |
| `bit-shift-right` | `>>`   | Right shift              |

The `difference` function performs numeric AND-NOT and set difference. The symbol operators also work with sets:

```clojure
(def s1 #{1 2 3})
(def s2 #{2 3 4})

(| s1 s2)              ; => #{1 2 3 4}  (union)
(& s1 s2)              ; => #{2 3}      (intersection)
(^ s1 s2)              ; => #{1 4}      (symmetric difference)
```

---

## Reader Macros

Reader macros are special syntax forms that transform input during the reading/parsing phase, before compilation. They provide convenient shorthand for common patterns.

### Core Reader Macros

These are fundamental reader macros used in quoting and metaprogramming:

| Syntax | Expansion | Description |
|--------|-----------|-------------|
| `'form` | `(quote form)` | Returns unevaluated form |
| `` `form `` | `(quasiquote form)` | Template with unquoting |
| `~form` | `(unquote form)` | Evaluate inside quasiquote |
| `~@form` | `(unquote-splicing form)` | Splice list into quasiquote |
| `^expr form` | `(Decorated expr form)` | Metadata/decorators |
| `;comment` | (ignored) | Line comment |

### Extended Reader Macros

#### `#(...)` — Hoisted Lambda

Creates an anonymous function with implicit arguments. Unlike Python's `lambda`, this supports **multiple statements** because the compiler hoists it to a named function.

**Implicit Arguments:**
- `%` or `%1` — first argument
- `%2`, `%3`, ... `%N` — positional arguments  
- `%&` — rest args (variadic)

```clojure
; Single argument
(doall (map #(+ % 1) [1 2 3]))      ; => [2 3 4]

; Multiple arguments
(reduce #(+ %1 %2) [1 2 3 4])       ; => 10

; Rest args
(def sum-all #(apply + %&))
(sum-all 1 2 3 4 5)                 ; => 15

; Works with filter
(doall (filter #(> % 5) [3 6 2 8 1 9])) ; => [6 8 9]

; Multi-statement bodies work because of hoisting
(doall
  (map #(do
          (print "Processing:" %)
          (* % 2))
       [1 2 3]))
```

**How Hoisting Works:**

When you write `#(+ % 1)`, the compiler transforms it into a named function definition and replaces the original location with a reference to that function:

```clojure
; This:
(map #(+ % 1) [1 2 3])

; Becomes approximately:
(def __lambda_1 (fn [%1] (+ %1 1)))
(map __lambda_1 [1 2 3])
```

This allows multi-statement bodies that wouldn't be possible with Python's expression-only lambdas.

---

#### `#[...]` — Slice Literal

A dedicated syntax for Python slices using Spork's space-delimited style. Use `_` for `nil` (omitted bounds).

**Syntax:** `#[start stop step]`

| Pattern | Python Equivalent | Description |
|---------|-------------------|-------------|
| `#[2 5]` | `[2:5]` | From index 2 up to (not including) 5 |
| `#[_ _ -1]` | `[::-1]` | Reverse the sequence |
| `#[0 8 2]` | `[0:8:2]` | Every 2nd item from 0 to 8 |
| `#[5 _]` | `[5:]` | From index 5 to end |
| `#[_ 5]` | `[:5]` | From start to index 5 |

```clojure
(def v [0 1 2 3 4 5 6 7 8 9])

(get v #[2 5])          ; => [2 3 4] - items at indices 2, 3, 4
(get v #[_ _ -1])       ; => [9 8 7 6 5 4 3 2 1 0] - reverse
(get v #[0 8 2])        ; => [0 2 4 6] - every other item
(get v #[5 _])          ; => [5 6 7 8 9] - from index 5 to end

; Works with Python lists too
(def py-list (list [1 2 3 4 5]))
(get py-list #[1 4])    ; => [2, 3, 4]

; String slicing
(get "hello world" #[0 5])  ; => "hello"
```

---

#### `#_` — Discard

Reads and discards the next form completely. The form is parsed but never compiled. Useful for temporarily commenting out code while preserving structure.

```clojure
; Comment out a form without breaking structure
(+ 1 2 #_(print "debug") 3)         ; => 6, nothing printed

; Temporarily disable vector elements
[1 #_2 3 #_4 5]                     ; => [1 3 5]

; Discard complex nested forms
(def x #_(some-expensive-call) 42)
x                                      ; => 42

; Useful for debugging - disable parts of a map
{:name "Alice"
 #_:debug #_true
 :age 30}                           ; => {:name "Alice" :age 30}

; Nested discard markers still consume one following form
(+ 1 #_#_2 3 4)                     ; => 8 (`#_#_2` discards only 2)
```

---

#### `#f"..."` — F-String

Parses the string as a template with embedded Spork expressions inside `{}`. Compiles to Python's native f-string (`ast.JoinedStr`) for zero runtime overhead.

```clojure
(def name "World")
(def greeting #f"Hello, {name}!")   ; => "Hello, World!"

; Expressions are fully evaluated
#f"1 + 1 = {(+ 1 1)}"              ; => "1 + 1 = 2"

; Multiple interpolations
(def a 10)
(def b 20)
#f"{a} + {b} = {(+ a b)}"          ; => "10 + 20 = 30"

; Method calls work
(def s "hello")
#f"Upper: {(.upper s)}"            ; => "Upper: HELLO"

; Nested expressions
(def items [1 2 3])
#f"Count: {(count items)}"         ; => "Count: 3"
```

Embedded forms must be balanced Spork expressions. Literal-brace escaping is not currently part of the documented syntax.

---

#### `#p"..."` — Path Literal

Creates a `pathlib.Path` object directly. Provides a clean syntax for filesystem paths.

```clojure
(def src-path #p"src/main.spork")
(isinstance src-path (type #p"."))  ; => true

; Path operations
(.joinpath #p"base" "subdir" "file.txt")  ; => base/subdir/file.txt
(. #p"a/b/c" parent)                       ; => a/b
(. #p"file.txt" suffix)                    ; => ".txt"
(. #p"file.txt" stem)                      ; => "file"

; Path predicates depend on the current filesystem
(.exists #p"./README.md")
(.is-dir #p"./src")
(.is-file #p"./main.py")

; Reading/writing
(.read-text #p"config.txt")         ; returns file contents as a string
(.write-text #p"out.txt" "content") ; => 7
(.read-text #p"out.txt")             ; => "content"
```

---

#### `#r"..."` — Regex Literal

Creates a compiled regex pattern (`re.Pattern`). The pattern is **validated at compile time**, catching regex syntax errors early.

```clojure
(def pattern #r"\d{3}-\d{4}")
(.group (.search pattern "Call 555-1234") 0) ; => "555-1234"

; Find all matches
(.findall #r"\d+" "a1b22c333")      ; => ["1", "22", "333"]

; With groups
(def m (.search #r"(\w+)@(\w+)" "user@domain"))
(.group m 1)                        ; => "user"
(.group m 2)                        ; => "domain"

; Common patterns
(.sub #r"\s+" " " "too   many   spaces")  ; => "too many spaces"
(.split #r"[,;]" "a,b;c,d")               ; => ["a", "b", "c", "d"]
```

Invalid regular expressions fail during compilation:

<!-- verify-docs: expect-error=SyntaxError -->
```clojure
#r"[invalid"                        ; SyntaxError at compile time!
```

---

#### `#uuid"..."` — UUID Literal

Parses a UUID string into a `uuid.UUID` object. Validated at compile time.

```clojure
(def id #uuid"550e8400-e29b-41d4-a716-446655440000")
(= (type id) (type #uuid"00000000-0000-0000-0000-000000000000")) ; => true
(. id version)                      ; => 4
(. id hex)                          ; => "550e8400e29b41d4a716446655440000"

; Equality works as expected
(= #uuid"550e8400-e29b-41d4-a716-446655440000"
   #uuid"550e8400-e29b-41d4-a716-446655440000")  ; => true

; Different UUID formats compare equal
(= id #uuid"550e8400e29b41d4a716446655440000")       ; => true
(= id #uuid"{550e8400-e29b-41d4-a716-446655440000}") ; => true
```

Invalid UUIDs fail during compilation:

<!-- verify-docs: expect-error=SyntaxError -->
```clojure
#uuid"not-a-uuid"                   ; SyntaxError at compile time!
```

---

#### `#inst"..."` — Instant Literal

Parses an ISO-8601 string into a `datetime.datetime` object. A `Z` suffix or explicit offset produces an aware datetime; a date or time without an offset produces a naive datetime.

```clojure
(def created #inst"2025-12-10T00:00:00Z")
(= (type created) (type #inst"2000-01-01")) ; => true

; Access components
(. created year)                    ; => 2025
(. created month)                   ; => 12
(. created day)                     ; => 10
(str (. created tzinfo))             ; => "UTC"

; With time
(def event #inst"2024-06-15T14:30:45Z")
(. event hour)                      ; => 14
(. event minute)                    ; => 30
(. event second)                    ; => 45

; Timezone offsets, in seconds east or west of UTC
(.total-seconds (.utcoffset #inst"2024-01-01T12:00:00+05:30")) ; => 19800.0
(.total-seconds (.utcoffset #inst"2024-01-01T12:00:00-08:00")) ; => -28800.0

; Date-only (naive midnight)
(str #inst"2024-01-01")             ; => "2024-01-01 00:00:00"
```

Invalid date/time formats fail during compilation:

<!-- verify-docs: expect-error=SyntaxError -->
```clojure
#inst"not-a-date"                   ; SyntaxError at compile time!
```

---

#### `#=` — Read-Time Eval

Evaluates the form **during compilation** and injects the result into the AST. The result must be a valid literal that can be embedded in compiled code.

```clojure
; Compute at compile time
(def computed #=(+ 100 200))        ; compiled as (def computed 300)
computed                               ; => 300

; String operations
(def upper #=(.upper "hello"))      ; compiled as (def upper "HELLO")
upper                                  ; => "HELLO"

; Mathematical constants
(def tau #=(* 2 3.14159265359))     ; computed once at compile time
tau                                    ; => 6.28318530718
```

**Available Environment:**

The expression runs in the compiler's macro execution environment. It includes selected Python builtins, persistent collection constructors, and Spork's core sequence and arithmetic helpers. Ordinary runtime definitions and modules imported by the surrounding `ns` form are not automatically available to `#=`.

**Use Cases:**
- Build-time constants
- Compile-time string processing
- Embedding generated literal values
- Pre-computing expensive constant values

**Caution:** `#=` executes trusted code at compile time. Avoid side effects and environment-dependent values when reproducible builds matter.

---

## Prelude Macros

The prelude is automatically loaded in every Spork namespace. No import required.

### Control Flow

#### `when`
Executes body only if test is truthy. Returns nil if test is falsy.
```clojure
(when (> x 0)
  (print "positive")
  x)

(when true "yes")       ; => "yes"
(when false "yes")      ; => nil
(when nil "yes")        ; => nil

; Multiple expressions in body
(when (valid? data)
  (process data)
  (save data)
  :done)
```

#### `unless`
Executes body only if test is falsy (opposite of when).
```clojure
(unless (empty? coll)
  (first coll))

(unless false "yes")    ; => "yes"
(unless true "yes")     ; => nil

(unless (authenticated? user)
  (redirect "/login"))
```

#### `cond`
Multi-way conditional. Evaluates each test in order, returns corresponding expression for first truthy test.
```clojure
(cond
  (< x 0) "negative"
  (> x 0) "positive"
  :else   "zero")

(defn grade [score]
  (cond
    (>= score 90) "A"
    (>= score 80) "B"
    (>= score 70) "C"
    (>= score 60) "D"
    :else "F"))

(grade 85)  ; => "B"
(grade 55)  ; => "F"
```

### Threading Macros

#### `->`
Thread-first: inserts x as second item (first argument) in each form.
```clojure
(-> 5
    (+ 3)
    (* 2))     ; => 16

(-> {:a 1}
    (assoc :b 2)
    (assoc :c 3))
; => {:a 1 :b 2 :c 3}

(-> [1 2 3]
    (conj 4)
    (conj 5))
; => [1 2 3 4 5]

; Without arrow:
(conj (conj (assoc {:a 1} :b 2) [:c 3]) [:d 4])
; => {:a 1 :b 2 :c 3 :d 4}

; With arrow:
(-> {:a 1}
    (assoc :b 2)
    (conj [:c 3])
    (conj [:d 4]))
; => {:a 1 :b 2 :c 3 :d 4}
```

#### `->>`
Thread-last: inserts x as last item (last argument) in each form.
```clojure
(->> [1 2 3 4 5]
     (filter even?)   ; (filter even? [1 2 3 4 5])
     (map inc)        ; (map inc (filter even? ...))
     (reduce +))      ; (reduce + (map inc ...))
; => 8

(->> (range 10)
     (filter odd?)
     (map #(* % %))
     (take 3))
; => (1 9 25)

; Great for sequence transformations
(->> users
     (filter :active)
     (map :email)
     (take 10))
```

### Utility Macros

#### `comment`
Ignores body. Useful for commenting out code blocks while keeping them syntactically valid.
```clojure
(comment
  (this code is ignored)
  (but remains syntactically valid)
  (useful for REPL experimentation))

(def result 42)
(comment
  ; Old implementation:
  (def result (expensive-calculation)))
```

#### `fmt`
Python-style string formatting with {} placeholders.
```clojure
; Positional
(fmt "Hello, {}!" "World")          ; => "Hello, World!"
(fmt "{} + {} = {}" 1 2 3)          ; => "1 + 2 = 3"

; Indexed
(fmt "{1} before {0}" "B" "A")      ; => "A before B"
(fmt "{0} {0} {0}" "echo")          ; => "echo echo echo"

; Named (using *{} kwargs)
(fmt "Hello {name}!" *{:name "Alice"})
; => "Hello Alice!"

(fmt "{name} is {age} years old" *{:name "Bob" :age 30})
; => "Bob is 30 years old"

; Format specifiers
(fmt "{:.2f}" 3.14159)              ; => "3.14"
(fmt "{:>10}" "hi")                 ; => "        hi"
(fmt "{:<10}" "hi")                 ; => "hi        "
(fmt "{:05d}" 42)                   ; => "00042"
```

#### `assert`
Throws AssertionError if test is false.
```clojure
(assert (> x 0) "x must be positive")
(assert (valid? data))

(defn divide [a b]
  (assert (not (zero? b)) "Cannot divide by zero")
  (/ a b))
```

### Lazy Sequence Macros

#### `mapv`
Eager map that returns a vector.
```clojure
(mapv inc [1 2 3])          ; => [2 3 4]
(mapv str [1 2 3])          ; => ["1" "2" "3"]
```

#### `filterv`
Eager filter that returns a vector.
```clojure
(filterv even? [1 2 3 4 5]) ; => [2 4]
(filterv pos? [-1 0 1 2])   ; => [1 2]
```

#### `doseq`
Execute body for each element (for side effects). Returns nil.
```clojure
(doseq [x [1 2 3]]
  (print x))
; prints each value on its own line: 1, 2, 3

(doseq [item items]
  (process item)
  (save item))
```

#### `for-all`
List comprehension returning a vector.
```clojure
(for-all [x [1 2 3]] (* x x))       ; => [1 4 9]
(for-all [x [1 2 3]] [x (* x 10)])  ; => [[1 10] [2 20] [3 30]]
```

### Function Composition

#### `comp`
Composes single-argument functions right to left.
```clojure
((comp str inc) 5)              ; => "6"
((comp inc inc inc) 0)          ; => 3
((comp first rest) [1 2 3])     ; => 2

(def process (comp str inc abs))
(process -5)                    ; => "6"
```

#### `partial`
Partial function application.
```clojure
((partial + 10) 5)              ; => 15
((partial + 1 2) 3 4)           ; => 10

(def add10 (partial + 10))
(add10 5)                       ; => 15

(def greet (partial + "Hello, "))
(greet "World")                 ; => "Hello, World"
```

#### `identity`
Expands to its argument unchanged.
```clojure
(identity 42)                   ; => 42
(identity nil)                  ; => nil
```

`identity` is a macro, not a first-class function binding. Use `(fn [x] x)` when an identity function must be passed as a value.

#### `constantly`
Returns a function that always returns x, regardless of arguments.
```clojure
((constantly 42) :anything)     ; => 42
((constantly :default) 1 2 3)   ; => :default

(map (constantly 0) [1 2 3])    ; => (0 0 0)
```

#### `complement`
Returns function that returns opposite boolean.
```clojure
((complement even?) 3)          ; => true
((complement even?) 4)          ; => false

(def odd? (complement even?))
(filter (complement (fn [x] (= x nil))) [1 nil 2 nil]) ; => (1 2)
```

### Type Predicates

```clojure
; Nil checks
(nil? nil)          ; => true
(nil? false)        ; => false
(some? nil)         ; => false
(some? false)       ; => true

; Type checks
(string? "hello")   ; => true
(string? 123)       ; => false
(number? 42)        ; => true
(number? 3.14)      ; => true
(int? 42)           ; => true
(int? 3.14)         ; => false
(float? 3.14)       ; => true
(bool? true)        ; => true
(fn? inc)           ; => true

; Symbol/Keyword checks
(symbol? 'foo)      ; => true
(keyword? :foo)     ; => true

; Collection checks
(vector? [1 2 3])   ; => true
(map? {:a 1})       ; => true
(list? '(1 2 3))    ; => true
(seq? (rest [1 2])) ; => true
(coll? [1 2 3])     ; => true
(coll? {:a 1})      ; => true
(dict? (dict [["a" 1]])) ; => true (Python dict)
```

### Collection Predicates and Accessors

```clojure
; Empty check
(empty? [])         ; => true
(empty? [1 2 3])    ; => false
(empty? nil)        ; => true

; Not-empty (returns coll or nil)
(not-empty [1 2])   ; => [1 2]
(not-empty [])      ; => nil

; Accessors
(second [1 2 3])    ; => 2
(ffirst [[1 2] [3 4]])  ; => 1  (first of first)
(last [1 2 3])      ; => 3
(butlast [1 2 3])   ; => (1 2)
```

### Numeric Predicates

```clojure
(even? 4)           ; => true
(even? 3)           ; => false
(odd? 3)            ; => true
(odd? 4)            ; => false
(pos? 5)            ; => true
(pos? 0)            ; => false
(neg? -5)           ; => true
(neg? 0)            ; => false
(zero? 0)           ; => true
(zero? 1)           ; => false
```

### Protocol Definition

#### `defprotocol`
Defines a protocol (interface).
```clojure
(defprotocol Showable
  "Protocol for things that can be shown"
  (show [this] "Returns string representation"))

(defprotocol Measurable
  (length [this])
  (width [this]))
```

#### `extend-type`
Extends a type to implement protocols.
```clojure
(extend-type str
  Showable
  (show [this] (fmt "String: {}" this)))

(extend-type Vector
  Showable
  (show [this] (fmt "Vector with {} elements" (count this)))
  Measurable
  (length [this] (count this)))
```

#### `extend-protocol`
Extends a protocol to multiple types.
```clojure
(extend-protocol Showable
  str
  (show [this] this)
  
  int
  (show [this] (fmt "Number: {}" this))
  
  Vector
  (show [this] (fmt "[{} items]" (count this))))
```

---

## Standard Library Modules

### std.string

String manipulation utilities.

**Usage:** `(ns my-file (:require [std.string :as str]))`

#### `str.join`
Joins collection elements with separator.
```clojure
(str.join ", " ["a" "b" "c"])      ; => "a, b, c"
(str.join "-" ["1" "2" "3"])       ; => "1-2-3"
(str.join "" ["a" "b" "c"])        ; => "abc"
(str.join "\n" ["line1" "line2"])  ; => "line1\nline2"
```

#### `str.split`
Splits string by separator.
```clojure
(str.split "a,b,c" ",")           ; => ["a" "b" "c"]
(str.split "hello world" " ")     ; => ["hello" "world"]
(str.split "a-b-c-d" "-")         ; => ["a" "b" "c" "d"]
```

#### `str.trim` / `str.ltrim` / `str.rtrim`
Removes whitespace.
```clojure
(str.trim "  hello  ")            ; => "hello"
(str.trim "\n\thello\n\t")        ; => "hello"
(str.ltrim "  hello  ")           ; => "hello  "
(str.rtrim "  hello  ")           ; => "  hello"
```

#### `str.upper` / `str.lower`
Case conversion.
```clojure
(str.upper "hello")               ; => "HELLO"
(str.upper "Hello World")         ; => "HELLO WORLD"
(str.lower "HELLO")               ; => "hello"
(str.lower "Hello World")         ; => "hello world"
```

#### `str.capitalize` / `str.title`
Capitalization.
```clojure
(str.capitalize "hello world")    ; => "Hello world"
(str.capitalize "HELLO")          ; => "Hello"
(str.title "hello world")         ; => "Hello World"
(str.title "the quick brown fox") ; => "The Quick Brown Fox"
```

#### `str.starts-with?` / `str.ends-with?`
Prefix/suffix checks.
```clojure
(str.starts-with? "hello" "he")   ; => true
(str.starts-with? "hello" "lo")   ; => false
(str.ends-with? "hello" "lo")     ; => true
(str.ends-with? "hello" "he")     ; => false
```

#### `str.includes?`
Substring check.
```clojure
(str.includes? "hello" "ell")     ; => true
(str.includes? "hello" "xyz")     ; => false
(str.includes? "hello" "")        ; => true
```

#### `str.blank?`
Checks if nil, empty, or whitespace only.
```clojure
(str.blank? nil)                  ; => true
(str.blank? "")                   ; => true
(str.blank? "   ")                ; => true
(str.blank? "\n\t")               ; => true
(str.blank? "hi")                 ; => false
(str.blank? "  hi  ")             ; => false
```

#### `str.replace` / `str.replace-first`
String replacement.
```clojure
(str.replace "abab" "a" "x")      ; => "xbxb"
(str.replace "hello" "l" "L")     ; => "heLLo"
(str.replace-first "abab" "a" "x"); => "xbab"
(str.replace-first "hello" "l" "L") ; => "heLlo"
```

#### `str.reverse`
Reverses a string.
```clojure
(str.reverse "hello")             ; => "olleh"
(str.reverse "abc")               ; => "cba"
(str.reverse "")                  ; => ""
```

#### `str.repeat`
Repeats string n times.
```clojure
(str.repeat "ab" 3)               ; => "ababab"
(str.repeat "-" 10)               ; => "----------"
(str.repeat "x" 0)                ; => ""
```

#### `str.substring-count`
Counts occurrences of substring.
```clojure
(str.substring-count "abab" "ab") ; => 2
(str.substring-count "aaa" "a")   ; => 3
(str.substring-count "hello" "l") ; => 2
(str.substring-count "hello" "x") ; => 0
```

#### `str.index-of` / `str.last-index-of`
Find substring position.
```clojure
(str.index-of "hello" "l")        ; => 2
(str.index-of "hello" "x")        ; => nil
(str.index-of "hello" "lo")       ; => 3
(str.last-index-of "hello" "l")   ; => 3
(str.last-index-of "abcabc" "bc") ; => 4
```

#### `str.substring`
Extract substring (start inclusive, end exclusive).
```clojure
(str.substring "hello" 1 4)       ; => "ell"
(str.substring "hello" 0 2)       ; => "he"
(str.substring "hello" 2 5)       ; => "llo"
```

#### `str.char-at`
Get character at index.
```clojure
(str.char-at "hello" 0)           ; => "h"
(str.char-at "hello" 1)           ; => "e"
(str.char-at "hello" 4)           ; => "o"
```

#### `str.length`
String length.
```clojure
(str.length "hello")              ; => 5
(str.length "")                   ; => 0
(str.length "日本語")              ; => 3
```

#### `str.pad-left` / `str.pad-right` / `str.center`
String padding.
```clojure
(str.pad-left "hi" 5 " ")         ; => "   hi"
(str.pad-left "42" 5 "0")         ; => "00042"
(str.pad-right "hi" 5 " ")        ; => "hi   "
(str.pad-right "hi" 5 ".")        ; => "hi..."
(str.center "hi" 6 "-")           ; => "--hi--"
(str.center "x" 5 " ")            ; => "  x  "
```

#### `str.lines`
Split into lines.
```clojure
(str.lines "a\nb\nc")             ; => ["a" "b" "c"]
(str.lines "line1\nline2\nline3") ; => ["line1" "line2" "line3"]
(str.lines "single")              ; => ["single"]
```

---

### std.map

Map manipulation utilities.

**Usage:** `(ns myfile (:require [std.map :as m]))`

#### `m.keys` / `m.vals`
Get keys or values as vectors.
```clojure
(set (m.keys {:a 1 :b 2 :c 3})) ; => #{:a :b :c}
(set (m.vals {:a 1 :b 2 :c 3})) ; => #{1 2 3}
(m.keys {})                       ; => []
(m.vals {})                       ; => []
```

#### `m.entries`
Get key-value pairs as vector of vectors.
```clojure
(into {} (m.entries {:a 1 :b 2})) ; => {:a 1 :b 2}
(m.entries {:x 10})               ; => [[:x 10]]
```

#### `m.update`
Update value by applying function.
```clojure
(m.update {:a 1} :a inc)          ; => {:a 2}
(m.update {:a 1 :b 2} :b #(* % 10))  ; => {:a 1 :b 20}
(m.update {:count 5} :count dec)  ; => {:count 4}
```

#### `m.update-with`
Update with default if key missing.
```clojure
(m.update-with {:a 1} :a inc 0)   ; => {:a 2}
(m.update-with {:a 1} :b inc 0)   ; => {:a 1 :b 1}
(m.update-with {} :count inc 0)   ; => {:count 1}
```

#### `m.get-in`
Get value from nested map.
```clojure
(m.get-in {:a {:b {:c 1}}} [:a :b :c])  ; => 1
(m.get-in {:a {:b 2}} [:a :b])          ; => 2
(m.get-in {:a 1} [:a])                  ; => 1
(m.get-in {:a {:b 2}} [:a :c])          ; => nil
```

#### `m.get-in-or`
Get-in with a default value. A stored `nil` is treated the same as a missing path.
```clojure
(m.get-in-or {:a {:b 1}} [:a :b] 42)   ; => 1
(m.get-in-or {:a {}} [:a :b] 42)       ; => 42
(m.get-in-or {} [:a :b :c] :missing)   ; => :missing
```

#### `m.assoc-in`
Associate value in nested map, creating intermediate maps as needed.
```clojure
(m.assoc-in {:a {}} [:a :b] 1)         ; => {:a {:b 1}}
(m.assoc-in {} [:a :b :c] 42)          ; => {:a {:b {:c 42}}}
(m.assoc-in {:a {:b 1}} [:a :b] 99)    ; => {:a {:b 99}}
(m.assoc-in {:a {:b 1}} [:a :c] 2)     ; => {:a {:b 1 :c 2}}
```

#### `m.update-in`
Update value in nested map by applying function.
```clojure
(m.update-in {:a {:b 1}} [:a :b] inc)  ; => {:a {:b 2}}
(m.update-in {:a {:b {:c 5}}} [:a :b :c] #(* % 10))  
; => {:a {:b {:c 50}}}
(m.update-in {:stats {:count 0}} [:stats :count] inc)
; => {:stats {:count 1}}
```

#### `m.select-keys`
Select only specified keys from map.
```clojure
(m.select-keys {:a 1 :b 2 :c 3} [:a :c])  ; => {:a 1 :c 3}
(m.select-keys {:a 1 :b 2} [:a :b :c])    ; => {:a 1 :b 2}
(m.select-keys {:a 1 :b 2} [:x :y])       ; => {}
(m.select-keys {:a 1 :b 2} [])            ; => {}
```

#### `m.dissoc-in`
Remove key from nested map.
```clojure
(m.dissoc-in {:a {:b 1 :c 2}} [:a :b])    ; => {:a {:c 2}}
(m.dissoc-in {:a {:b {:c 1}}} [:a :b :c]) ; => {:a {:b {}}}
(m.dissoc-in {:x {:y 1}} [:x :y])         ; => {:x {}}
```

#### `m.merge`
Merge maps (later values override earlier ones).
```clojure
(m.merge {:a 1} {:b 2})               ; => {:a 1 :b 2}
(m.merge {:a 1} {:a 2})               ; => {:a 2}
(m.merge {:a 1} {:b 2} {:c 3})        ; => {:a 1 :b 2 :c 3}
(m.merge {:a 1 :b 1} {:b 2} {:b 3})   ; => {:a 1 :b 3}
(m.merge {:a 1} nil {:b 2})           ; => {:a 1 :b 2}
```

#### `m.merge-with`
Merge using function to combine values for duplicate keys.
```clojure
(m.merge-with + {:a 1} {:a 2})        ; => {:a 3}
(m.merge-with + {:a 1 :b 2} {:a 3 :b 4})  ; => {:a 4 :b 6}
(m.merge-with into {:a [1]} {:a [2]})     ; => {:a [1 2]}
(m.merge-with into {:a #{1}} {:a #{2 3}}) ; => {:a #{1 2 3}}
```

#### `m.rename-keys`
Rename keys according to a mapping.
```clojure
(m.rename-keys {:a 1 :b 2} {:a :x})        ; => {:x 1 :b 2}
(m.rename-keys {:a 1 :b 2} {:a :x :b :y})  ; => {:x 1 :y 2}
(m.rename-keys {:a 1 :b 2} {:c :z})        ; => {:a 1 :b 2}
(m.rename-keys {:old-name "value"} {:old-name :new-name})
; => {:new-name "value"}
```

#### `m.invert`
Swap keys and values.
```clojure
(m.invert {:a 1 :b 2})            ; => {1 :a 2 :b}
(m.invert {:x "hello" :y "world"}) ; => {"hello" :x "world" :y}
(m.invert {1 :a 2 :b})            ; => {:a 1 :b 2}
```

#### `m.map-keys` / `m.map-vals`
Transform keys or values.
```clojure
; Map over keys
(m.map-keys (fn [k] k.name) {:a 1 :b 2}) ; => {"a" 1 "b" 2}
(m.map-keys str {1 :a 2 :b})      ; => {"1" :a "2" :b}
(m.map-keys inc {1 :a 2 :b})      ; => {2 :a 3 :b}

; Map over values
(m.map-vals inc {:a 1 :b 2})      ; => {:a 2 :b 3}
(m.map-vals str {:a 1 :b 2})      ; => {:a "1" :b "2"}
(m.map-vals count {:a [1 2] :b [1 2 3]})  ; => {:a 2 :b 3}
```

#### `m.filter-keys` / `m.filter-vals`
Filter by predicate on keys or values.
```clojure
; Filter by keys
(m.filter-keys #(isinstance % Keyword) {:a 1 "b" 2}) ; => {:a 1}
(m.filter-keys #(= :a %) {:a 1 :b 2})     ; => {:a 1}

; Filter by values
(m.filter-vals even? {:a 1 :b 2 :c 3 :d 4})  ; => {:b 2 :d 4}
(m.filter-vals pos? {:a -1 :b 0 :c 1 :d 2})  ; => {:c 1 :d 2}
(m.filter-vals #(not (= % nil)) {:a 1 :b nil :c 2}) ; => {:a 1 :c 2}
```

#### `m.deep-merge`
Recursively merge nested maps.
```clojure
(m.deep-merge {:a {:b 1}} {:a {:c 2}})     
; => {:a {:b 1 :c 2}}

(m.deep-merge {:a {:b {:c 1}}} {:a {:b {:d 2}}})
; => {:a {:b {:c 1 :d 2}}}

(m.deep-merge {:a {:x 1}} {:a {:x 2}})     
; => {:a {:x 2}}  (non-map values are overwritten)

(m.deep-merge {:config {:debug false :port 8080}}
              {:config {:debug true}})
; => {:config {:debug true :port 8080}}
```

---

### std.json

JSON serialization and parsing with automatic conversion for Spork values.

**Usage:** `(ns my-file (:require [std.json :as json]))`

#### Encoding

`json.dumps` returns compact JSON. `json.dumps-pretty` uses an indentation level of two. `json.generate` is an alias for `json.dumps`.

```clojure
(def encoded (json.dumps {:name "Spork" :items [1 2 3]}))
; typical encoded value: "{\"name\": \"Spork\", \"items\": [1, 2, 3]}"
; JSON object key order follows the map's unspecified iteration order
(json.loads encoded true) ; => {:name "Spork" :items [1 2 3]}

(json.dumps-pretty {:ready true})
; => "{\n  \"ready\": true\n}"

(json.generate {:status "ok"})
; => "{\"status\": \"ok\"}"
```

The encoder converts values recursively:

| Spork value | JSON representation |
| --- | --- |
| `Map` | object; keyword and symbol keys become strings |
| `Vector`, `DoubleVector`, `IntVector`, `SortedVector` | array |
| `Set` | array; order is unspecified |
| `Cons` | array |
| keyword used as a value | string with a leading `:` |
| symbol used as a value | string |

`json.dump` and `json.dump-pretty` write to a file-like object:

```clojure
(with [out (open "data.json" "w")]
  (json.dump-pretty {:name "Spork" :ready true} out))

(json.loads (.read-text #p"data.json") true)
; => {:name "Spork" :ready true}
```

#### Decoding

`json.loads` parses a string and recursively converts JSON objects to persistent `Map` values and arrays to persistent `Vector` values. `json.parse` is an alias for `json.loads`.

```clojure
(def data (json.loads "{\"name\": \"Spork\", \"items\": [1, 2]}"))
(get data "name")             ; => "Spork"
(get data "items")            ; => [1 2]

; Pass true to convert object keys to keywords at every nesting level
(def keyed (json.loads "{\"ready\": true}" true))
(:ready keyed)                 ; => true

(json.parse "[1, 2, 3]")      ; => [1 2 3]
```

`json.load` reads from a file-like object and accepts the same optional keywordization flag:

```clojure
(with [in (open "data.json" "r")]
  (json.load in true))
; => {:ready true}
```

JSON has no set or keyword type, so those distinctions do not round-trip automatically. Invalid JSON and unsupported encoded values raise the corresponding Python `json` exceptions.

---

## Related Language Features

The following topics are language behavior rather than standard-library APIs and are documented in the [Language Reference](LANG.md):

- [protocol definitions and extension](LANG.md#9-protocols);
- [namespaces, `:require`, and Python `:import`](LANG.md#10-namespaces--modules);
- [keyword arguments and attribute access](LANG.md#15-python-interop);
- [exceptions](LANG.md#13-exception-handling);
- [async functions and generators](LANG.md#12-async--generators).

### Common Python builtins

Python builtins remain accessible unless a Spork runtime binding overrides the same name. Notably, `map` and `filter` below are Spork's lazy helpers, while constructors such as `list`, `dict`, and `set` create Python built-in collections.

```clojure
(print "hello" "world")
(len [1 2 3])                 ; => 3
(= (type obj) SomeClass)      ; => true
(str 42)                      ; => "42"
(int "42")                    ; => 42
(float "3.14")                ; => 3.14
(list (range 5))              ; => [0, 1, 2, 3, 4]
(dict [[:a 1] [:b 2]])        ; => {:a 1 :b 2}
(set [1 2 2 3])               ; => #{1 2 3}
(sorted [3 1 2])              ; => [1, 2, 3]
(list (reversed [1 2 3]))     ; => [3 2 1]
(list (enumerate ["a" "b" "c"])) ; => ([0 "a"] [1 "b"] [2 "c"])
(list (zip [1 2] ["a" "b"])) ; => ([1 "a"] [2 "b"])
(doall (map inc [1 2 3]))      ; => [2 3 4]
(doall (filter even? [1 2 3 4])) ; => [2 4]
(any [false false true])      ; => True
(all [true true true])        ; => True
(sum [1 2 3 4])               ; => 10
(min 1 2 3)                   ; => 1
(max 1 2 3)                   ; => 3
(abs -5)                      ; => 5
(round 3.7)                   ; => 4
(callable inc)                ; => True
(hasattr obj "method")        ; => true
(getattr obj "attr" default)  ; => 1
(setattr obj "attr" 42)       ; Set attribute
(getattr obj "attr")          ; => 42
```
