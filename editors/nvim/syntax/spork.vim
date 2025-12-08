" Vim syntax file for Spork
" Language: Spork (a Lisp that compiles to Python)
" Maintainer: Spork Language Team
" Latest Revision: 2024

if exists("b:current_syntax")
  finish
endif

" Spork is case-sensitive
syntax case match

" Comments - semicolon to end of line
syntax match sporkComment /;.*$/

" Strings
syntax region sporkString start=/"/ skip=/\\"/ end=/"/ contains=sporkStringEscape
syntax match sporkStringEscape /\\[nrtbf\\"']/ contained
syntax match sporkStringEscape /\\u[0-9a-fA-F]\{4}/ contained

" Numbers
syntax match sporkNumber /\v<-?[0-9]+>/
syntax match sporkNumber /\v<-?[0-9]+\.[0-9]+>/
syntax match sporkNumber /\v<-?[0-9]+\.[0-9]+[eE][+-]?[0-9]+>/
syntax match sporkNumber /\v<0[xX][0-9a-fA-F]+>/
syntax match sporkNumber /\v<0[oO][0-7]+>/
syntax match sporkNumber /\v<0[bB][01]+>/

" Keywords (self-evaluating symbols starting with :)
syntax match sporkKeyword /:[a-zA-Z_][a-zA-Z0-9_\-\.\*\+\!\?]*/

" Boolean and nil
syntax keyword sporkBoolean true false
syntax keyword sporkNil nil

" Special forms - from spork/compiler/codegen.py
syntax keyword sporkSpecial def defn defmacro defclass fn let set!
syntax keyword sporkSpecial if do loop recur for while async-for
syntax keyword sporkSpecial try catch finally throw return
syntax keyword sporkSpecial quote quasiquote
syntax keyword sporkSpecial ns import
syntax keyword sporkSpecial await yield yield-from
syntax keyword sporkSpecial match with apply call

" Macros from spork/std/prelude.spork
syntax keyword sporkMacro when unless cond
syntax keyword sporkMacro -> ->>
syntax keyword sporkMacro comment fmt assert
syntax keyword sporkMacro mapv filterv doseq for-all
syntax keyword sporkMacro comp partial identity constantly complement
syntax keyword sporkMacro defprotocol extend-type extend-protocol

" Predicates from prelude
syntax match sporkMacro /\v<nil\?>/
syntax match sporkMacro /\v<some\?>/
syntax match sporkMacro /\v<string\?>/
syntax match sporkMacro /\v<number\?>/
syntax match sporkMacro /\v<int\?>/
syntax match sporkMacro /\v<float\?>/
syntax match sporkMacro /\v<bool\?>/
syntax match sporkMacro /\v<fn\?>/
syntax match sporkMacro /\v<symbol\?>/
syntax match sporkMacro /\v<keyword\?>/
syntax match sporkMacro /\v<vector\?>/
syntax match sporkMacro /\v<map\?>/
syntax match sporkMacro /\v<list\?>/
syntax match sporkMacro /\v<seq\?>/
syntax match sporkMacro /\v<coll\?>/
syntax match sporkMacro /\v<dict\?>/
syntax match sporkMacro /\v<empty\?>/
syntax match sporkMacro /\v<even\?>/
syntax match sporkMacro /\v<odd\?>/
syntax match sporkMacro /\v<pos\?>/
syntax match sporkMacro /\v<neg\?>/
syntax match sporkMacro /\v<zero\?>/

" Collection accessors
syntax keyword sporkMacro second ffirst last butlast not-empty

" Common functions from runtime
syntax keyword sporkFunction first rest cons conj assoc dissoc get nth
syntax keyword sporkFunction count len seq vec list hash-map hash-set
syntax keyword sporkFunction map filter reduce apply
syntax keyword sporkFunction inc dec + - * / mod
syntax keyword sporkFunction = not= < > <= >=
syntax keyword sporkFunction str print println pr prn
syntax keyword sporkFunction type isinstance callable
syntax keyword sporkFunction range take drop take-while drop-while
syntax keyword sporkFunction concat reverse sort sorted
syntax keyword sporkFunction keys vals contains? in
syntax keyword sporkFunction and or not

" Definition names (highlight the name after def/defn/etc.)
syntax match sporkDefName /\v(def|defn|defmacro|defclass|defprotocol)\s+\zs[a-zA-Z_][a-zA-Z0-9_\-\.\*\+\!\?]*/

" Decorators/metadata (^annotation form)
syntax match sporkDecorator /\^[a-zA-Z_][a-zA-Z0-9_\-\.\*\+\!\?]*/
syntax match sporkDecorator /\^([^)]*)/

" Quoting
syntax match sporkQuote /'/
syntax match sporkQuote /`/
syntax match sporkQuote /\~/
syntax match sporkQuote /\~@/

" Kwarg splat syntax
syntax match sporkKwargSplat /\*{/

" Set literal
syntax match sporkSetLiteral /#{/

" Symbols (generic identifier)
syntax match sporkSymbol /[a-zA-Z_][a-zA-Z0-9_\-\.\*\+\!\?\/]*/

" Brackets
syntax match sporkParen /[()]/
syntax match sporkBracket /[\[\]]/
syntax match sporkBrace /[{}]/

" Highlight groups
highlight default link sporkComment Comment
highlight default link sporkString String
highlight default link sporkStringEscape SpecialChar
highlight default link sporkNumber Number
highlight default link sporkKeyword Constant
highlight default link sporkBoolean Boolean
highlight default link sporkNil Constant
highlight default link sporkSpecial Keyword
highlight default link sporkMacro Macro
highlight default link sporkFunction Function
highlight default link sporkDefName Function
highlight default link sporkDecorator PreProc
highlight default link sporkQuote Special
highlight default link sporkKwargSplat Special
highlight default link sporkSetLiteral Special
highlight default link sporkSymbol Identifier
highlight default link sporkParen Delimiter
highlight default link sporkBracket Delimiter
highlight default link sporkBrace Delimiter

let b:current_syntax = "spork"
