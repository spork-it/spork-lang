# Spork Standard Library Reference

This document provides comprehensive documentation for the Spork standard library, including built-in types, core functions, prelude macros, and standard library modules.

## Table of Contents

1. [Built-in Types](#built-in-types)
2. [Core Functions](#core-functions)
3. [Prelude Macros](#prelude-macros)
4. [Standard Library Modules](#standard-library-modules)

---

## Built-in Types

Spork provides persistent, immutable data structures implemented in C for performance.

### Vector

Persistent vectors provide efficient random access and updates. Vectors are created using square bracket syntax.

```clojure
; Creating vectors
[1 2 3 4 5]           ; literal syntax
(vec 1 2 3)           ; constructor function

; Basic operations
(conj [1 2] 3)        ; => [1 2 3]
(nth [1 2 3] 1)       ; => 2
(nth [1 2] 5 :default) ; => :default (with default)
(assoc [1 2 3] 1 42)  ; => [1 42 3]
(count [1 2 3])       ; => 3
(first [1 2 3])       ; => 1
(rest [1 2 3])        ; => (2 3)
(peek [1 2 3])        ; => 3
(pop [1 2 3])         ; => [1 2]
```

**Specialized Vectors:**
```clojure
; DoubleVector - Optimized for 64-bit floats
(vec-f64 1.0 2.0 3.0)  ; => DoubleVector

; IntVector - Optimized for 64-bit integers  
(vec-i64 1 2 3)        ; => IntVector
```

### Map

Persistent hash maps with keyword keys. Maps are created using curly brace syntax.

```clojure
; Creating maps
{:a 1 :b 2}              ; literal syntax
(hash-map :a 1 :b 2)     ; constructor function

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
(keys {:a 1 :b 2})       ; => (:a :b)
(vals {:a 1 :b 2})       ; => (1 2)
```

### Set

Persistent sets. Sets are created using `#{}` syntax.

```clojure
; Creating sets
#{1 2 3}               ; literal syntax
(hash-set 1 2 3)       ; constructor function

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

Singly-linked lists created by `cons` or returned by lazy sequence operations.

```clojure
; Creating lists
(cons 1 nil)              ; => (1)
(cons 1 (cons 2 nil))     ; => (1 2)
(cons 0 '(1 2 3))         ; => (0 1 2 3)

; Basic operations
(first (cons 1 (cons 2 nil)))  ; => 1
(rest (cons 1 (cons 2 nil)))   ; => (2)
(first nil)                    ; => nil
(rest nil)                     ; => ()
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

Persistent sorted vectors maintain elements in sorted order using a Red-Black tree. All operations are O(log n).

```clojure
; Creating sorted vectors
(sorted_vec [3 1 4 1 5 9])      ; => sorted_vec(1, 1, 3, 4, 5, 9)
(sorted_vec)                     ; empty sorted vector

; With key function (sort by result of key-fn)
(sorted_vec ["banana" "apple" "cherry"] :key len)
; => sorted_vec("apple", "banana", "cherry")

; With keyword as key (for sorting maps/dicts)
(sorted_vec [{:name "Bob" :age 25} {:name "Alice" :age 30}] :key :age)
; => sorted by age

; Reverse order
(sorted_vec [3 1 4] :reverse true)  ; => sorted_vec(4, 3, 1)

; Combine key and reverse
(sorted_vec items :key :score :reverse true)  ; highest scores first
```

**Basic Operations:**
```clojure
(def sv (sorted_vec [5 2 8 1 9]))

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
(def sv (sorted_vec [1 3 5]))

(conj sv 2)          ; => sorted_vec(1, 2, 3, 5) - inserts in sorted position
(conj sv 3)          ; => sorted_vec(1, 3, 3, 5) - duplicates allowed
(disj sv 3)          ; => sorted_vec(1, 5) - removes one occurrence
(disj sv 99)         ; => sorted_vec(1, 3, 5) - no-op if not found
```

**Search Operations:**
```clojure
(def sv (sorted_vec [10 20 30 40 50]))

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
(for [x (sorted_vec [3 1 4 1 5])]
  (print x))
; prints: 1 1 3 4 5

; Convert to vector
(vec (sorted_vec [3 1 4]))  ; => [1 3 4]
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
```

**Transient Operations:**
```clojure
; For batch operations, use transients
(def sv (sorted_vec [1 3 5]))
(def tsv (.transient sv))

(.conj_mut tsv 2)           ; mutates in place
(.conj_mut tsv 4)
(.disj_mut tsv 3)
(def result (.persistent tsv))  ; => sorted_vec(1, 2, 4, 5)

; Transient preserves key and reverse settings
(def sv (sorted_vec items :key :score :reverse true))
(def tsv (.transient sv))   ; still sorts by :score, reversed
```

**Equality and Hashing:**
```clojure
; Equal if same elements in same order
(= (sorted_vec [3 1 2]) (sorted_vec [1 2 3]))  ; => true
(= (sorted_vec [1 2]) (sorted_vec [1 2 3]))    ; => false

; Can be used as map keys (hashable)
(def cache {(sorted_vec [1 2 3]) "result"})
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
(first {:a 1 :b 2})  ; => [:a 1] (first entry)
```

#### `rest`
Returns a sequence of all elements except the first. Returns empty sequence (not nil) if collection has 0 or 1 elements.
```clojure
(rest [1 2 3])    ; => (2 3)
(rest [1])        ; => ()
(rest [])         ; => ()
(rest nil)        ; => ()
(rest "hello")    ; => ("e" "l" "l" "o")
```

#### `seq`
Returns a sequence on the collection, or `nil` if empty. Useful for testing if a collection has elements.
```clojure
(seq [1 2 3])     ; => (1 2 3)
(seq [])          ; => nil
(seq nil)         ; => nil
(seq "hi")        ; => ("h" "i")
(seq {:a 1})      ; => ([:a 1])

; Common pattern for checking if collection has elements
(if (seq coll)
  (println "has elements")
  (println "empty"))
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
Adds element(s) to a collection. Position depends on collection type: end for vectors, front for lists.
```clojure
; Vectors add at end
(conj [1 2] 3)           ; => [1 2 3]
(conj [1 2] 3 4 5)       ; => [1 2 3 4 5]

; Lists add at front
(conj '(1 2) 0)          ; => (0 1 2)
(conj '(2 3) 1 0)        ; => (0 1 2 3)

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
(assoc {} :x 1 :y 2 :z 3)     ; => {:x 1 :y 2 :z 3}

; Vectors (by index)
(assoc [1 2 3] 1 42)          ; => [1 42 3]
(assoc [1 2 3] 0 :first)      ; => [:first 2 3]
```

#### `dissoc`
Removes a key from a map. Returns map unchanged if key not present.
```clojure
(dissoc {:a 1 :b 2} :a)       ; => {:b 2}
(dissoc {:a 1 :b 2} :c)       ; => {:a 1 :b 2} (key not present)
(dissoc {:a 1 :b 2 :c 3} :a :c)  ; => {:b 2} (multiple keys)
```

#### `disj`
Removes an element from a set. Returns set unchanged if element not present.
```clojure
(disj #{1 2 3} 2)        ; => #{1 3}
(disj #{1 2 3} 5)        ; => #{1 2 3} (not present)
(disj #{1 2 3 4} 2 4)    ; => #{1 3} (multiple elements)
```

#### `get`
Returns the value for a key, with optional default. Works on maps, vectors (by index), sets, and strings.
```clojure
; Maps
(get {:a 1 :b 2} :a)         ; => 1
(get {:a 1} :b)              ; => nil
(get {:a 1} :b :not-found)   ; => :not-found

; Vectors (by index)
(get [1 2 3] 1)              ; => 2
(get [1 2 3] 10)             ; => nil
(get [1 2 3] 10 :oops)       ; => :oops

; Sets (membership check returning the element)
(get #{:a :b :c} :a)         ; => :a
(get #{:a :b :c} :d)         ; => nil

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
(empty '(1 2 3))        ; => ()
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

; Add to existing collection
(into [0] [1 2 3])           ; => [0 1 2 3]
(into {:a 1} {:b 2 :c 3})    ; => {:a 1 :b 2 :c 3}

; With transducer
(into [] (map inc) [1 2 3])  ; => [2 3 4]
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
(def sv (sorted_vec [1 3 5 7]))
(def tsv (.transient sv))

; Add elements (maintains sorted order)
(.conj_mut tsv 2)    ; now contains 1, 2, 3, 5, 7
(.conj_mut tsv 4)    ; now contains 1, 2, 3, 4, 5, 7
(.conj_mut tsv 6)    ; now contains 1, 2, 3, 4, 5, 6, 7

; Remove elements
(.disj_mut tsv 3)    ; now contains 1, 2, 4, 5, 6, 7
(.disj_mut tsv 99)   ; no-op, element not present

; Convert back to persistent
(def result (.persistent tsv))  ; => sorted_vec(1, 2, 4, 5, 6, 7)

; Transient preserves key function and reverse settings
(def sv (sorted_vec items :key :score :reverse true))
(def tsv (.transient sv))
(.conj_mut tsv new-item)  ; still sorted by :score in reverse
```

Note: After calling `.persistent`, the transient can no longer be used.

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

These functions return lazy sequences that compute elements on demand.

#### `map`
Applies a function to each element of one or more collections.
```clojure
; Single collection
(map inc [1 2 3])              ; => (2 3 4)
(map str [1 2 3])              ; => ("1" "2" "3")

; Multiple collections (stops at shortest)
(map + [1 2 3] [10 20 30])     ; => (11 22 33)
(map + [1 2] [10 20 30])       ; => (11 22)
(map vector [1 2 3] [:a :b :c]) ; => ([1 :a] [2 :b] [3 :c])

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
(filter string? [1 "a" 2 "b"])    ; => ("a" "b")

; Filter with keyword (truthy values)
(filter :active [{:active true :name "A"}
                 {:active false :name "B"}
                 {:active true :name "C"}])
; => ({:active true :name "A"} {:active true :name "C"})

; Filter with set (membership)
(filter #{2 4 6} [1 2 3 4 5 6])   ; => (2 4 6)
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
Returns a sequence of x repeated n times (or infinitely if no n given).
```clojure
(repeat 3 "x")              ; => ("x" "x" "x")
(repeat 5 0)                ; => (0 0 0 0 0)
(take 4 (repeat :a))        ; => (:a :a :a :a) (infinite)
(vec (repeat 3 [1 2]))      ; => [[1 2] [1 2] [1 2]]
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
(take 4 (iterate rest [1 2 3])) ; => ([1 2 3] (2 3) (3) ())
```

#### `range`
Returns a range of numbers.
```clojure
(range 5)            ; => (0 1 2 3 4)
(range 1 5)          ; => (1 2 3 4)
(range 0 10 2)       ; => (0 2 4 6 8)
(range 10 0 -1)      ; => (10 9 8 7 6 5 4 3 2 1)
(range 0 1 0.2)      ; => (0 0.2 0.4 0.6 0.8)
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
(apply str (interpose "-" [1 2 3]))  ; => "1-2-3"
```

#### `partition`
Partitions into groups of n elements. Drops incomplete final group.
```clojure
(partition 2 [1 2 3 4 5 6])       ; => ((1 2) (3 4) (5 6))
(partition 2 [1 2 3 4 5])         ; => ((1 2) (3 4)) (drops 5)
(partition 3 [1 2 3 4 5 6 7 8 9]) ; => ((1 2 3) (4 5 6) (7 8 9))

; With step (sliding window)
(partition 2 1 [1 2 3 4])         ; => ((1 2) (2 3) (3 4))
(partition 3 1 [1 2 3 4 5])       ; => ((1 2 3) (2 3 4) (3 4 5))
```

#### `partition-all`
Like partition but includes incomplete final group.
```clojure
(partition-all 2 [1 2 3 4 5])     ; => ((1 2) (3 4) (5))
(partition-all 3 [1 2 3 4 5])     ; => ((1 2 3) (4 5))
(partition-all 3 [1 2])           ; => ((1 2))
```

#### `keep`
Returns non-nil results of (f item).
```clojure
(keep #(if (even? %) %) [1 2 3 4 5 6])  ; => (2 4 6)
(keep identity [1 nil 2 nil 3])         ; => (1 2 3)
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
(map-indexed vector [:a :b :c])       ; => ([0 :a] [1 :b] [2 :c])
(map-indexed #(str %1 ": " %2) ["a" "b" "c"])  
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
(mapcat #(repeat 2 %) [1 2 3])       ; => (1 1 2 2 3 3)
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

; With set (finds element if present)
(some #{3 5 7} [1 2 3 4])        ; => 3
(some #{:a :b} [:c :d :a])       ; => :a

; Return actual matching value
(some #(if (> % 5) %) [1 3 6 2]) ; => 6
```

#### `every?`
Returns true if (pred item) is truthy for all items.
```clojure
(every? even? [2 4 6 8])         ; => true
(every? even? [2 4 5 6])         ; => false
(every? pos? [1 2 3])            ; => true
(every? string? ["a" "b" "c"])   ; => true
(every? identity [1 2 nil 3])    ; => false
```

#### `not-every?`
Returns true if (pred item) is false for at least one item.
```clojure
(not-every? even? [2 4 6 8])     ; => false
(not-every? even? [2 4 5 6])     ; => true
(not-every? pos? [1 -1 2])       ; => true
```

#### `not-any?`
Returns true if (pred item) is false for all items.
```clojure
(not-any? even? [1 3 5 7])       ; => true
(not-any? even? [1 3 4 5])       ; => false
(not-any? neg? [1 2 3])          ; => true
(not-any? string? [1 2 3])       ; => true
```

### Reduction Functions

#### `reduce`
Reduces a collection using a function. With 2 args, uses first element as initial value.
```clojure
; Sum
(reduce + [1 2 3 4])             ; => 10
(reduce + 0 [1 2 3 4])           ; => 10 (explicit init)
(reduce + 100 [1 2 3 4])         ; => 110

; Product
(reduce * [1 2 3 4])             ; => 24

; Build string
(reduce str ["a" "b" "c"])       ; => "abc"

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
(reductions * [1 2 3 4])         ; => (1 2 6 24)
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
(apply str (reverse "hello"))    ; => "olleh"
```

#### `sort`
Returns sorted sequence.
```clojure
(sort [3 1 4 1 5 9 2 6])         ; => (1 1 2 3 4 5 6 9)
(sort ["c" "a" "b"])             ; => ("a" "b" "c")
(sort > [3 1 4 1 5])             ; => (5 4 3 1 1) (descending)
(sort < [3 1 4 1 5])             ; => (1 1 3 4 5) (ascending, default)
```

#### `sort-by`
Sorts by key function.
```clojure
(sort-by count ["aaa" "b" "cc"]) ; => ("b" "cc" "aaa")
(sort-by :age [{:age 30} {:age 20} {:age 25}])
; => ({:age 20} {:age 25} {:age 30})

(sort-by :name [{:name "Charlie"} {:name "Alice"} {:name "Bob"}])
; => ({:name "Alice"} {:name "Bob"} {:name "Charlie"})

; With comparator
(sort-by count > ["a" "bbb" "cc"])  ; => ("bbb" "cc" "a")
```

#### `split-at`
Splits at index, returns pair of sequences.
```clojure
(split-at 2 [1 2 3 4 5])         ; => [(1 2) (3 4 5)]
(split-at 0 [1 2 3])             ; => [() (1 2 3)]
(split-at 10 [1 2 3])            ; => [(1 2 3) ()]
```

#### `split-with`
Splits where predicate becomes false.
```clojure
(split-with #(< % 3) [1 2 3 4 1 2])  ; => [(1 2) (3 4 1 2)]
(split-with pos? [1 2 0 3 4])        ; => [(1 2) (0 3 4)]
(split-with even? [2 4 6 7 8])       ; => [(2 4 6) (7 8)]
```

### Sequence Realization

#### `doall`
Forces realization of lazy sequence, returns it. Use when you need the results and side effects.
```clojure
(doall (map println [1 2 3]))    ; prints 1, 2, 3; returns (nil nil nil)
(def realized (doall (map inc (range 5))))
realized  ; => (1 2 3 4 5)
```

#### `dorun`
Forces realization, returns nil. Use for side effects when you don't need the results.
```clojure
(dorun (map println [1 2 3]))    ; prints 1, 2, 3; returns nil

; More memory efficient than doall when you don't need results
(dorun (map #(save-to-db %) large-collection))
```

#### `realized?`
Returns true if lazy sequence has been realized.
```clojure
(def lazy-nums (map inc [1 2 3]))
(realized? lazy-nums)            ; => false
(first lazy-nums)                ; force first element
(realized? lazy-nums)            ; => true (at least partially)
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
(+)             ; => 0 (identity)
(+ 5)           ; => 5
(+ 1 2)         ; => 3
(+ 1 2 3 4 5)   ; => 15

; Subtraction
(- 5)           ; => -5 (negation)
(- 10 3)        ; => 7
(- 10 3 2 1)    ; => 4

; Multiplication
(*)             ; => 1 (identity)
(* 5)           ; => 5
(* 2 3)         ; => 6
(* 2 3 4)       ; => 24

; Division
(/ 10 2)        ; => 5
(/ 20 2 2)      ; => 5
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
Integer quotient (truncates toward zero).
```clojure
(quot 10 3)     ; => 3
(quot 11 3)     ; => 3
(quot -10 3)    ; => -3
(quot 10 -3)    ; => -3
```

#### `max` / `min`
Maximum.minimum of arguments.
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
(bit-and-not 7 2)      ; => 5       (0111 & ~0010 = 0101)
(bit-and-not 15 3)     ; => 12      (1111 & ~0011 = 1100)

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

These symbol operators also work with sets:

```clojure
(def s1 #{1 2 3})
(def s2 #{2 3 4})

(| s1 s2)              ; => #{1 2 3 4}  (union)
(& s1 s2)              ; => #{2 3}      (intersection)
(^ s1 s2)              ; => #{1 4}      (symmetric difference)
```

---

## Prelude Macros

The prelude is automatically loaded in every Spork namespace. No import required.

### Control Flow

#### `when`
Executes body only if test is truthy. Returns nil if test is falsy.
```clojure
(when (> x 0)
  (println "positive")
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
    (+ 3)      ; (+ 5 3) => 8
    (* 2))     ; (* 8 2) => 16

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
; With arrow:
(-> {:a 1}
    (assoc :b 2)
    (conj [:c 3])
    (conj [:d 4]))
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
(mapv + [1 2 3] [4 5 6])    ; => [5 7 9]
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
(doseq {x [1 2 3]}
  (println x))
; prints: 1, 2, 3

(doseq {item items}
  (process item)
  (save item))
```

#### `for-all`
List comprehension returning a vector.
```clojure
(for-all {x [1 2 3]} (* x x))       ; => [1 4 9]
(for-all {x [1 2 3]} [x (* x 10)])  ; => [[1 10] [2 20] [3 30]]
```

### Function Composition

#### `comp`
Composes functions right-to-left.
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

(def greet (partial str "Hello, "))
(greet "World")                 ; => "Hello, World"
```

#### `identity`
Returns its argument unchanged.
```clojure
(identity 42)                   ; => 42
(identity nil)                  ; => nil
(filter identity [1 nil 2 nil 3])  ; => (1 2 3)
```

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
(filter (complement nil?) [1 nil 2 nil])  ; => (1 2)
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
(dict? {"a" 1})     ; => true (Python dict)
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
(extend-type String
  Showable
  (show [this] (str "String: " this)))

(extend-type Vector
  Showable
  (show [this] (str "Vector with " (count this) " elements"))
  Measurable
  (length [this] (count this)))
```

#### `extend-protocol`
Extends a protocol to multiple types.
```clojure
(extend-protocol Showable
  String
  (show [this] this)
  
  Integer
  (show [this] (str "Number: " this))
  
  Vector
  (show [this] (str "[" (count this) " items]")))
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
(str.join "-" [1 2 3])             ; => "1-2-3"
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
(m.keys {:a 1 :b 2 :c 3})         ; => [:a :b :c]
(m.vals {:a 1 :b 2 :c 3})         ; => [1 2 3]
(m.keys {})                       ; => []
(m.vals {})                       ; => []
```

#### `m.entries`
Get key-value pairs as vector of vectors.
```clojure
(m.entries {:a 1 :b 2})           ; => [[:a 1] [:b 2]]
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
Get-in with default value.
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
(m.merge-with concat {:a [1]} {:a [2]})   ; => {:a [1 2]}
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
(m.map-keys name {:a 1 :b 2})     ; => {"a" 1 "b" 2}
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
(m.filter-keys keyword? {:a 1 "b" 2})     ; => {:a 1}
(m.filter-keys #(= :a %) {:a 1 :b 2})     ; => {:a 1}

; Filter by values
(m.filter-vals even? {:a 1 :b 2 :c 3 :d 4})  ; => {:b 2 :d 4}
(m.filter-vals pos? {:a -1 :b 0 :c 1 :d 2})  ; => {:c 1 :d 2}
(m.filter-vals some? {:a 1 :b nil :c 2})     ; => {:a 1 :c 2}
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

## Protocols

Spork supports Clojure-style protocols for polymorphism.

### Defining Protocols

```clojure
(defprotocol Countable
  "Protocol for things that can be counted"
  (item-count [this] "Returns the count of items"))

(defprotocol Serializable
  (to-json [this])
  (to-xml [this]))
```

### Structural Protocols

Use `^structural` for duck-typed protocols (checks for method existence rather than explicit implementation):

```clojure
^structural
(defprotocol Nameable
  (get-name [this]))

; Any object with a get-name method satisfies this
```

### Implementing Protocols

```clojure
; Extend a single type to implement one or more protocols
(extend-type String
  Countable
  (item-count [this] (len this))
  
  Serializable
  (to-json [this] (str "\"" this "\""))
  (to-xml [this] (str "<string>" this "</string>")))

; Extend multiple types at once for one protocol
(extend-protocol Countable
  Vector
  (item-count [this] (count this))
  
  Map
  (item-count [this] (count this))
  
  String  
  (item-count [this] (len this)))
```

### Checking Protocol Support

```clojure
(satisfies? Countable [1 2 3])    ; => true
(satisfies? Countable "hello")   ; => true
(satisfies? Countable 42)        ; => false
```

---

## Python Interop

Spork provides seamless Python interoperability.

### Attribute Access

```clojure
; Get attribute
(.-attribute obj)
(.-__name__ some-class)

; Set attribute  
(set! (.-attribute obj) new-value)

; Method calls
(.method obj arg1 arg2)
(.upper "hello")              ; => "HELLO"
(.split "a,b,c" ",")          ; => ["a" "b" "c"]
(.format "{} + {}" 1 2)       ; => "1 + 2"
```

### Keyword Arguments

Use `*{...}` to pass keyword arguments to functions:

```clojure
; Basic keyword arguments
(f 1 2 *{:name "Alice" :age 30})  ; => f(1, 2, name="Alice", age=30)

; Multiple kwarg splats are allowed (after positional args)
(f pos1 pos2 *{:a 1} *{:b 2 :c 3})

; Works with Python functions
(.format "{name} is {age}" *{:name "Bob" :age 25})  ; => "Bob is 25"

; With Python's open()
(open "file.txt" *{:mode "r" :encoding "utf-8"})
```

### Import (Python Modules)

All imports must be declared inside the `(ns ...)` form using `:import`:

```clojure
(ns my.app
  (:import
    [json]                              ; import json
    [os]                                ; import os
    [os.path :as path]                  ; import os.path as path
    [collections :as coll]              ; import collections as coll
    [collections :refer [defaultdict Counter]]  ; from collections import ...
    [os.path :refer [join exists]]))    ; from os.path import join, exists

; Access with dot notation
(json.dumps {:a 1})
(path.join "a" "b")
(os.getcwd)
```

### Type Checking

```clojure
(isinstance x str)
(isinstance x int)
(isinstance x (tuple list dict))  ; Multiple types

(type obj)                ; Get type
(type "hello")            ; => <class 'str'>
```

### Exception Handling

```clojure
(try
  (risky-operation)
  (catch ValueError e
    (println "Value error:" (str e)))
  (catch [KeyError IndexError] e
    (println "Key or Index error:" (str e)))
  (finally
    (cleanup)))

; Throw exceptions
(throw (ValueError "Invalid input"))
(throw (RuntimeError "Something went wrong"))
```

### Python Builtins

All Python builtins are available:

```clojure
(print "hello" "world")
(len [1 2 3])                 ; => 3
(type obj)                    ; Get type
(str 42)                      ; => "42"
(int "42")                    ; => 42
(float "3.14")                ; => 3.14
(list (range 5))              ; => [0, 1, 2, 3, 4]
(dict [[:a 1] [:b 2]])        ; Python dict
(set [1 2 2 3])               ; Python set
(sorted [3 1 2])              ; => [1, 2, 3]
(reversed [1 2 3])            ; iterator
(enumerate ["a" "b" "c"])     ; iterator of (index, value)
(zip [1 2] ["a" "b"])         ; iterator of pairs
(map inc [1 2 3])             ; lazy sequence
(filter even? [1 2 3 4])      ; lazy sequence
(any [false false true])      ; => True
(all [true true true])        ; => True
(sum [1 2 3 4])               ; => 10
(min 1 2 3)                   ; => 1
(max 1 2 3)                   ; => 3
(abs -5)                      ; => 5
(round 3.7)                   ; => 4
(callable inc)                ; => True
(hasattr obj "method")        ; => True/False
(getattr obj "attr" default)  ; Get attribute with default
(setattr obj "attr" value)    ; Set attribute
```
