" Vim indent file for Spork
" Language: Spork (a Lisp that compiles to Python)
" Maintainer: Spork Language Team
" Latest Revision: 2025

if exists("b:did_indent")
  finish
endif
let b:did_indent = 1

" Spork uses lisp-style indentation
setlocal indentexpr=SporkIndent()
setlocal indentkeys=!^F,o,O,),],}

" Only define the function once
if exists("*SporkIndent")
  finish
endif

let s:save_cpo = &cpo
set cpo&vim

" Forms that should have their body indented by 2 spaces
" Based on _INDENT_FORMS in spork/repl/backend.py
let s:indent_forms = [
  \ 'do', 'let', 'fn', 'defn', 'defmacro', 'defclass', 'def',
  \ 'if', 'when', 'unless', 'cond', 'match',
  \ 'try', 'catch', 'finally',
  \ 'loop', 'for', 'while', 'doseq', 'dotimes', 'async-for',
  \ 'extend-type', 'extend-protocol', 'defprotocol',
  \ 'with', 'ns', '->', '->>'
  \ ]

function! SporkIndent()
  let lnum = v:lnum
  let line = getline(lnum)

  " Start with basic lisp indentation
  if lnum == 1
    return 0
  endif

  " Find the previous non-blank line
  let prev_lnum = prevnonblank(lnum - 1)
  if prev_lnum == 0
    return 0
  endif

  let prev_line = getline(prev_lnum)
  let prev_indent = indent(prev_lnum)

  " Count open parens/brackets/braces on previous line
  let open_count = 0
  let i = 0
  let in_string = 0
  let prev_len = len(prev_line)

  while i < prev_len
    let c = prev_line[i]

    " Handle strings
    if c == '"' && (i == 0 || prev_line[i-1] != '\')
      let in_string = !in_string
    endif

    if !in_string
      if c == '(' || c == '[' || c == '{'
        let open_count += 1
      elseif c == ')' || c == ']' || c == '}'
        let open_count -= 1
      endif
    endif

    let i += 1
  endwhile

  " If previous line has unclosed delimiters, indent
  if open_count > 0
    " Check if this is a special form that needs body indentation
    let form_match = matchstr(prev_line, '(\s*\zs[a-zA-Z_][a-zA-Z0-9_\-\.\*\+\!\?]*\ze')
    if index(s:indent_forms, form_match) >= 0
      return prev_indent + &shiftwidth
    endif

    " For function calls, align with first argument if on same line
    " Otherwise use standard indentation
    return prev_indent + &shiftwidth
  elseif open_count < 0
    " Previous line closed more than it opened
    return prev_indent - (&shiftwidth * abs(open_count))
  endif

  " Check if current line starts with a closing delimiter
  let first_char = matchstr(line, '^\s*\zs.')
  if first_char == ')' || first_char == ']' || first_char == '}'
    " Find matching opening delimiter
    let match_lnum = searchpair('[({\[]', '', '[)}\]]', 'bnW')
    if match_lnum > 0
      return indent(match_lnum)
    endif
  endif

  " Default: maintain previous indentation
  return prev_indent
endfunction

let &cpo = s:save_cpo
unlet s:save_cpo
