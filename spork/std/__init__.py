"""
spork.std - Spork Standard Library

This package contains Spork source files that define the standard library.

Structure:
- prelude.spork: Essential macros loaded automatically (when, unless, cond,
  ->, ->>, fmt, defprotocol, extend-type, etc.)

Requireable modules (use :require to import):
- std.string: String utilities (join, split, trim, etc.)
- std.map: Map utilities (update, get-in, assoc-in, merge, etc.)

Usage:
    (ns my-app
      (:require [std.string :as str]
                [std.map :as m]))

    (str.join ", " ["a" "b" "c"])  ; => "a, b, c"
    (m.get-in {:a {:b 1}} [:a :b]) ; => 1
"""
