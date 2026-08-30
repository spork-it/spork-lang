# Spork Standard Library Reference

This reference covers the values and functions available in every Spork namespace, the automatically loaded prelude macros, reader syntax, and the Python-backed `std.*` modules provided by `spork-runtime`.

For version information, related references, and shared conventions, see the [documentation index](README.md).

## Table of Contents

1. [Built-in Types](#built-in-types)
2. [Core Functions](#core-functions)
   - [Sequence operations](#sequence-operations)
   - [Transient operations](#transient-operations)
   - [Lazy sequences](#lazy-sequence-functions)
   - [Sequence predicates](#predicates-on-sequences)
   - [Reductions](#reduction-functions)
   - [Collection transformations](#collection-transformations)
   - [Sequence realization](#sequence-realization)
   - [Numeric functions](#numeric-functions)
   - [Bitwise operations](#bitwise-operations)
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
(nth [1 2] 5 :default) ; => :default
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
(get {:a 1} :b 42)       ; => 42
(:a {:a 1})              ; => 1
(:missing {:a 1} "nope") ; => "nope"
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
(| #{1 2} #{2 3})      ; => #{1 2 3}
(& #{1 2} #{2 3})      ; => #{2}
(- #{1 2 3} #{2})      ; => #{1 3}
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

Interned named values that evaluate to themselves and begin with `:`. Keywords are also callable for map lookup.

```clojure
; Keywords as values
:my-keyword                      ; a keyword
:namespaced.keyword              ; with namespace

; Keywords as functions (map lookup)
(:name {:name "Alice" :age 30})  ; => "Alice"
(:missing {:name "Alice"})       ; => nil
(:missing {:name "Alice"} "default")  ; => "default"

; A keyword can therefore extract the same key from several maps
(map :name [{:name "Alice"} {:name "Bob"}]) ; => ("Alice" "Bob")
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

; A key function sorts by a derived value (string length here)
(sorted-vec ["banana" "apple" "cherry"] *{:key len})
; => sorted_vec("apple", "banana", "cherry")

; A keyword is callable and can be the key for map-like values
(sorted-vec [{:name "Bob" :age 25} {:name "Alice" :age 30}] *{:key :age})
; => sorted_vec({:name "Bob" :age 25}, {:name "Alice" :age 30})

; Reverse order
(sorted-vec [3 1 4] *{:reverse true}) ; => sorted_vec(4, 3, 1)

; Combine a key and reverse ordering
(def score-items
  [{:name "one" :score 10} {:name "two" :score 20}])
(def ranked (sorted-vec score-items *{:key :score :reverse true}))
(isinstance ranked SortedVector) ; => true
(vec ranked)
; => [{:name "two" :score 20} {:name "one" :score 10}]
```

**Basic Operations:**
```clojure
(def sv (sorted-vec [5 2 8 1 9]))

(count sv)           ; => 5
(first sv)           ; => 1
(last sv)            ; => 9
(nth sv 2)           ; => 5
(nth sv 10 :default) ; => :default
(get sv 0)           ; => 1
(get sv -1)          ; => 9
```

**Adding and Removing Elements:**

`conj` inserts in configured sorted position and retains duplicates. `disj` removes one matching occurrence and is a no-op when the value is absent.

```clojure
(def sv (sorted-vec [1 3 5]))

(conj sv 2)          ; => sorted_vec(1, 2, 3, 5)
(conj sv 3)          ; => sorted_vec(1, 3, 3, 5)
(disj sv 3)          ; => sorted_vec(1, 5)
(disj sv 99)         ; => sorted_vec(1, 3, 5)
```

**Search Operations:**

`index-of` (Python: `index_of`) returns the index of an equal value or `-1`. `rank` returns the insertion index under the vector's configured ordering.

```clojure
(def sv (sorted-vec [10 20 30 40 50]))

(contains? sv 30)    ; => true
(contains? sv 25)    ; => false
(sv.index-of 30)    ; => 2
(sv.index-of 25)    ; => -1
(sv.rank 25)        ; => 2
(sv.rank 100)       ; => 5
```

**Iteration:**
```clojure
; Iterates in sorted order for effects
(doseq [x (sorted-vec [3 1 4 1 5])]
  (print x))
; prints one value per line: 1, 1, 3, 4, 5

; Convert to vector
(vec (sorted-vec [3 1 4]))  ; => [1 3 4]
```

**Sorted Iteration Expression:**

`sorted-for` is an eager language expression rather than a library function. See [Sorted For Expression](LANG.md#sorted-for-expression) in the Language Reference.

**Transient Operations:**

Sorted-vector transients preserve key and reverse settings. Their mutation API is documented under [SortedVector Transient Operations](#sortedvector-transient-operations).

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
Returns the first element of a collection, or `nil` if empty. On a one-shot Python iterator, retrieving the first element consumes it.
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
Returns the element at zero-based index `n`. An out-of-range access raises `IndexError` unless a default is provided. Use nonnegative indices for portable behavior; indexable collection types may additionally support Python-style negative indices.
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
Adds one value and returns a new collection. The position depends on the type: the end for vectors, sorted position for sorted vectors, the front for `Cons` lists, set membership for sets, and key association for a map entry. On `nil`, it creates a one-element `Cons`. As a Python fallback, an append-capable input is copied into a new Python `list` before the value is appended.
```clojure
; Vectors add at end
(conj [1 2] 3)           ; => [1 2 3]

; Lists add at front
(conj '(1 2) 0)          ; => (0 1 2)

; Sets add element
(conj #{1 2} 3)          ; => #{1 2 3}
(conj #{1 2} 2)          ; => #{1 2}

; Maps add entry
(conj {:a 1} [:b 2])     ; => {:a 1 :b 2}
```

#### `assoc`
Associates a key with a value in a persistent map, vector, or Python `dict`, returning a new collection. Associating a non-integer key into `nil` creates a persistent map.
```clojure
; Maps
(assoc {:a 1} :b 2)           ; => {:a 1 :b 2}
(assoc {:a 1} :a 99)          ; => {:a 99}

; Vectors (by index)
(assoc [1 2 3] 1 42)          ; => [1 42 3]
(assoc [1 2 3] 0 :first)      ; => [:first 2 3]
```

#### `dissoc`
Removes a key from a persistent map or Python `dict`, returning a new collection. A missing key is a no-op, and `nil` remains `nil`.
```clojure
(dissoc {:a 1 :b 2} :a)       ; => {:b 2}
(dissoc {:a 1 :b 2} :c)       ; => {:a 1 :b 2}
```

#### `disj`
Removes an element from a persistent or Python set, or one matching occurrence from a `SortedVector`, returning a new collection. If the value is absent, the original value is returned unchanged; `nil` remains `nil`.
```clojure
(disj #{1 2 3} 2)        ; => #{1 3}
(disj #{1 2 3} 5)        ; => #{1 2 3}

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
For maps it checks keys, for sets and sorted vectors it checks values, and for vectors, Python lists, and tuples it checks whether a nonnegative integer index exists. Other iterable types use Python membership.
```clojure
; Maps (checks keys)
(contains? {:a 1 :b 2} :a)   ; => true
(contains? {:a 1 :b 2} :c)   ; => false

; Sets (checks elements)
(contains? #{1 2 3} 2)       ; => true
(contains? #{1 2 3} 5)       ; => false

; Vectors check an index, not a stored value
(contains? [1 2 3] 0)        ; => true
(contains? [1 2 3] 2)        ; => true
(contains? [1 2 3] 5)        ; => false
```

#### `empty`
Returns an empty value for persistent `Vector`, `Map`, `Set`, `SortedVector`, and `Cons` collections and for Python `list`, `dict`, and `set`. Unsupported inputs, including strings and typed vectors, return `nil`. A `SortedVector` result uses default ascending ordering rather than preserving custom key or reverse settings.
```clojure
(empty [1 2 3])         ; => []
(empty {:a 1 :b 2})     ; => {}
(empty #{1 2 3})        ; => #{}
(empty '(1 2 3))        ; => nil
```

#### `into`
Adds every input element to a supported persistent destination: a vector, map, set, sorted vector, `Cons` list, or `nil`. This is useful for conversion and batch construction.
```clojure
; Convert list to vector
(into [] '(1 2 3))           ; => [1 2 3]

; Convert vector to set
(into #{} [1 2 2 3 3 3])     ; => #{1 2 3}

; Build map from pairs
(into {} [[:a 1] [:b 2]])    ; => {:a 1 :b 2}

; Add to an existing collection
(into [0] [1 2 3])           ; => [0 1 2 3]

; A list destination receives each new item at the front
(into '(0) [1 2 3])          ; => (3 2 1 0)

; Realize a lazy transformation into a chosen collection
(into [] (map inc [1 2 3]))   ; => [2 3 4]
```

### Transient Operations

Transients are mutable builders initialized from persistent collections. Operations ending in `!` mutate a transient in place; do not apply them to persistent collections. Convert the builder back with `persistent!` when the batch is complete.

#### `transient`
Creates a mutable builder from a persistent `Vector`, `DoubleVector`, `IntVector`, `Map`, `Set`, or `SortedVector`.
```clojure
(def tv (transient [1 2 3]))
(def tm (transient {:a 1}))
(def ts (transient #{1 2}))
```

#### `persistent!`
Converts a transient back to a persistent collection and invalidates the transient. Later access to the transient raises `RuntimeError`.
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
Mutates a transient by adding one value and returns that transient. A transient map requires a two-item key/value pair.
```clojure
(def tv (transient []))
(conj! tv 1)
(conj! tv 2)
(persistent! tv)  ; => [1 2]
```

#### `assoc!`
Associates a key in a `TransientMap` or an index in a general `TransientVector` and returns the transient. Vector indices may be negative. Typed-vector and sorted-vector transients do not support this operation.
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
Removes a value from a transient set or sorted vector.
```clojure
(def ts (transient #{1 2 3 4}))
(disj! ts 2)
(disj! ts 4)
(persistent! ts)  ; => #{1 3}
```

#### `pop!`
Removes the final element from a general `TransientVector`. Typed-vector and sorted-vector transients do not support this operation.
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

; Add elements while maintaining sorted order
(conj! tsv 2)
(conj! tsv 4)
(conj! tsv 6)

; Remove one matching value; an absent value is a no-op
(disj! tsv 3)
(disj! tsv 99)

; Convert back to persistent
(def result (persistent! tsv))  ; => sorted_vec(1, 2, 4, 5, 6, 7)

; A transient preserves its source's key function and reverse ordering
(def tsv
  (transient
    (sorted-vec [{:score 10} {:score 20}]
                *{:key :score :reverse true})))
(conj! tsv {:score 15})
(vec (persistent! tsv))
; => [{:score 20} {:score 15} {:score 10}]
```

#### `with-mutable`
Binds a transient initialized from the supplied collection, executes the body, and returns that transient's persistent result. The body's own result is ignored. This macro is the shortest form for a scoped batch of mutations.

```clojure
(with-mutable [v [10 20]]
  (conj! v 30)
  :ignored-body-result)
; => [10 20 30]
```

**Python-style Mutable APIs:**

Transient maps, vectors, and sets are registered with Python's mutable collection ABCs:

- `TransientMap` passes `isinstance` checks for `MutableMapping`
- `TransientVector` passes `isinstance` checks for `MutableSequence`
- `TransientSet` passes `isinstance` checks for `MutableSet`

ABC registration enables type checks but does not supply every Python mixin method: for example, transient vectors have no `.insert`, and transient maps have no `.update`. They can be passed to Python code that relies only on supported operations. Typed-vector and sorted-vector transients have smaller, type-specific APIs.

```clojure
; TransientVector supports .append, .extend, indexing, and iteration
(with-mutable [v []]
  (v.extend [1 2 3])
  (v.append 4))
; => [1 2 3 4]

; TransientMap supports .get, .keys, .values, .items, and iteration
(with-mutable [m {}]
  (assoc! m :a 1)
  (assert (= (m.get :a) 1)))
; => {:a 1}

; TransientSet supports .add, .discard, .remove, .clear, and iteration
(with-mutable [s #{}]
  (s.add 1)
  (s.add 2)
  (s.discard 1))
; => #{2}
```

For example, Python's `random.shuffle` mutates a transient vector through the mutable-sequence protocol, and `with-mutable` retains the mutation in its persistent result:

```clojure
(ns example.shuffle
  (:import [random :refer [shuffle]]))

(def shuffled
  (with-mutable [v [1 2 3 4]]
    (shuffle v)))

; The order is random, but the persistent result contains the same values
(vec (sorted shuffled)) ; => [1 2 3 4]
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

These functions return Python generators unless a section states otherwise. Calling a generator function does not realize its result; use `vec`, `doall`, iteration, or a reducer to consume it. `cycle`, `partition`, `partition-all`, and `reverse` materialize their input when first consumed and therefore are not suitable for infinite inputs. `sort` and related helpers also realize their inputs but return concrete values.

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
(take 10 [1 2 3])          ; => (1 2 3)
(take 0 [1 2 3])           ; => ()
(take 5 (range))           ; => (0 1 2 3 4)
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
(take 4 (repeat :a))        ; => (:a :a :a :a)
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
(take 5 (range))     ; => (0 1 2 3 4)
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
Returns groups of `n` elements. The default step is `n`, and an incomplete final group is dropped. Optional `step` and `pad` arguments follow the collection; padding is emitted only if `pad` supplies enough values to complete the group.
```clojure
(partition 2 [1 2 3 4 5 6])       ; => ([1 2] [3 4] [5 6])
(partition 2 [1 2 3 4 5])         ; => ([1 2] [3 4])
(partition 3 [1 2 3 4 5 6 7 8 9]) ; => ([1 2 3] [4 5 6] [7 8 9])

; A smaller step creates sliding windows
(partition 2 [1 2 3 4] 1)         ; => ([1 2] [2 3] [3 4])
(partition 3 [1 2 3 4 5] 1)       ; => ([1 2 3] [2 3 4] [3 4 5])

; A fourth argument supplies padding for the final group
(partition 3 [1 2 3 4] 3 [0 0])   ; => ([1 2 3] [4 0 0])
```

#### `partition-all`
Like `partition`, but includes every incomplete group and does not take a padding argument.
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
; => (:a :c :e)

(keep-indexed #(if (> %1 1) %2) [:a :b :c :d])
; => (:c :d)
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
(dedupe [1 2 3 4])           ; => (1 2 3 4)
(dedupe [:a :a :a :b :b :a]) ; => (:a :b :a)
```

#### `distinct`
Removes duplicate hashable values, preserving their first occurrence. Unhashable Python objects are compared by identity rather than equality.
```clojure
(distinct [1 2 1 3 2 4 3])   ; => (1 2 3 4)
(distinct [:a :b :a :c :b])  ; => (:a :b :c)
(distinct "abracadabra")     ; => ("a" "b" "r" "c" "d")
```

#### `flatten`
Recursively flattens any nested iterable except strings and bytes. Maps therefore contribute keys through their normal iteration protocol.
```clojure
(flatten [[1 2] [3 4]])              ; => (1 2 3 4)
(flatten [[1 [2 3]] [[4] 5]])        ; => (1 2 3 4 5)
(flatten [1 [2 [3 [4 [5]]]]])        ; => (1 2 3 4 5)
(flatten [1 2 3])                    ; => (1 2 3)
```

#### `mapcat`
Maps over one or more collections and concatenates each non-`nil` result. It is equivalent to applying `concat` to the results of `map`.
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
Returns true if the predicate is falsy for at least one item. It returns false for an empty input.
```clojure
(not-every even? [2 4 6 8])     ; => false
(not-every even? [2 4 5 6])     ; => true
(not-every pos? [1 -1 2])       ; => true
(not-every even? [])             ; => false
```

#### `not-any`
Returns true if the predicate is falsy for every item, including when the input is empty.
```clojure
(not-any even? [1 3 5 7])       ; => true
(not-any even? [1 3 4 5])       ; => false
(not-any neg? [1 2 3])          ; => true
(not-any #(isinstance % str) [1 2 3]) ; => true
(not-any even? [])                   ; => true
```

### Reduction Functions

#### `reduce`
Reduces a collection using a function. Without an explicit initial value, the first element becomes the accumulator. For an empty collection with no initial value, `reduce` calls the reducing function with zero arguments.
```clojure
; Sum
(reduce + [1 2 3 4])             ; => 10
(reduce + 0 [1 2 3 4])           ; => 10
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

; The zero-argument identity of `+` is used for an empty collection
(reduce + [])                     ; => 0
```

#### `reductions`
Returns a lazy sequence of intermediate accumulator values. An explicit initial value appears first; an empty collection without one produces an empty sequence.
```clojure
(reductions + [1 2 3 4])         ; => (1 3 6 10)
(reductions + 0 [1 2 3 4])       ; => (0 1 3 6 10)
(reductions #(* %1 %2) [1 2 3 4]) ; => (1 2 6 24)
(reductions conj [] [1 2 3])     ; => ([] [1] [1 2] [1 2 3])
```

### Collection Transformations

#### `zipmap`
Creates a map from parallel key and value sequences, stopping when either input is exhausted.
```clojure
(zipmap [:a :b :c] [1 2 3])      ; => {:a 1 :b 2 :c 3}
(zipmap [1 2 3] [:a :b :c])      ; => {1 :a 2 :b 3 :c}
(zipmap [:a :b] [1 2 3])         ; => {:a 1 :b 2}

; Create lookup from list
(zipmap (range) ["a" "b" "c"])   ; => {0 "a" 1 "b" 2 "c"}
```

#### `group-by`
Groups elements by each hashable result of `f`, returning vectors in encounter order.
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
Returns a map from each hashable input value to its count.
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
Realizes its input and returns a stably sorted `Vector`. Optional Python-style `:key` and `:reverse-order` keyword arguments control ordering.
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
Realizes the input and returns a Python tuple containing two vectors. Negative `n` values use Python slicing semantics.
```clojure
(split-at 2 [1 2 3 4 5])         ; => ([1 2], [3 4 5])
(split-at 0 [1 2 3])             ; => ([], [1 2 3])
(split-at 10 [1 2 3])            ; => ([1 2 3], [])
```

#### `split-with`
Realizes the input and returns a Python tuple of two vectors, split at the first falsy predicate result.
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
Consumes an iterable and returns `nil`. Unlike `doall`, it does not retain the yielded values.
```clojure
(dorun (map print [1 2 3]))      ; => nil
; also prints each value on its own line
```

#### `realized?`
Distinguishes raw Python generator objects from concrete or sequence values. It returns false for a generator even after that generator has been partly or fully consumed; it does not track realization progress.
```clojure
(def lazy-nums (map inc [1 2 3]))
(realized? lazy-nums)            ; => false
(first lazy-nums)                ; => 2
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
Direct arithmetic operator forms accept one or more operands. With one operand, each direct form returns it unchanged; with several, evaluation proceeds from left to right. When `-` or `/` is passed as a first-class runtime callable, its one-argument behavior is unary negation or reciprocal instead.
```clojure
; Addition
(+ 5)           ; => 5
(+ 1 2)         ; => 3
(+ 1 2 3 4 5)   ; => 15

; Subtraction
(- 5)           ; => 5
(- 0 5)         ; => -5
(- 10 3)        ; => 7
(- 10 3 2 1)    ; => 4

; Multiplication
(* 5)           ; => 5
(* 2 3)         ; => 6
(* 2 3 4)       ; => 24

; Division
(/ 5)           ; => 5
(/ 10 2)        ; => 5.0
(/ 20 2 2)      ; => 5.0
(/ 7 2)         ; => 3.5

; First-class runtime callables retain conventional unary behavior
(apply - [5])   ; => -5
(apply / [5])   ; => 0.2
```

#### `mod`
Modulus (remainder), also spelled `%` in operator position. The result has the same sign as the divisor.
```clojure
(mod 10 3)      ; => 1
(mod 11 3)      ; => 2
(mod -10 3)     ; => 2
(mod 10 -3)     ; => -2
```

#### `quot`
Integer floor division, equivalent to the `//` operator and matching Python's negative-number semantics.
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
(max [1 5 3])       ; => 5

(min 1 5 3)         ; => 1
(min -1 -5 -3)      ; => -5
(min [1 5 3])       ; => 1
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

Bitwise operations have verbose names and symbol aliases. The same functions also implement persistent set operations; `bit-or`/`|` additionally merge maps, with later values winning.

```clojure
; Bitwise OR - bit-or or |
(bit-or 1 2)           ; => 3
(| 5 3)                ; => 7

; Bitwise AND - bit-and or &
(bit-and 7 3)          ; => 3
(& 5 3)                ; => 1

; Bitwise AND NOT (clear bits)
(difference 7 2)       ; => 5
(difference 15 3)      ; => 12

; Bitwise XOR - bit-xor or ^
(bit-xor 5 3)          ; => 6
(^ 7 7)                ; => 0

; Bitwise NOT (complement) - bit-not or ~
(bit-not 0)            ; => -1
(~ -1)                 ; => 0
(~ 5)                  ; => -6

; Left shift - bit-shift-left or <<
(bit-shift-left 1 4)   ; => 16
(<< 3 2)               ; => 12

; Right shift - bit-shift-right or >>
(bit-shift-right 16 2) ; => 4
(>> 15 2)              ; => 3
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

`union`, `intersection`, and `difference` are aliases for `bit-or`, `bit-and`, and numeric AND-NOT respectively. For sets, `difference` performs set difference. The symbol operators also work with sets and maps:

```clojure
(def s1 #{1 2 3})
(def s2 #{2 3 4})

(| s1 s2)              ; => #{1 2 3 4}
(& s1 s2)              ; => #{2 3}
(^ s1 s2)              ; => #{1 4}

; Map union keeps the rightmost value for a duplicate key
(| {:a 1} {:a 2 :b 3}) ; => {:a 2 :b 3}
```

---

## Reader Macros

Reader macros are special syntax forms that transform input during the reading/parsing phase, before compilation. They provide convenient shorthand for common patterns.

### Core Reader Macros

Quote, quasiquote, unquote, decoration metadata, and comments are core language syntax. See [Core Reader Macros](LANG.md#core-reader-macros) in the Language Reference.

### Extended Reader Macros

#### `#(...)` — Anonymous Function

`#(...)` and its `%` placeholders are function syntax, so their semantics and examples live under [Anonymous Functions](LANG.md#anonymous-functions) in the Language Reference.

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

(get v #[2 5])          ; => [2 3 4]
(get v #[_ _ -1])       ; => [9 8 7 6 5 4 3 2 1 0]
(get v #[0 8 2])        ; => [0 2 4 6]
(get v #[5 _])          ; => [5 6 7 8 9]

; Slicing a Python list returns another Python list
(def py-slice (get (list [1 2 3 4 5]) #[1 4]))
(isinstance py-slice list) ; => true
(vec py-slice)             ; => [2 3 4]

; String slicing
(get "hello world" #[0 5])  ; => "hello"
```

---

#### `#_` — Discard

Reads and discards the next form completely. The form is parsed but never compiled. Useful for temporarily commenting out code while preserving structure.

```clojure
; The discarded call is not compiled or executed
(+ 1 2 #_(print "debug") 3)         ; => 6

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
(+ 1 #_#_2 3 4)                     ; => 8
```

---

#### `#f"..."` — F-String

Parses a string template containing Spork expressions inside `{}` and compiles it as a Python f-string.

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
#f"Upper: {(s.upper)}"             ; => "Upper: HELLO"

; Nested expressions
(def items [1 2 3])
#f"Count: {(count items)}"         ; => "Count: 3"
```

Embedded forms must be balanced Spork expressions. Literal-brace escaping is not currently part of the documented syntax.

---

#### `#p"..."` — Path Literal

Creates a `pathlib.Path` object directly. All normal `Path` attributes and methods remain available.

```clojure
(def src-path #p"src/main.spork")
(isinstance src-path (type #p"."))  ; => true

; Path operations
(def base-path #p"base")
(str (base-path.joinpath "subdir" "file.txt"))
; => "base/subdir/file.txt"
(def nested-path #p"a/b/c")
(str nested-path.parent)                    ; => "a/b"
src-path.suffix                             ; => ".spork"
src-path.stem                               ; => "main"

; Path predicates depend on the current filesystem
(def project-root #p".")
(project-root.exists)
(project-root.is-dir)
(src-path.is-file)

; Path methods work normally
(def out-path #p"out.txt")
(out-path.write-text "content")     ; => 7
(out-path.read-text)                 ; => "content"
```

---

#### `#r"..."` — Regex Literal

Creates a compiled regex pattern (`re.Pattern`). The pattern is **validated at compile time**, catching regex syntax errors early.

```clojure
(def pattern #r"\d{3}-\d{4}")
(def phone-match (pattern.search "Call 555-1234"))
(phone-match.group 0)                       ; => "555-1234"

; Python regex methods return Python lists; convert when a vector is wanted
(def digits #r"\d+")
(vec (digits.findall "a1b22c333"))          ; => ["1" "22" "333"]

; With groups
(def email-pattern #r"(\w+)@(\w+)")
(def m (email-pattern.search "user@domain"))
(m.group 1)                                 ; => "user"
(m.group 2)                                 ; => "domain"

; Common patterns
(def whitespace #r"\s+")
(whitespace.sub " " "too   many   spaces") ; => "too many spaces"
(def separators #r"[,;]")
(vec (separators.split "a,b;c,d"))           ; => ["a" "b" "c" "d"]
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
id.version                          ; => 4
id.hex                              ; => "550e8400e29b41d4a716446655440000"

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
created.year                        ; => 2025
created.month                       ; => 12
created.day                         ; => 10
(str created.tzinfo)                ; => "UTC"

; With time
(def event #inst"2024-06-15T14:30:45Z")
event.hour                          ; => 14
event.minute                        ; => 30
event.second                        ; => 45

; Timezone offsets, in seconds east or west of UTC
(def east #inst"2024-01-01T12:00:00+05:30")
(def west #inst"2024-01-01T12:00:00-08:00")
(def east-offset (east.utcoffset))
(def west-offset (west.utcoffset))
(east-offset.total-seconds)         ; => 19800.0
(west-offset.total-seconds)         ; => -28800.0

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

Evaluates the form during compilation and embeds the result in generated code. The result must be a supported literal value.

```clojure
(def computed #=(+ 100 200))
computed                            ; => 300

(def upper #=(.upper "hello"))
upper                               ; => "HELLO"

(def tau #=(* 2 3.14159265359))
tau                                 ; => 6.28318530718
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

The prelude supplies `when`, `unless`, and `cond`, while their evaluation semantics and examples live in [Control Flow](LANG.md#4-control-flow) in the Language Reference:

| Macro | Behavior |
|-------|----------|
| `when` | Evaluate its body when the test is truthy; otherwise return `nil` |
| `unless` | Evaluate its body when the test is falsy; otherwise return `nil` |
| `cond` | Return the result for the first truthy test, or `nil` when none matches |

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

; Sequence transformations commonly use thread-last
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
Raises `AssertionError` when the test is falsy. An optional second form supplies the exception message.
```clojure
(assert (> x 0) "x must be positive")
(assert (valid? data))

(defn withdraw [balance amount]
  (assert (<= amount balance) "Insufficient balance")
  (- balance amount))
```

### Collection Iteration Macros

#### `mapv`
Applies a function to one collection eagerly and returns a vector.
```clojure
(mapv inc [1 2 3])          ; => [2 3 4]
(mapv str [1 2 3])          ; => ["1" "2" "3"]
```

#### `filterv`
Filters one collection eagerly and returns a vector.
```clojure
(filterv even? [1 2 3 4 5]) ; => [2 4]
(filterv pos? [-1 0 1 2])   ; => [1 2]
```

#### `doseq`
Executes the body for each value from one binding pair and returns `nil`. Use it when only side effects are needed.
```clojure
(doseq [x [1 2 3]]
  (print x))
; prints each value on its own line: 1, 2, 3

(doseq [item items]
  (process item)
  (save item))
```

### Function Composition

#### `comp`
Composes single-argument functions from right to left. With no functions it returns an identity function; with one, it returns that function.
```clojure
((comp) 5)                      ; => 5
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
Returns a function that ignores its arguments and evaluates the supplied form as its result. Because `constantly` is a macro, a non-literal result form is evaluated on every call rather than when the function is created.
```clojure
((constantly 42) :anything)     ; => 42
((constantly :default) 1 2 3)   ; => :default

(map (constantly 0) [1 2 3])    ; => (0 0 0)
```

#### `complement`
Returns a variadic function that calls its input function and negates the result's truth value.
```clojure
((complement even?) 3)          ; => true
((complement even?) 4)          ; => false

(def odd? (complement even?))
(filter (complement (fn [x] (= x nil))) [1 nil 2 nil]) ; => (1 2)
```

### Type Predicates

These predicates are prelude macros based on Python type checks. `number?` recognizes `int` and `float` only; because `bool` subclasses `int`, booleans also satisfy `int?` and `number?`. `fn?` is equivalent to Python `callable`, so callable objects and classes also satisfy it.

The collection predicates are intentionally narrow. `vector?` recognizes only `Vector`; `map?` recognizes only persistent `Map`; `list?` recognizes `Cons` and Python `list`; `seq?` recognizes only `Cons`; and `dict?` recognizes only Python `dict`. `coll?` recognizes `Vector`, `Map`, `Cons`, Python `list`, and Python `dict`. Typed vectors, sorted vectors, and sets are not included.

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
(number? true)      ; => true
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
(vector? (vec-i64 1 2)) ; => false
(map? {:a 1})       ; => true
(list? '(1 2 3))    ; => true
(seq? (rest [1 2])) ; => true
(coll? [1 2 3])     ; => true
(coll? {:a 1})      ; => true
(coll? #{1 2})      ; => false
(dict? (dict [["a" 1]])) ; => true
```

### Collection Predicates and Accessors

`not-empty` returns its original argument when nonempty. `butlast` is lazy, while the other accessors return a single value; `last` raises `IndexError` for an empty collection.

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
(ffirst [[1 2] [3 4]])  ; => 1
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

### Protocol Forms

These prelude macros support the protocol language forms:

| Macro | Purpose |
|-------|---------|
| `defprotocol` | Define a protocol and its dispatcher functions |
| `extend-type` | Implement one or more protocols for a type |
| `extend-protocol` | Implement one protocol for several types |

See [Protocols](LANG.md#9-protocols) in the Language Reference for syntax, examples, dispatch rules, structural protocols, and `isinstance` behavior.

---

## Standard Library Modules

### std.string

String manipulation utilities.

**Usage:** `(ns my-file (:require [std.string :as str]))`

#### `str.join`
Joins a collection of strings with `sep`. Non-string elements raise Python's `TypeError`.
```clojure
(str.join ", " ["a" "b" "c"])      ; => "a, b, c"
(str.join "-" ["1" "2" "3"])       ; => "1-2-3"
(str.join "" ["a" "b" "c"])        ; => "abc"
(str.join "\n" ["line1" "line2"])  ; => "line1\nline2"
```

#### `str.split`
Splits a string on an explicit separator and returns a persistent vector. Unlike Python's zero-argument `str.split`, the separator is required.
```clojure
(str.split "a,b,c" ",")           ; => ["a" "b" "c"]
(str.split "hello world" " ")     ; => ["hello" "world"]
(str.split "a-b-c-d" "-")         ; => ["a" "b" "c" "d"]
```

#### `str.trim` / `str.ltrim` / `str.rtrim`
Remove leading and/or trailing whitespace. These functions do not take a custom character set.
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
Counts non-overlapping occurrences of a substring.
```clojure
(str.substring-count "abab" "ab") ; => 2
(str.substring-count "aaa" "a")   ; => 3
(str.substring-count "aaa" "aa")  ; => 1
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
Extracts a substring using Python slice semantics: the start is inclusive, the end is exclusive, negative indices are accepted, and out-of-range bounds are clamped.
```clojure
(str.substring "hello" 1 4)       ; => "ell"
(str.substring "hello" 0 2)       ; => "he"
(str.substring "hello" 2 5)       ; => "llo"
```

#### `str.char-at`
Returns the one-character slice from `idx` to `idx + 1`. It is intended for nonnegative indices; an out-of-range index returns `""` rather than raising `IndexError`.
```clojure
(str.char-at "hello" 0)           ; => "h"
(str.char-at "hello" 1)           ; => "e"
(str.char-at "hello" 4)           ; => "o"
(str.char-at "hello" 9)           ; => ""
```

#### `str.length`
String length.
```clojure
(str.length "hello")              ; => 5
(str.length "")                   ; => 0
(str.length "日本語")              ; => 3
```

#### `str.pad-left` / `str.pad-right` / `str.center`
Pad to at least the requested width. The padding argument must be exactly one character; strings already at least as wide are unchanged.
```clojure
(str.pad-left "hi" 5 " ")         ; => "   hi"
(str.pad-left "42" 5 "0")         ; => "00042"
(str.pad-right "hi" 5 " ")        ; => "hi   "
(str.pad-right "hi" 5 ".")        ; => "hi..."
(str.center "hi" 6 "-")           ; => "--hi--"
(str.center "x" 5 " ")            ; => "  x  "
```

#### `str.lines`
Splits at line boundaries, removes the line endings, and returns a vector. A trailing line break does not add a final empty string.
```clojure
(str.lines "a\nb\nc")             ; => ["a" "b" "c"]
(str.lines "line1\nline2\nline3") ; => ["line1" "line2" "line3"]
(str.lines "single")              ; => ["single"]
(str.lines "a\n")                  ; => ["a"]
```

---

### std.map

Map manipulation utilities.

**Usage:** `(ns my-file (:require [std.map :as m]))`

#### `m.keys` / `m.vals`
Return keys or values as persistent vectors. Their order follows the map's unspecified iteration order.
```clojure
(def ks (m.keys {:a 1 :b 2 :c 3}))
(vector? ks)                      ; => true
(= (set ks) (set [:a :b :c]))    ; => true

(def vs (m.vals {:a 1 :b 2 :c 3}))
(vector? vs)                      ; => true
(= (set vs) (set [1 2 3]))       ; => true

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
Applies a function to the current value and associates the result. If the key is absent, the function receives `nil`.
```clojure
(m.update {:a 1} :a inc)          ; => {:a 2}
(m.update {:a 1 :b 2} :b #(* % 10))  ; => {:a 1 :b 20}
(m.update {:count 5} :count dec)  ; => {:count 4}
```

#### `m.update-with`
Like `m.update`, but supplies `default` when the key is absent. A stored `nil` remains `nil` and is not replaced by the default.
```clojure
(m.update-with {:a 1} :a inc 0)   ; => {:a 2}
(m.update-with {:a 1} :b inc 0)   ; => {:a 1 :b 1}
(m.update-with {} :count inc 0)   ; => {:count 1}
```

#### `m.get-in`
Traverses a sequence of keys through nested maps. It returns `nil` when a lookup fails; an empty key path returns the original map.
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
Associates a value at a nonempty path, creating missing intermediate maps. Existing intermediate values must themselves support map lookup and association.
```clojure
(m.assoc-in {:a {}} [:a :b] 1)         ; => {:a {:b 1}}
(m.assoc-in {} [:a :b :c] 42)          ; => {:a {:b {:c 42}}}
(m.assoc-in {:a {:b 1}} [:a :b] 99)    ; => {:a {:b 99}}
(m.assoc-in {:a {:b 1}} [:a :c] 2)     ; => {:a {:b 1 :c 2}}
```

#### `m.update-in`
Updates a value at a nonempty path. Missing intermediate maps are created, and a missing final value is passed to the function as `nil`.
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
Removes the final key at a nonempty nested path. The parent path should exist; when an intermediate key is missing, the current implementation associates `nil` at that point.
```clojure
(m.dissoc-in {:a {:b 1 :c 2}} [:a :b])    ; => {:a {:c 2}}
(m.dissoc-in {:a {:b {:c 1}}} [:a :b :c]) ; => {:a {:b {}}}
(m.dissoc-in {:x {:y 1}} [:x :y])         ; => {:x {}}
(m.dissoc-in {} [:x :y])                   ; => {:x nil}
```

#### `m.merge`
Merges zero or more maps into a new persistent map. Later values override earlier ones, and `nil` inputs are ignored.
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
Renames keys according to a mapping. If several source keys resolve to the same target, one overwrites the others according to the source map's unspecified iteration order.
```clojure
(m.rename-keys {:a 1 :b 2} {:a :x})        ; => {:x 1 :b 2}
(m.rename-keys {:a 1 :b 2} {:a :x :b :y})  ; => {:x 1 :y 2}
(m.rename-keys {:a 1 :b 2} {:c :z})        ; => {:a 1 :b 2}
(m.rename-keys {:old-name "value"} {:old-name :new-name})
; => {:new-name "value"}
```

#### `m.invert`
Swaps keys and values. Values must be hashable; duplicate values collapse to one entry according to unspecified map iteration order.
```clojure
(m.invert {:a 1 :b 2})            ; => {1 :a 2 :b}
(m.invert {:x "hello" :y "world"}) ; => {"hello" :x "world" :y}
(m.invert {1 :a 2 :b})            ; => {:a 1 :b 2}
```

#### `m.map-keys` / `m.map-vals`
Transform keys or values. Results from `m.map-keys` must be hashable, and key collisions overwrite according to unspecified map iteration order.
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
Recursively merges values when both sides are persistent Spork maps. In every other conflict, the later value replaces the earlier one.
```clojure
(m.deep-merge {:a {:b 1}} {:a {:c 2}})
; => {:a {:b 1 :c 2}}

(m.deep-merge {:a {:b {:c 1}}} {:a {:b {:d 2}}})
; => {:a {:b {:c 1 :d 2}}}

(m.deep-merge {:a {:x 1}} {:a {:x 2}})
; => {:a {:x 2}}

(m.deep-merge {:config {:debug false :port 8080}}
              {:config {:debug true}})
; => {:config {:debug true :port 8080}}
```

---

### std.json

JSON serialization and parsing with automatic conversion for Spork values.

**Usage:** `(ns my-file (:require [std.json :as json]))`

#### Encoding

`json.dumps` uses Python's standard single-line JSON formatting. `json.dumps-pretty` uses an indentation level of two. `json.generate` is an alias for `json.dumps`.

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
| `Map` | object; keyword and symbol keys use their names, and every other non-string key is stringified |
| `Vector`, `DoubleVector`, `IntVector`, `SortedVector` | array |
| `Set` | array; order is unspecified |
| `Cons` | array |
| `TransientMap`, `TransientVector`, `TransientSet` | their current mutable contents |
| keyword used as a value | string with a leading `:` |
| symbol used as a value | string |

`json.dump` and `json.dump-pretty` write to a file-like object and return `nil`:

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

JSON has no set, symbol, or keyword type, so those distinctions do not round-trip automatically. Stringification can also make distinct map keys collide in a JSON object. Invalid JSON and unsupported encoded values raise the corresponding Python `json` exceptions.

---

## Related Language Features

The following topics are language behavior rather than standard-library APIs and are documented in the [Language Reference](LANG.md):

- [protocol definitions and extension](LANG.md#9-protocols);
- [namespaces, `:require`, and Python `:import`](LANG.md#10-namespaces--modules);
- [keyword arguments](LANG.md#keyword-arguments) and [attribute access](LANG.md#attribute-and-method-access);
- [exceptions](LANG.md#13-exception-handling);
- [async functions and generators](LANG.md#12-async--generators).

### Common Python builtins

Python builtins remain accessible unless a Spork runtime binding overrides the same name. Notably, `map`, `filter`, `min`, `max`, and `abs` below are Spork runtime functions, while constructors such as `list`, `dict`, and `set` create Python built-in collections.

```clojure
(print "hello" "world")
(len [1 2 3])                  ; => 3
(= (type 42) int)              ; => true
(str 42)                       ; => "42"
(int "42")                     ; => 42
(float "3.14")                 ; => 3.14

; Python collection constructors retain their Python types
(def py-list (list (range 5)))
(isinstance py-list list)      ; => true
(vec py-list)                  ; => [0 1 2 3 4]

(def py-dict (dict [[:a 1] [:b 2]]))
(isinstance py-dict dict)      ; => true
(get py-dict :a)               ; => 1

(def py-set (set [1 2 2 3]))
(isinstance py-set set)        ; => true
(contains? py-set 3)           ; => true

(vec (sorted [3 1 2]))         ; => [1 2 3]
(vec (reversed [1 2 3]))       ; => [3 2 1]
(vec (map vec (enumerate ["a" "b" "c"])))
; => [[0 "a"] [1 "b"] [2 "c"]]
(vec (map vec (zip [1 2] ["a" "b"])))
; => [[1 "a"] [2 "b"]]

(doall (map inc [1 2 3]))      ; => [2 3 4]
(doall (filter even? [1 2 3 4])) ; => [2 4]
(any [false false true])       ; => true
(all [true true true])         ; => true
(sum [1 2 3 4])                ; => 10
(min 1 2 3)                    ; => 1
(max 1 2 3)                    ; => 3
(abs -5)                       ; => 5
(round 3.7)                    ; => 4
(callable inc)                 ; => true
(hasattr "hello" "upper")     ; => true
((getattr "hello" "upper"))    ; => "HELLO"

(def Box (type "Box" (tuple) (dict)))
(def box (Box))
(setattr box "attr" 42)
(getattr box "attr")           ; => 42
```
