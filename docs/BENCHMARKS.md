# Persistent Data Structure Benchmarks

## Overview

This benchmark suite compares Spork's persistent data structures (Vector, Map, Set) against Python's built-in mutables (list, dict, set). It measures raw C extension performance, bypassing the Spork interpreter.

## Why Benchmark PDS?

Persistent data structures are immutable—every "modification" returns a new version while preserving the original. The naive approach (copy everything) is O(n). Spork uses structural sharing via HAMTs, RRB trees, and Bit-Partitioned Tries to achieve O(log n) updates.

The benchmarks quantify:
1. The overhead of persistence vs mutables
2. The wins from structural sharing when creating derived versions
3. Transient performance for batch mutations

## Running

```bash
.venv/bin/python tools/benchmark_pds.py --size 100000 --iter 50
```

Requires the C extension to be built. NumPy is optional.

## Methodology

Each benchmark:
1. Warms up with one untimed run
2. Disables GC during timing
3. Runs N iterations and averages
4. Sorts results fastest-to-slowest

## Benchmark Categories

### Vector Benchmarks
- **Construction**: `list.append()` vs `TransientVector.conj_mut()` vs `Vector.conj()`
- **Access**: Random index lookup and sequential iteration
- **Pop**: Removing elements from the end
- **Typed vectors**: `DoubleVector`/`IntVector` vs `array.array`

### Map Benchmarks
- **Construction**: `dict()` vs `TransientMap` vs `Map.assoc()` chain
- **Lookup**: Existing and missing key performance
- **Dissoc**: Key removal
- **Iteration**: `.keys()`, `.values()`, `.items()`

### Set Benchmarks
- **Construction**, **membership**, **disj**, **iteration**

### Structural Sharing (where PDS shines)
Compares creating a modified copy:
- Python: `collection.copy()` + modify → O(n)
- Spork: `.assoc()` / `.conj()` → O(log n)

For large collections with multiple updates, Spork can be 100x+ faster.

### Sequences
- Eager conversion via `to_seq()`
- Lazy sequences via `lazy_seq()`

### NumPy Interop
`DoubleVector` and `IntVector` support zero-copy `np.array()` via the buffer protocol.


## Results

### AMD Ryzen 7 6800H


- **OS**: Linux 6.12.54-gentoo-dist
- **CPU**: AMD Ryzen 7 6800H with Radeon Graphics
- **Cores**: 16
- **Memory**: 27.2 GB
- **Python**: CPython 3.13.5
- **Architecture**: x86_64

#### N=25,000

<details>
<summary>Click to expand benchmark results (N=25,000)</summary>

