" Spork plugin for Neovim
" Language: Spork (a Lisp that compiles to Python)
" Maintainer: Spork Language Team
" Latest Revision: 2024

if exists("g:loaded_spork")
  finish
endif
let g:loaded_spork = 1

" Save compatibility options
let s:save_cpo = &cpo
set cpo&vim

" User configuration variables
if !exists("g:spork_cmd")
  let g:spork_cmd = "spork"
endif

if !exists("g:spork_lsp_enabled")
  let g:spork_lsp_enabled = 1
endif

" Restore compatibility options
let &cpo = s:save_cpo
unlet s:save_cpo
