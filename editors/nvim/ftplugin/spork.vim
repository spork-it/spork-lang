" Filetype plugin for Spork files
" Spork is a Lisp that compiles to Python

if exists("b:did_ftplugin")
  finish
endif
let b:did_ftplugin = 1

" Save compatibility options
let s:save_cpo = &cpo
set cpo&vim

" Buffer-local settings
setlocal comments=:;
setlocal commentstring=;\ %s
setlocal formatoptions-=t
setlocal formatoptions+=croql

" Lisp-style settings for S-expression navigation
setlocal lisp
setlocal lispwords=def,defn,defmacro,defclass,defprotocol,fn,let,if,do,loop,for,while,try,catch,finally,with,match,when,unless,cond,->,->>,extend-type,extend-protocol,ns

" Match parentheses, brackets, and braces
setlocal matchpairs=(:),[:],{:}

" Keyword characters for Spork symbols (includes - and ? and ! and *)
setlocal iskeyword=@,48-57,_,-,?,!,*,+,/,<,>,=

" Indentation
setlocal expandtab
setlocal shiftwidth=2
setlocal softtabstop=2
setlocal tabstop=2
setlocal autoindent

" Folding based on syntax (parentheses)
setlocal foldmethod=syntax

" File suffixes for gf command
setlocal suffixesadd=.spork

" Define what constitutes a word for w/b/e motions
" Spork symbols can contain hyphens and other special chars
setlocal iskeyword+=-,?,!,*,+,/,<,>,=,:

" Undo buffer-local settings when filetype changes
let b:undo_ftplugin = "setlocal comments< commentstring< formatoptions< lisp< lispwords< matchpairs< iskeyword< expandtab< shiftwidth< softtabstop< tabstop< autoindent< foldmethod< suffixesadd<"

" Restore compatibility options
let &cpo = s:save_cpo
unlet s:save_cpo