```sh
$ .venv/bin/python tools/benchmark_pds.py --size 25000
Spork PDS Performance Benchmark
Size: 25000, Iterations: 50
------------------------------------------------------------
generating pre-built structures (N=25000)... done.


============================================================
  VECTOR BENCHMARKS
============================================================

--- Vector Construction (N=25000) ---
  Python [x for x in range(N)]      893.27 µs  (fastest)
  Python list(range(N))               1.01 ms  (1.13x slower)
  Python list.append() loop           1.21 ms  (1.36x slower)
  Spork TransientVector               1.88 ms  (2.10x slower)
  Spork vec(*range(N))                2.27 ms  (2.54x slower)
  Spork Vector.conj() chain           3.53 ms  (3.9x slower)

--- Float64 Vector Construction ---
  Python list[float]               443.68 µs  (fastest)
  Spork vec_f64(*data)             443.92 µs  (~same)
  Spork vec(*data) boxed           495.98 µs  (1.12x slower)
  Spork TransientDoubleVector        1.09 ms  (2.46x slower)
  Python array('d').extend()         1.29 ms  (2.91x slower)

--- Int64 Vector Construction ---
  Spork vec_i64(*data)            248.49 µs  (fastest)
  Python list[int]                289.20 µs  (1.16x slower)
  Spork TransientIntVector        618.41 µs  (2.49x slower)
  Python array('q').extend()      659.65 µs  (2.65x slower)
  Spork vec(*data) boxed          811.47 µs  (3.3x slower)

--- Random Access (10000 reads) ---
  Python list[i]                  343.91 µs  (fastest)
  Spork Vector[i]                   1.09 ms  (3.2x slower)
  Spork Vector.nth(i)               1.53 ms  (4.4x slower)

--- Sequential Iteration ---
  Python list                     543.06 µs  (fastest)
  Spork Vector                    637.15 µs  (1.17x slower)
  Spork DoubleVector              697.22 µs  (1.28x slower)
  Spork IntVector                 949.97 µs  (1.75x slower)

--- Vector Pop (1000 pops) ---
  Spork Transient.pop_mut()        41.12 µs  (fastest)
  Python list.pop()                48.32 µs  (1.18x slower)
  Spork Vector.pop()               86.63 µs  (2.11x slower)


============================================================
  MAP BENCHMARKS
============================================================

--- Map Construction (N=25000) ---
  Python dict(zip(k, v))            1.18 ms  (fastest)
  Python {k: v for ...}             1.31 ms  (1.11x slower)
  Python dict[] loop                1.80 ms  (1.53x slower)
  Spork TransientMap                9.98 ms  (8.4x slower)
  Spork hash_map(*args)            10.49 ms  (8.9x slower)
  Spork Map.assoc() chain          18.00 ms  (15x slower)

--- Map Lookup (10000 lookups) ---
  Python dict.get(missing)        407.57 µs  (fastest)
  Python dict[k]                  433.12 µs  (~same)
  Spork Map.get(missing)            1.05 ms  (2.58x slower)
  Spork Map.get(k)                  1.45 ms  (3.6x slower)

--- Map Dissoc (1000 removals) ---
  Python dict copy+del              101.64 µs  (fastest)
  Spork Transient.dissoc_mut()      382.22 µs  (3.8x slower)
  Spork Map.dissoc()                637.71 µs  (6.3x slower)

--- Map Iteration - keys() ---
  Python dict.keys()              840.55 µs  (fastest)
  Spork Map.keys()                  1.89 ms  (2.25x slower)

--- Map Iteration - values() ---
  Python dict.values()            625.27 µs  (fastest)
  Spork Map.values()                2.23 ms  (3.6x slower)

--- Map Iteration - items() ---
  Python dict.items()               1.34 ms  (fastest)
  Spork Map.items()                 4.48 ms  (3.3x slower)


============================================================
  SET BENCHMARKS
============================================================

--- Set Construction (N=25000) ---
  Python set(iterable)            572.92 µs  (fastest)
  Python {x for x in ...}         772.91 µs  (1.35x slower)
  Python set.add() loop             1.07 ms  (1.87x slower)
  Spork TransientSet               11.27 ms  (20x slower)
  Spork Set.conj() chain           22.90 ms  (40x slower)

--- Set Membership (10000 lookups) ---
  Python set (in)                 697.04 µs  (fastest)
  Spork Set (in)                    2.15 ms  (3.1x slower)

--- Set Disj (1000 removals) ---
  Python set copy+discard         157.54 µs  (fastest)
  Spork Transient.disj_mut()      211.62 µs  (1.34x slower)
  Spork Set.disj()                746.24 µs  (4.7x slower)

--- Set Iteration ---
  Python set                        1.27 ms  (fastest)
  Spork Set                         2.36 ms  (1.86x slower)


============================================================
  STRUCTURAL SHARING BENCHMARKS
============================================================

  Scenario: Single update on collection of size 25000

--- Vector: Single Element Update ---
  Spork Vector.assoc()               0.64 µs  (fastest)
  Python list.copy() + modify       33.42 µs  (53x slower)

--- Map: Single Key Update ---
  Spork Map.assoc()                  1.00 µs  (fastest)
  Python dict.copy() + modify       91.64 µs  (92x slower)

--- Set: Single Element Add ---
  Spork Set.conj()                  0.90 µs  (fastest)
  Python set.copy() + add         162.28 µs  (181x slower)

  Scenario: 100 updates on collection of size 25000

--- Vector: Multiple Updates ---
  Spork Transient.assoc_mut()       20.04 µs  (fastest)
  Spork Vector.assoc() chain        31.00 µs  (1.55x slower)
  Python list copy chain             2.70 ms  (135x slower)

--- Map: Multiple Updates ---
  Spork Transient.assoc_mut()       42.12 µs  (fastest)
  Spork Map.assoc() chain           62.12 µs  (1.47x slower)
  Python dict copy chain             8.30 ms  (197x slower)


============================================================
  UTILITY BENCHMARKS
============================================================

--- Length Operation ---
  Spork len(Set)                    0.25 µs  (fastest)
  Python len(set)                   0.25 µs  (~same)
  Python len(dict)                  0.26 µs  (~same)
  Spork len(Vector)                 0.27 µs  (~same)
  Python len(list)                  0.28 µs  (1.13x slower)
  Spork len(Map)                    0.31 µs  (1.24x slower)

--- Eager Sequence Conversion (to Cons list) ---
  Python list(iter(list))          87.75 µs  (fastest)
  Spork Vector.to_seq()           914.71 µs  (10x slower)
  Spork Set.to_seq()                2.66 ms  (30x slower)
  Spork Map.to_seq()                5.58 ms  (64x slower)

--- Lazy Sequence Creation (O(1)) ---
  Python iter(list)                 0.28 µs  (fastest)
  Python (x for x in list)          0.46 µs  (1.65x slower)
  Spork lazy_seq(Map)               0.92 µs  (3.3x slower)
  Spork lazy_seq(Set)               1.01 µs  (3.6x slower)
  Spork lazy_seq(Vector)            1.05 µs  (3.7x slower)

--- Lazy Sequence Full Consumption ---
  Python sum(iter(list))           603.55 µs  (fastest)
  Spork sum(lazy_seq(Vector))        8.70 ms  (14x slower)


============================================================
  NUMPY INTEROP BENCHMARKS
============================================================

--- NumPy Array Creation ---
  np.array(DoubleVector) [zero-copy]        0.85 µs  (fastest)
  np.array(Python list)                   567.42 µs  (664x slower)

--- NumPy Operations ---
  np.sum(from list)                 7.57 µs  (fastest)
  np.sum(from DoubleVector)         7.75 µs  (~same)
  np.mean(from list)                9.11 µs  (1.20x slower)
  np.mean(from DoubleVector)       10.01 µs  (1.32x slower)

  Verification: Array sum=312487500.00

Benchmark complete!
```

