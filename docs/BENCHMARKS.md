# Persistent Data Structure Benchmarks

## Overview

This benchmark suite compares Spork's persistent data structures (Vector, Map, Set) against Python's built-in mutables (list, dict, set). It measures raw C extension performance, bypassing the Spork interpreter.

## Why Benchmark PDS?

Persistent data structures are immutable—every "modification" returns a new version while preserving the original. The naive approach (copy everything) is O(n). Spork uses structural sharing via HAMTs and RRB trees to achieve O(log n) updates.

The benchmarks quantify:
1. The overhead of persistence vs mutables
2. The wins from structural sharing when creating derived versions
3. Transient performance for batch mutations

## Running

```bash
python3 tools/benchmark_pds.py --size 100000 --iter 50
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

## Adding Benchmarks

Add a method to the `Benchmarks` class:

```python
def bench_my_op(self):
    def py_version():
        ...
    def spork_version():
        ...

    py_time = run_benchmark("Python", py_version, self.ITERS)
    spork_time = run_benchmark("Spork", spork_version, self.ITERS)

    print_group("My Operation", [
        ("Python", py_time),
        ("Spork", spork_time),
    ])
```

Then call it from `main()`.


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
  Python [x for x in range(N)]      884.98 µs  (fastest)
  Python list(range(N))             906.43 µs  (~same)
  Python list.append() loop           1.28 ms  (1.45x slower)
  Spork TransientVector               1.79 ms  (2.02x slower)
  Spork vec(*range(N))                2.02 ms  (2.28x slower)
  Spork Vector.conj() chain           4.10 ms  (4.6x slower)

--- Float64 Vector Construction ---
  Python list[float]               535.15 µs  (fastest)
  Spork TransientDoubleVector        1.04 ms  (1.94x slower)
  Python array('d').extend()         1.36 ms  (2.53x slower)
  Spork vec_f64(*data)               2.63 ms  (4.9x slower)

--- Int64 Vector Construction ---
  Python list[int]                406.69 µs  (fastest)
  Spork TransientIntVector        616.90 µs  (1.52x slower)
  Python array('q').extend()      684.27 µs  (1.68x slower)
  Spork vec_i64(*data)              1.57 ms  (3.9x slower)

--- Random Access (10000 reads) ---
  Python list[i]                  505.48 µs  (fastest)
  Spork Vector[i]                   1.13 ms  (2.23x slower)
  Spork Vector.nth(i)               1.93 ms  (3.8x slower)

--- Sequential Iteration ---
  Python list                     549.10 µs  (fastest)
  Spork DoubleVector              697.33 µs  (1.27x slower)
  Spork Vector                    837.05 µs  (1.52x slower)
  Spork IntVector                 972.22 µs  (1.77x slower)

--- Vector Pop (1000 pops) ---
  Spork Transient.pop_mut()        41.81 µs  (fastest)
  Python list.pop()                49.54 µs  (1.18x slower)
  Spork Vector.pop()              157.84 µs  (3.8x slower)


============================================================
  MAP BENCHMARKS
============================================================

--- Map Construction (N=25000) ---
  Python dict(zip(k, v))            1.18 ms  (fastest)
  Python {k: v for ...}             1.58 ms  (1.34x slower)
  Python dict[] loop                1.63 ms  (1.39x slower)
  Spork TransientMap               10.21 ms  (8.7x slower)
  Spork hash_map(*args)            15.17 ms  (13x slower)
  Spork Map.assoc() chain          18.90 ms  (16x slower)

--- Map Lookup (10000 lookups) ---
  Python dict[k]                  383.02 µs  (fastest)
  Python dict.get(missing)        809.86 µs  (2.11x slower)
  Spork Map.get(k)                  1.48 ms  (3.9x slower)
  Spork Map.get(missing)            1.96 ms  (5.1x slower)

--- Map Dissoc (1000 removals) ---
  Python dict copy+del              207.46 µs  (fastest)
  Spork Transient.dissoc_mut()      735.40 µs  (3.5x slower)
  Spork Map.dissoc()                  1.20 ms  (5.8x slower)

--- Map Iteration - keys() ---
  Python dict.keys()                1.67 ms  (fastest)
  Spork Map.keys()                  4.16 ms  (2.49x slower)

--- Map Iteration - values() ---
  Python dict.values()              1.12 ms  (fastest)
  Spork Map.values()                2.99 ms  (2.66x slower)

--- Map Iteration - items() ---
  Python dict.items()               1.45 ms  (fastest)
  Spork Map.items()                 4.29 ms  (2.96x slower)


============================================================
  SET BENCHMARKS
============================================================

--- Set Construction (N=25000) ---
  Python set(iterable)            676.91 µs  (fastest)
  Python {x for x in ...}         800.58 µs  (1.18x slower)
  Python set.add() loop             1.14 ms  (1.68x slower)
  Spork TransientSet               11.22 ms  (17x slower)
  Spork Set.conj() chain           23.17 ms  (34x slower)

--- Set Membership (10000 lookups) ---
  Python set (in)                 810.36 µs  (fastest)
  Spork Set (in)                    1.76 ms  (2.17x slower)

--- Set Disj (1000 removals) ---
  Python set copy+discard         160.41 µs  (fastest)
  Spork Transient.disj_mut()      438.10 µs  (2.73x slower)
  Spork Set.disj()                693.17 µs  (4.3x slower)

--- Set Iteration ---
  Python set                        1.15 ms  (fastest)
  Spork Set                         4.03 ms  (3.5x slower)


============================================================
  STRUCTURAL SHARING BENCHMARKS
============================================================

  Scenario: Single update on collection of size 25000

--- Vector: Single Element Update ---
  Spork Vector.assoc()               1.20 µs  (fastest)
  Python list.copy() + modify       39.34 µs  (33x slower)

--- Map: Single Key Update ---
  Spork Map.assoc()                  1.11 µs  (fastest)
  Python dict.copy() + modify      104.58 µs  (94x slower)

--- Set: Single Element Add ---
  Spork Set.conj()                  1.28 µs  (fastest)
  Python set.copy() + add         147.36 µs  (115x slower)

  Scenario: 100 updates on collection of size 25000

--- Vector: Multiple Updates ---
  Spork Vector.assoc() chain        43.50 µs  (fastest)
  Spork Transient.assoc_mut()       53.87 µs  (1.24x slower)
  Python list copy chain             5.91 ms  (136x slower)

--- Map: Multiple Updates ---
  Spork Transient.assoc_mut()       41.45 µs  (fastest)
  Spork Map.assoc() chain           73.35 µs  (1.77x slower)
  Python dict copy chain            13.68 ms  (330x slower)


============================================================
  UTILITY BENCHMARKS
============================================================

--- Length Operation ---
  Spork len(Set)                    0.24 µs  (fastest)
  Spork len(Vector)                 0.26 µs  (~same)
  Python len(list)                  0.27 µs  (1.10x slower)
  Python len(set)                   0.32 µs  (1.33x slower)
  Python len(dict)                  0.34 µs  (1.40x slower)
  Spork len(Map)                    0.42 µs  (1.73x slower)

--- Eager Sequence Conversion (to Cons list) ---
  Python list(iter(list))         124.04 µs  (fastest)
  Spork Vector.to_seq()             1.76 ms  (14x slower)
  Spork Set.to_seq()                5.00 ms  (40x slower)
  Spork Map.to_seq()               13.14 ms  (106x slower)

--- Lazy Sequence Creation (O(1)) ---
  Python iter(list)                 0.26 µs  (fastest)
  Python (x for x in list)          0.88 µs  (3.3x slower)
  Spork lazy_seq(Map)               1.70 µs  (6.4x slower)
  Spork lazy_seq(Vector)            1.94 µs  (7.3x slower)
  Spork lazy_seq(Set)               8.96 µs  (34x slower)

--- Lazy Sequence Full Consumption ---
  Python sum(iter(list))             1.40 ms  (fastest)
  Spork sum(lazy_seq(Vector))       14.71 ms  (10x slower)


============================================================
  NUMPY INTEROP BENCHMARKS
============================================================

--- NumPy Array Creation ---
  np.array(DoubleVector) [zero-copy]        0.70 µs  (fastest)
  np.array(Python list)                   622.69 µs  (886x slower)

--- NumPy Operations ---
  np.sum(from list)                 7.12 µs  (fastest)
  np.sum(from DoubleVector)         9.10 µs  (1.28x slower)
  np.mean(from list)               24.11 µs  (3.4x slower)
  np.mean(from DoubleVector)       62.08 µs  (8.7x slower)

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
  Python list(range(N))               1.70 ms  (fastest)
  Python [x for x in range(N)]        2.10 ms  (1.23x slower)
  Python list.append() loop           2.32 ms  (1.36x slower)
  Spork vec(*range(N))                2.52 ms  (1.48x slower)
  Spork TransientVector               4.38 ms  (2.57x slower)
  Spork Vector.conj() chain           9.71 ms  (5.7x slower)

--- Float64 Vector Construction ---
  Python list[float]               770.02 µs  (fastest)
  Spork TransientDoubleVector        1.18 ms  (1.54x slower)
  Python array('d').extend()         1.66 ms  (2.15x slower)
  Spork vec_f64(*data)               3.48 ms  (4.5x slower)

--- Int64 Vector Construction ---
  Python list[int]                623.56 µs  (fastest)
  Python array('q').extend()        1.34 ms  (2.15x slower)
  Spork TransientIntVector          1.42 ms  (2.28x slower)
  Spork vec_i64(*data)              3.44 ms  (5.5x slower)

--- Random Access (10000 reads) ---
  Python list[i]                  646.13 µs  (fastest)
  Spork Vector[i]                   1.14 ms  (1.76x slower)
  Spork Vector.nth(i)               1.63 ms  (2.52x slower)

--- Sequential Iteration ---
  Spork Vector                      1.27 ms  (fastest)
  Python list                       1.38 ms  (~same)
  Spork DoubleVector                1.61 ms  (1.27x slower)
  Spork IntVector                   2.27 ms  (1.78x slower)

--- Vector Pop (1000 pops) ---
  Spork Transient.pop_mut()        57.53 µs  (fastest)
  Python list.pop()                79.16 µs  (1.38x slower)
  Spork Vector.pop()               99.40 µs  (1.73x slower)


============================================================
  MAP BENCHMARKS
============================================================

--- Map Construction (N=50000) ---
  Python dict(zip(k, v))            2.70 ms  (fastest)
  Python {k: v for ...}             3.57 ms  (1.32x slower)
  Python dict[] loop                3.63 ms  (1.34x slower)
  Spork hash_map(*args)            21.38 ms  (7.9x slower)
  Spork TransientMap               29.70 ms  (11x slower)
  Spork Map.assoc() chain          52.06 ms  (19x slower)

--- Map Lookup (10000 lookups) ---
  Python dict[k]                  427.09 µs  (fastest)
  Python dict.get(missing)        819.32 µs  (1.92x slower)
  Spork Map.get(missing)            1.10 ms  (2.58x slower)
  Spork Map.get(k)                  1.57 ms  (3.7x slower)

--- Map Dissoc (1000 removals) ---
  Python dict copy+del              255.65 µs  (fastest)
  Spork Transient.dissoc_mut()      406.61 µs  (1.59x slower)
  Spork Map.dissoc()                  1.24 ms  (4.8x slower)

--- Map Iteration - keys() ---
  Python dict.keys()                1.77 ms  (fastest)
  Spork Map.keys()                 13.14 ms  (7.4x slower)

--- Map Iteration - values() ---
  Python dict.values()              2.44 ms  (fastest)
  Spork Map.values()               10.44 ms  (4.3x slower)

--- Map Iteration - items() ---
  Python dict.items()               3.15 ms  (fastest)
  Spork Map.items()                19.90 ms  (6.3x slower)


============================================================
  SET BENCHMARKS
============================================================

--- Set Construction (N=50000) ---
  Python set(iterable)              1.03 ms  (fastest)
  Python {x for x in ...}           1.13 ms  (1.10x slower)
  Python set.add() loop             2.16 ms  (2.09x slower)
  Spork TransientSet               23.85 ms  (23x slower)
  Spork Set.conj() chain           59.43 ms  (58x slower)

--- Set Membership (10000 lookups) ---
  Python set (in)                 812.56 µs  (fastest)
  Spork Set (in)                    1.91 ms  (2.35x slower)

--- Set Disj (1000 removals) ---
  Python set copy+discard         300.53 µs  (fastest)
  Spork Transient.disj_mut()      670.57 µs  (2.23x slower)
  Spork Set.disj()                  1.10 ms  (3.7x slower)

--- Set Iteration ---
  Python set                        2.25 ms  (fastest)
  Spork Set                        10.28 ms  (4.6x slower)


============================================================
  STRUCTURAL SHARING BENCHMARKS
============================================================

  Scenario: Single update on collection of size 50000

--- Vector: Single Element Update ---
  Spork Vector.assoc()               0.76 µs  (fastest)
  Python list.copy() + modify      116.91 µs  (153x slower)

--- Map: Single Key Update ---
  Spork Map.assoc()                  1.12 µs  (fastest)
  Python dict.copy() + modify      259.02 µs  (231x slower)

--- Set: Single Element Add ---
  Spork Set.conj()                  1.64 µs  (fastest)
  Python set.copy() + add         239.07 µs  (146x slower)

  Scenario: 100 updates on collection of size 50000

--- Vector: Multiple Updates ---
  Spork Transient.assoc_mut()       21.00 µs  (fastest)
  Spork Vector.assoc() chain        44.06 µs  (2.10x slower)
  Python list copy chain            11.58 ms  (551x slower)

--- Map: Multiple Updates ---
  Spork Map.assoc() chain           99.92 µs  (fastest)
  Spork Transient.assoc_mut()      123.57 µs  (1.24x slower)
  Python dict copy chain            34.87 ms  (349x slower)


============================================================
  UTILITY BENCHMARKS
============================================================

--- Length Operation ---
  Python len(dict)                  0.24 µs  (fastest)
  Python len(set)                   0.24 µs  (~same)
  Spork len(Map)                    0.27 µs  (1.13x slower)
  Spork len(Vector)                 0.29 µs  (1.20x slower)
  Spork len(Set)                    0.34 µs  (1.41x slower)
  Python len(list)                  1.97 µs  (8.2x slower)

--- Eager Sequence Conversion (to Cons list) ---
  Python list(iter(list))         254.80 µs  (fastest)
  Spork Vector.to_seq()             3.49 ms  (14x slower)
  Spork Set.to_seq()               11.06 ms  (43x slower)
  Spork Map.to_seq()               34.36 ms  (135x slower)

--- Lazy Sequence Creation (O(1)) ---
  Python iter(list)                 0.35 µs  (fastest)
  Python (x for x in list)          0.48 µs  (1.37x slower)
  Spork lazy_seq(Set)               1.09 µs  (3.1x slower)
  Spork lazy_seq(Map)               1.21 µs  (3.5x slower)
  Spork lazy_seq(Vector)            2.40 µs  (6.9x slower)

--- Lazy Sequence Full Consumption ---
  Python sum(iter(list))             2.23 ms  (fastest)
  Spork sum(lazy_seq(Vector))       33.24 ms  (15x slower)


============================================================
  NUMPY INTEROP BENCHMARKS
============================================================

--- NumPy Array Creation ---
  np.array(DoubleVector) [zero-copy]        3.55 µs  (fastest)
  np.array(Python list)                     2.05 ms  (576x slower)

--- NumPy Operations ---
  np.sum(from DoubleVector)        10.69 µs  (fastest)
  np.mean(from list)               13.31 µs  (1.25x slower)
  np.mean(from DoubleVector)       17.45 µs  (1.63x slower)
  np.sum(from list)                28.21 µs  (2.64x slower)

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
  Python list(range(N))               4.69 ms  (fastest)
  Python [x for x in range(N)]        4.85 ms  (~same)
  Python list.append() loop           5.79 ms  (1.24x slower)
  Spork vec(*range(N))                7.87 ms  (1.68x slower)
  Spork TransientVector               8.27 ms  (1.77x slower)
  Spork Vector.conj() chain          19.80 ms  (4.2x slower)

--- Float64 Vector Construction ---
  Python list[float]                 1.85 ms  (fastest)
  Spork TransientDoubleVector        3.85 ms  (2.08x slower)
  Python array('d').extend()         4.89 ms  (2.64x slower)
  Spork vec_f64(*data)              11.20 ms  (6.1x slower)

--- Int64 Vector Construction ---
  Python list[int]                  2.18 ms  (fastest)
  Spork TransientIntVector          3.86 ms  (1.77x slower)
  Python array('q').extend()        4.79 ms  (2.20x slower)
  Spork vec_i64(*data)             11.92 ms  (5.5x slower)

--- Random Access (10000 reads) ---
  Python list[i]                  799.92 µs  (fastest)
  Spork Vector[i]                   2.25 ms  (2.81x slower)
  Spork Vector.nth(i)               2.91 ms  (3.6x slower)

--- Sequential Iteration ---
  Python list                       4.21 ms  (fastest)
  Spork Vector                      4.93 ms  (1.17x slower)
  Spork DoubleVector                5.05 ms  (1.20x slower)
  Spork IntVector                   7.96 ms  (1.89x slower)

--- Vector Pop (1000 pops) ---
  Spork Transient.pop_mut()        49.07 µs  (fastest)
  Spork Vector.pop()              162.48 µs  (3.3x slower)
  Python list.pop()               258.78 µs  (5.3x slower)


============================================================
  MAP BENCHMARKS
============================================================

--- Map Construction (N=100000) ---
  Python dict(zip(k, v))           14.33 ms  (fastest)
  Python {k: v for ...}            15.09 ms  (~same)
  Python dict[] loop               15.28 ms  (~same)
  Spork hash_map(*args)            91.05 ms  (6.4x slower)
  Spork TransientMap              120.85 ms  (8.4x slower)
  Spork Map.assoc() chain         203.16 ms  (14x slower)

--- Map Lookup (10000 lookups) ---
  Python dict.get(missing)        474.51 µs  (fastest)
  Python dict[k]                  863.64 µs  (1.82x slower)
  Spork Map.get(missing)            1.39 ms  (2.94x slower)
  Spork Map.get(k)                  3.07 ms  (6.5x slower)

--- Map Dissoc (1000 removals) ---
  Spork Transient.dissoc_mut()      734.49 µs  (fastest)
  Spork Map.dissoc()                  1.22 ms  (1.67x slower)
  Python dict copy+del                1.56 ms  (2.13x slower)

--- Map Iteration - keys() ---
  Python dict.keys()                6.69 ms  (fastest)
  Spork Map.keys()                 41.20 ms  (6.2x slower)

--- Map Iteration - values() ---
  Python dict.values()              5.15 ms  (fastest)
  Spork Map.values()               33.80 ms  (6.6x slower)

--- Map Iteration - items() ---
  Python dict.items()               6.19 ms  (fastest)
  Spork Map.items()                45.83 ms  (7.4x slower)


============================================================
  SET BENCHMARKS
============================================================

--- Set Construction (N=100000) ---
  Python set(iterable)              2.67 ms  (fastest)
  Python {x for x in ...}           2.98 ms  (1.12x slower)
  Python set.add() loop             3.34 ms  (1.25x slower)
  Spork TransientSet               53.88 ms  (20x slower)
  Spork Set.conj() chain          100.26 ms  (38x slower)

--- Set Membership (10000 lookups) ---
  Python set (in)                 955.99 µs  (fastest)
  Spork Set (in)                    1.66 ms  (1.74x slower)

--- Set Disj (1000 removals) ---
  Spork Transient.disj_mut()      716.12 µs  (fastest)
  Python set copy+discard         718.28 µs  (~same)
  Spork Set.disj()                892.63 µs  (1.25x slower)

--- Set Iteration ---
  Python set                        5.16 ms  (fastest)
  Spork Set                        16.43 ms  (3.2x slower)


============================================================
  STRUCTURAL SHARING BENCHMARKS
============================================================

  Scenario: Single update on collection of size 100000

--- Vector: Single Element Update ---
  Spork Vector.assoc()               1.44 µs  (fastest)
  Python list.copy() + modify      143.13 µs  (99x slower)

--- Map: Single Key Update ---
  Spork Map.assoc()                  1.93 µs  (fastest)
  Python dict.copy() + modify        1.09 ms  (566x slower)

--- Set: Single Element Add ---
  Spork Set.conj()                  1.04 µs  (fastest)
  Python set.copy() + add         433.89 µs  (418x slower)

  Scenario: 100 updates on collection of size 100000

--- Vector: Multiple Updates ---
  Spork Vector.assoc() chain        44.91 µs  (fastest)
  Spork Transient.assoc_mut()      165.62 µs  (3.7x slower)
  Python list copy chain            15.59 ms  (347x slower)

--- Map: Multiple Updates ---
  Spork Transient.assoc_mut()       51.14 µs  (fastest)
  Spork Map.assoc() chain           70.95 µs  (1.39x slower)
  Python dict copy chain           127.94 ms  (2502x slower)


============================================================
  UTILITY BENCHMARKS
============================================================

--- Length Operation ---
  Spork len(Vector)                 0.28 µs  (fastest)
  Spork len(Map)                    0.37 µs  (1.28x slower)
  Python len(dict)                  0.38 µs  (1.33x slower)
  Python len(set)                   0.38 µs  (1.33x slower)
  Python len(list)                  0.39 µs  (1.35x slower)
  Spork len(Set)                    1.28 µs  (4.5x slower)

--- Eager Sequence Conversion (to Cons list) ---
  Python list(iter(list))         570.43 µs  (fastest)
  Spork Vector.to_seq()             5.52 ms  (9.7x slower)
  Spork Set.to_seq()               16.85 ms  (30x slower)
  Spork Map.to_seq()               61.15 ms  (107x slower)

--- Lazy Sequence Creation (O(1)) ---
  Python iter(list)                 0.37 µs  (fastest)
  Python (x for x in list)          0.54 µs  (1.45x slower)
  Spork lazy_seq(Vector)            1.12 µs  (3.0x slower)
  Spork lazy_seq(Map)               1.23 µs  (3.3x slower)
  Spork lazy_seq(Set)               1.31 µs  (3.5x slower)

--- Lazy Sequence Full Consumption ---
  Python sum(iter(list))             3.38 ms  (fastest)
  Spork sum(lazy_seq(Vector))       55.18 ms  (16x slower)


============================================================
  NUMPY INTEROP BENCHMARKS
============================================================

--- NumPy Array Creation ---
  np.array(DoubleVector) [zero-copy]        4.39 µs  (fastest)
  np.array(Python list)                     3.24 ms  (738x slower)

--- NumPy Operations ---
  np.mean(from list)               22.19 µs  (fastest)
  np.mean(from DoubleVector)       23.55 µs  (~same)
  np.sum(from DoubleVector)        44.33 µs  (2.00x slower)
  np.sum(from list)               126.76 µs  (5.7x slower)

  Verification: Array sum=4999950000.00

Benchmark complete!
```

</details>