</details>

#### N=50,000

<details>
<summary>Click to expand benchmark results (N=50,000)</summary>

```sh
$ .venv/bin/python tools/benchmark_pds.py --size 50000
Spork PDS Performance Benchmark
Size: 50000, Iterations: 50
------------------------------------------------------------
generating pre-built structures (N=50000)... done.


============================================================
  VECTOR BENCHMARKS
============================================================

--- Vector Construction (N=50000) ---
  Python list(range(N))             919.54 µs  (fastest)
  Python [x for x in range(N)]        1.13 ms  (1.23x slower)
  Python list.append() loop           1.38 ms  (1.50x slower)
  Spork vec(*range(N))                2.21 ms  (2.41x slower)
  Spork TransientVector               2.32 ms  (2.53x slower)
  Spork Vector.conj() chain           5.35 ms  (5.8x slower)

--- Float64 Vector Construction ---
  Spork vec_f64(*data)             446.69 µs  (fastest)
  Python list[float]               536.03 µs  (1.20x slower)
  Spork vec(*data) boxed           911.01 µs  (2.04x slower)
  Spork TransientDoubleVector        1.15 ms  (2.57x slower)
  Python array('d').extend()         1.33 ms  (2.97x slower)

--- Int64 Vector Construction ---
  Spork vec_i64(*data)            437.51 µs  (fastest)
  Python list[int]                534.14 µs  (1.22x slower)
  Spork vec(*data) boxed          915.69 µs  (2.09x slower)
  Spork TransientIntVector          1.23 ms  (2.81x slower)
  Python array('q').extend()        1.33 ms  (3.0x slower)

--- Random Access (10000 reads) ---
  Python list[i]                  401.16 µs  (fastest)
  Spork Vector[i]                   1.15 ms  (2.87x slower)
  Spork Vector.nth(i)               1.63 ms  (4.1x slower)

--- Sequential Iteration ---
  Python list                       1.17 ms  (fastest)
  Spork Vector                      1.33 ms  (1.14x slower)
  Spork DoubleVector                1.48 ms  (1.27x slower)
  Spork IntVector                   2.22 ms  (1.89x slower)

--- Vector Pop (1000 pops) ---
  Spork Transient.pop_mut()        46.39 µs  (fastest)
  Python list.pop()                88.68 µs  (1.91x slower)
  Spork Vector.pop()               96.18 µs  (2.07x slower)


============================================================
  MAP BENCHMARKS
============================================================

--- Map Construction (N=50000) ---
  Python dict(zip(k, v))            3.16 ms  (fastest)
  Python {k: v for ...}             3.53 ms  (1.12x slower)
  Python dict[] loop                3.61 ms  (1.14x slower)
  Spork hash_map(*args)            20.53 ms  (6.5x slower)
  Spork TransientMap               23.11 ms  (7.3x slower)
  Spork Map.assoc() chain          46.29 ms  (15x slower)

--- Map Lookup (10000 lookups) ---
  Python dict[k]                  427.22 µs  (fastest)
  Python dict.get(missing)        457.01 µs  (~same)
  Spork Map.get(missing)            1.13 ms  (2.63x slower)
  Spork Map.get(k)                  1.73 ms  (4.0x slower)

--- Map Dissoc (1000 removals) ---
  Python dict copy+del              209.53 µs  (fastest)
  Spork Transient.dissoc_mut()      426.45 µs  (2.04x slower)
  Spork Map.dissoc()                772.15 µs  (3.7x slower)

--- Map Iteration - keys() ---
  Python dict.keys()                1.91 ms  (fastest)
  Spork Map.keys()                  4.90 ms  (2.56x slower)

--- Map Iteration - values() ---
  Python dict.values()              1.36 ms  (fastest)
  Spork Map.values()                3.55 ms  (2.60x slower)

--- Map Iteration - items() ---
  Python dict.items()               1.58 ms  (fastest)
  Spork Map.items()                 5.28 ms  (3.3x slower)


============================================================
  SET BENCHMARKS
============================================================

--- Set Construction (N=50000) ---
  Python set(iterable)            586.32 µs  (fastest)
  Python {x for x in ...}         714.63 µs  (1.22x slower)
  Python set.add() loop             1.05 ms  (1.79x slower)
  Spork TransientSet               12.50 ms  (21x slower)
  Spork Set.conj() chain           27.01 ms  (46x slower)

--- Set Membership (10000 lookups) ---
  Python set (in)                 483.62 µs  (fastest)
  Spork Set (in)                  997.52 µs  (2.06x slower)

--- Set Disj (1000 removals) ---
  Python set copy+discard         160.77 µs  (fastest)
  Spork Transient.disj_mut()      362.75 µs  (2.26x slower)
  Spork Set.disj()                495.65 µs  (3.1x slower)

--- Set Iteration ---
  Python set                        1.26 ms  (fastest)
  Spork Set                         4.54 ms  (3.6x slower)


============================================================
  STRUCTURAL SHARING BENCHMARKS
============================================================

  Scenario: Single update on collection of size 50000

--- Vector: Single Element Update ---
  Spork Vector.assoc()               0.77 µs  (fastest)
  Python list.copy() + modify       70.00 µs  (91x slower)

--- Map: Single Key Update ---
  Spork Map.assoc()                  0.94 µs  (fastest)
  Python dict.copy() + modify      184.86 µs  (196x slower)

--- Set: Single Element Add ---
  Spork Set.conj()                  0.83 µs  (fastest)
  Python set.copy() + add         174.96 µs  (212x slower)

  Scenario: 100 updates on collection of size 50000

--- Vector: Multiple Updates ---
  Spork Transient.assoc_mut()       20.21 µs  (fastest)
  Spork Vector.assoc() chain        42.33 µs  (2.09x slower)
  Python list copy chain             5.79 ms  (287x slower)

--- Map: Multiple Updates ---
  Spork Transient.assoc_mut()       43.34 µs  (fastest)
  Spork Map.assoc() chain           62.61 µs  (1.44x slower)
  Python dict copy chain            16.06 ms  (371x slower)


============================================================
  UTILITY BENCHMARKS
============================================================

--- Length Operation ---
  Python len(set)                   0.20 µs  (fastest)
  Spork len(Set)                    0.29 µs  (1.42x slower)
  Spork len(Map)                    0.29 µs  (1.42x slower)
  Python len(list)                  0.29 µs  (1.43x slower)
  Python len(dict)                  0.32 µs  (1.56x slower)
  Spork len(Vector)                 0.53 µs  (2.61x slower)

--- Eager Sequence Conversion (to Cons list) ---
  Python list(iter(list))         162.41 µs  (fastest)
  Spork Vector.to_seq()             2.40 ms  (15x slower)
  Spork Set.to_seq()                7.41 ms  (46x slower)
  Spork Map.to_seq()               23.62 ms  (145x slower)

--- Lazy Sequence Creation (O(1)) ---
  Python iter(list)                 0.31 µs  (fastest)
  Python (x for x in list)          0.46 µs  (1.48x slower)
  Spork lazy_seq(Map)               1.05 µs  (3.4x slower)
  Spork lazy_seq(Set)               1.17 µs  (3.7x slower)
  Spork lazy_seq(Vector)            1.36 µs  (4.3x slower)

--- Lazy Sequence Full Consumption ---
  Python sum(iter(list))             1.32 ms  (fastest)
  Spork sum(lazy_seq(Vector))       21.03 ms  (16x slower)


============================================================
  NUMPY INTEROP BENCHMARKS
============================================================

--- NumPy Array Creation ---
  np.array(DoubleVector) [zero-copy]        0.84 µs  (fastest)
  np.array(Python list)                     1.29 ms  (1536x slower)

--- NumPy Operations ---
  np.sum(from DoubleVector)        11.08 µs  (fastest)
  np.sum(from list)                13.22 µs  (1.19x slower)
  np.mean(from DoubleVector)       14.47 µs  (1.31x slower)
  np.mean(from list)               18.60 µs  (1.68x slower)

  Verification: Array sum=1249975000.00

Benchmark complete!
```

</details>

#### N=100,000

<details>
<summary>Click to expand benchmark results (N=100,000)</summary>

```sh
$ .venv/bin/python tools/benchmark_pds.py --size 100000
Spork PDS Performance Benchmark
Size: 100000, Iterations: 50
------------------------------------------------------------
generating pre-built structures (N=100000)... done.


============================================================
  VECTOR BENCHMARKS
============================================================

--- Vector Construction (N=100000) ---
  Python list(range(N))               2.84 ms  (fastest)
  Python [x for x in range(N)]        3.31 ms  (1.17x slower)
  Python list.append() loop           3.82 ms  (1.34x slower)
  Spork vec(*range(N))                5.38 ms  (1.89x slower)
  Spork TransientVector               5.76 ms  (2.03x slower)
  Spork Vector.conj() chain          11.81 ms  (4.2x slower)

--- Float64 Vector Construction ---
  Spork vec_f64(*data)             986.60 µs  (fastest)
  Python list[float]                 1.22 ms  (1.24x slower)
  Spork vec(*data) boxed             1.98 ms  (2.00x slower)
  Spork TransientDoubleVector        2.43 ms  (2.46x slower)
  Python array('d').extend()         2.97 ms  (3.0x slower)

--- Int64 Vector Construction ---
  Spork vec_i64(*data)            975.93 µs  (fastest)
  Python list[int]                  1.15 ms  (1.18x slower)
  Spork vec(*data) boxed            2.11 ms  (2.16x slower)
  Spork TransientIntVector          2.63 ms  (2.69x slower)
  Python array('q').extend()        2.94 ms  (3.0x slower)

--- Random Access (10000 reads) ---
  Python list[i]                  461.62 µs  (fastest)
  Spork Vector[i]                   1.44 ms  (3.1x slower)
  Spork Vector.nth(i)               1.95 ms  (4.2x slower)

--- Sequential Iteration ---
  Python list                       2.81 ms  (fastest)
  Spork Vector                      3.45 ms  (1.23x slower)
  Spork DoubleVector                3.62 ms  (1.29x slower)
  Spork IntVector                   4.85 ms  (1.72x slower)

--- Vector Pop (1000 pops) ---
  Spork Transient.pop_mut()        47.79 µs  (fastest)
  Spork Vector.pop()               96.76 µs  (2.02x slower)
  Python list.pop()               156.52 µs  (3.3x slower)


============================================================
  MAP BENCHMARKS
============================================================

--- Map Construction (N=100000) ---
  Python dict(zip(k, v))            9.67 ms  (fastest)
  Python {k: v for ...}            10.13 ms  (~same)
  Python dict[] loop               10.77 ms  (1.11x slower)
  Spork hash_map(*args)            44.71 ms  (4.6x slower)
  Spork TransientMap               73.31 ms  (7.6x slower)
  Spork Map.assoc() chain         123.37 ms  (13x slower)

--- Map Lookup (10000 lookups) ---
  Python dict.get(missing)        471.08 µs  (fastest)
  Python dict[k]                  475.93 µs  (~same)
  Spork Map.get(missing)            1.16 ms  (2.46x slower)
  Spork Map.get(k)                  1.65 ms  (3.5x slower)

--- Map Dissoc (1000 removals) ---
  Spork Transient.dissoc_mut()      441.12 µs  (fastest)
  Spork Map.dissoc()                699.70 µs  (1.59x slower)
  Python dict copy+del              838.34 µs  (1.90x slower)

--- Map Iteration - keys() ---
  Python dict.keys()                4.03 ms  (fastest)
  Spork Map.keys()                 14.86 ms  (3.7x slower)

--- Map Iteration - values() ---
  Python dict.values()              2.92 ms  (fastest)
  Spork Map.values()                7.68 ms  (2.63x slower)

--- Map Iteration - items() ---
  Python dict.items()               3.94 ms  (fastest)
  Spork Map.items()                30.29 ms  (7.7x slower)


============================================================
  SET BENCHMARKS
============================================================

--- Set Construction (N=100000) ---
  Python set(iterable)              1.76 ms  (fastest)
  Python {x for x in ...}           2.05 ms  (1.17x slower)
  Python set.add() loop             2.42 ms  (1.38x slower)
  Spork TransientSet               30.50 ms  (17x slower)
  Spork Set.conj() chain           55.86 ms  (32x slower)

--- Set Membership (10000 lookups) ---
  Python set (in)                 482.35 µs  (fastest)
  Spork Set (in)                    1.03 ms  (2.14x slower)

--- Set Disj (1000 removals) ---
  Python set copy+discard         328.93 µs  (fastest)
  Spork Transient.disj_mut()      342.93 µs  (~same)
  Spork Set.disj()                505.17 µs  (1.54x slower)

--- Set Iteration ---
  Python set                        3.35 ms  (fastest)
  Spork Set                         9.06 ms  (2.70x slower)


============================================================
  STRUCTURAL SHARING BENCHMARKS
============================================================

  Scenario: Single update on collection of size 100000

--- Vector: Single Element Update ---
  Spork Vector.assoc()               0.79 µs  (fastest)
  Python list.copy() + modify      134.59 µs  (171x slower)

--- Map: Single Key Update ---
  Spork Map.assoc()                  1.07 µs  (fastest)
  Python dict.copy() + modify        1.01 ms  (939x slower)

--- Set: Single Element Add ---
  Spork Set.conj()                  0.90 µs  (fastest)
  Python set.copy() + add         416.82 µs  (462x slower)

  Scenario: 100 updates on collection of size 100000

--- Vector: Multiple Updates ---
  Spork Transient.assoc_mut()       23.26 µs  (fastest)
  Spork Vector.assoc() chain        44.02 µs  (1.89x slower)
  Python list copy chain            11.14 ms  (479x slower)

--- Map: Multiple Updates ---
  Spork Transient.assoc_mut()       55.45 µs  (fastest)
  Spork Map.assoc() chain           65.33 µs  (1.18x slower)
  Python dict copy chain            77.79 ms  (1403x slower)


============================================================
  UTILITY BENCHMARKS
============================================================

--- Length Operation ---
  Spork len(Set)                    0.24 µs  (fastest)
  Python len(dict)                  0.25 µs  (~same)
  Python len(list)                  0.31 µs  (1.28x slower)
  Spork len(Vector)                 0.34 µs  (1.38x slower)
  Python len(set)                   0.36 µs  (1.47x slower)
  Spork len(Map)                    0.44 µs  (1.82x slower)

--- Eager Sequence Conversion (to Cons list) ---
  Python list(iter(list))         329.93 µs  (fastest)
  Spork Vector.to_seq()             3.93 ms  (12x slower)
  Spork Set.to_seq()               17.06 ms  (52x slower)
  Spork Map.to_seq()               43.90 ms  (133x slower)

--- Lazy Sequence Creation (O(1)) ---
  Python iter(list)                 0.34 µs  (fastest)
  Python (x for x in list)          0.62 µs  (1.81x slower)
  Spork lazy_seq(Set)               1.54 µs  (4.5x slower)
  Spork lazy_seq(Map)               1.56 µs  (4.6x slower)
  Spork lazy_seq(Vector)            6.81 µs  (20x slower)

--- Lazy Sequence Full Consumption ---
  Python sum(iter(list))             3.02 ms  (fastest)
  Spork sum(lazy_seq(Vector))       40.88 ms  (14x slower)


============================================================
  NUMPY INTEROP BENCHMARKS
============================================================

--- NumPy Array Creation ---
  np.array(DoubleVector) [zero-copy]        1.23 µs  (fastest)
  np.array(Python list)                     2.47 ms  (2007x slower)

--- NumPy Operations ---
  np.mean(from DoubleVector)       20.84 µs  (fastest)
  np.sum(from DoubleVector)        21.34 µs  (~same)
  np.sum(from list)                21.41 µs  (~same)
  np.mean(from list)               22.21 µs  (~same)

  Verification: Array sum=4999950000.00

Benchmark complete!
```

</details>
