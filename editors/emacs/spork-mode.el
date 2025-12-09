;;; spork-mode.el --- Major mode for Spork with nREPL integration  -*- lexical-binding: t; -*-

;; Copyright (C) 2025

;; Author: Spork Contributors
;; Version: 0.1.0
;; Package-Requires: ((emacs "26.1"))
;; Keywords: languages, lisp, spork
;; URL: https://github.com/yourusername/spork

;;; Commentary:

;; This package provides a major mode for Spork (a Lisp to Python transpiler)
;; with full nREPL integration. It offers CIDER-like functionality including:
;;
;; Core Features:
;; - Syntax highlighting for Spork code
;; - Lisp-style indentation and navigation
;; - Start/stop nREPL server
;; - Connect to running nREPL server
;; - Evaluate forms, regions, and buffers
;; - Load files into the REPL
;; - REPL buffer with history
;; - Auto-completion
;; - Pretty-printed results
;;
;; Runtime Features (Spork Runtime v0.1):
;; - Documentation lookup with rich metadata (type, arglists, protocols)
;; - Macroexpansion - see what your macros expand to
;; - Jump to definition (M-.) with xref integration
;; - Interactive value inspector - drill into data structures
;; - Protocol browser - list all registered protocols
;;
;; Usage:
;;   (require 'spork-mode)
;;   ;; Files ending in .spork or .lpy will automatically use spork-mode
;;
;; Key Bindings:
;;   M-x spork-jack-in         ;; Start server and connect
;;   M-x spork-connect         ;; Connect to existing server
;;
;;   Evaluation:
;;   C-c C-k                   ;; Load current buffer
;;   C-c C-c                   ;; Eval form at point
;;   C-c C-e                   ;; Eval form before point (last sexp)
;;   C-c C-r                   ;; Eval region
;;   C-c C-b                   ;; Eval buffer
;;   C-c C-z                   ;; Switch to REPL buffer
;;
;;   Namespaces:
;;   C-c C-n                   ;; Switch to namespace
;;   C-c n                     ;; Show current namespace
;;   C-c C-S-n                 ;; List all namespaces
;;
;;   Documentation & Info:
;;   C-c C-d                   ;; Show documentation
;;   C-c i                     ;; Show rich info (type, arglists, etc.)
;;   C-c C-m                   ;; Macroexpand form at point
;;   C-c C-t                   ;; Transpile form at point to Python
;;   C-c C-p                   ;; List all protocols
;;
;;   Navigation:
;;   M-.                       ;; Jump to definition
;;   M-,                       ;; Pop back from definition
;;
;;   Inspector:
;;   C-c C-i                   ;; Inspect last sexp
;;   (in inspector: n=nav-index, k=nav-key, b=back, q=quit)
;;
;;   Connection:
;;   C-c C-j                   ;; Jack-in (start server)
;;   C-c C-q                   ;; Quit connection

;;; Code:

(require 'lisp-mode)
(require 'comint)
(require 'json)
(require 'xref)

;;; Customization

(defgroup spork nil
  "Major mode and nREPL integration for Spork."
  :group 'languages
  :prefix "spork-")

(defcustom spork-repl-buffer "*spork-repl*"
  "Name of the Spork REPL buffer."
  :type 'string
  :group 'spork)

(defcustom spork-default-host "127.0.0.1"
  "Default host for nREPL server."
  :type 'string
  :group 'spork)

(defcustom spork-default-port 7888
  "Default port for nREPL server."
  :type 'integer
  :group 'spork)

(defcustom spork-prompt-regexp "^[a-zA-Z0-9._-]+> "
  "Regexp to match REPL prompt (namespace followed by >)."
  :type 'regexp
  :group 'spork)

(defcustom spork-command "spork"
  "Command to run the Spork CLI.
This should be the global spork command installed via pipx or pip.
The command will be run from the project root directory."
  :type 'string
  :group 'spork)

;;; Namespace Commands

(defun spork-set-ns (ns-name)
  "Switch to namespace NS-NAME in the current REPL session."
  (interactive "sNamespace: ")
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (spork--send-message conn
                         `((op . "using-ns")
                           (ns . ,ns-name))
                         (lambda (response)
                           (let ((new-ns (cdr (assoc 'ns response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              ((spork--status-contains status "error")
                               (message "Error switching namespace: %s" error-msg))
                              (new-ns
                               (setf (spork-conn-namespace conn) new-ns)
                               (message "Switched to namespace: %s" new-ns))))))))

(defun spork-list-ns ()
  "List all loaded namespaces."
  (interactive)
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (spork--send-message conn
                         '((op . "ns-list"))
                         (lambda (response)
                           (let ((namespaces (cdr (assoc 'namespaces response)))
                                 (current-ns (cdr (assoc 'current-ns response))))
                             (with-help-window "*spork-namespaces*"
                               (princ "Loaded Namespaces:\n\n")
                               (if namespaces
                                   (dolist (ns (append namespaces nil))
                                     (princ (format "  %s%s\n" ns
                                                    (if (string= ns current-ns) " (current)" ""))))
                                 (princ "  (no namespaces loaded)\n"))
                               (princ (format "\nCurrent namespace: %s\n" current-ns))))))))

(defun spork-current-ns ()
  "Show the current namespace."
  (interactive)
  (if (spork--current-connection)
      (message "Current namespace: %s" (spork-conn-namespace (spork--current-connection)))
    (message "No active Spork connection")))

(defcustom spork-show-evaluation-result t
  "Whether to show evaluation results in the echo area."
  :type 'boolean
  :group 'spork)

;;; Syntax Table

(defvar spork-mode-syntax-table
  (let ((st (make-syntax-table lisp-mode-syntax-table)))
    ;; Comments: ; to end of line
    (modify-syntax-entry ?\; "<" st)
    (modify-syntax-entry ?\n ">" st)

    ;; Treat ? ! * + - / _ as word constituents for symbols like foo? bar! my-var
    (modify-syntax-entry ?? "w" st)
    (modify-syntax-entry ?! "w" st)
    (modify-syntax-entry ?* "w" st)
    (modify-syntax-entry ?+ "w" st)
    (modify-syntax-entry ?- "w" st)
    (modify-syntax-entry ?/ "w" st)
    (modify-syntax-entry ?_ "w" st)

    ;; Vectors and maps participate in sexp movement
    (modify-syntax-entry ?\[ "(" st)
    (modify-syntax-entry ?\] ")" st)
    (modify-syntax-entry ?{ "(" st)
    (modify-syntax-entry ?} ")" st)
    st)
  "Syntax table for `spork-mode'.")

;;; Font Lock (Syntax Highlighting)

(defconst spork--special-forms
  '("def" "defn" "defmacro" "defclass" "fn" "let" "set!"
    "if" "do" "while" "for" "loop" "recur" "match"
    "throw" "try" "catch" "finally"
    "async-for" "await" "yield" "yield-from"
    "import-macros" "import" "quote" "quasiquote"
    "unquote" "unquote-splicing" "with")
  "Special forms and core macros in Spork.")

(defconst spork--constants
  '("nil" "true" "false")
  "Literal constants in Spork.")

(defconst spork--builtins
  '("identity" "constantly" "complement" "comp" "partial" "apply"
    "map" "filter" "take" "drop" "cycle" "repeat" "iterate"
    "interleave" "interpose" "partition" "mapcat"
    "count" "reduce" "reductions" "into"
    "first" "rest" "nth" "seq" "cons" "conj"
    "assoc" "dissoc" "get" "zipmap" "group-by" "frequencies"
    "concat" "flatten" "distinct" "dedupe"
    "take-while" "drop-while" "keep" "keep-indexed" "map-indexed"
    "some" "every" "not-any" "not-every"
    "reverse" "sort" "sort-by" "split-at" "split-with"
    "partition-all" "doall" "dorun" "realized?"
    "inc" "dec" "even?" "odd?" "pos?" "neg?" "zero?"
    "empty" "empty?" "vec" "hash-map"
    ;; Type predicates
    "nil?" "some?" "string?" "number?" "int?" "float?" "bool?"
    "fn?" "symbol?" "keyword?" "vector?" "map?" "list?" "seq?"
    "coll?" "dict?")
  "Builtin functions from Spork's standard library.")

(defconst spork-font-lock-keywords
  (let* ((special-forms-re (regexp-opt spork--special-forms 'symbols))
         (constants-re     (regexp-opt spork--constants 'symbols))
         (builtins-re      (regexp-opt spork--builtins 'symbols))
         ;; symbol chars like foo-bar? or math/sin
         (name-chars       "[:word:][-_!?+*/.[:word:]]*"))
    `(
      ;; (defn name [args] ...)
      (,(concat
         "("
         "\\(defn\\|defmacro\\|defclass\\|def\\)"      ; group 1: keyword
         "[ \t]+"
         "\\(" name-chars "\\)")           ; group 2: name
       (1 font-lock-keyword-face)
       (2 font-lock-function-name-face))

      ;; Special forms in operator position: (if ...), (let ...), etc.
      (,(concat "(" "\\(" special-forms-re "\\)" )
       (1 font-lock-keyword-face))

      ;; Constants: nil, true, false
      (,constants-re . font-lock-constant-face)

      ;; Builtins: map, filter, etc.
      (,builtins-re . font-lock-builtin-face)

      ;; Keywords: :foo, :bar/baz
      ("\\(:\\(?:\\sw\\|\\s_\\)+\\)" 1 font-lock-constant-face)

      ;; Metadata marker: ^meta or ^int or ^async
      ("\\^\\(?:\\sw\\|\\s_\\)+" . font-lock-preprocessor-face)

      ;; Reader-ish chars: ', `, ~, ~@
      ("['`]" . font-lock-preprocessor-face)
      ("~@"   . font-lock-preprocessor-face)
      ("~"    . font-lock-preprocessor-face)
      ))
  "Font-lock keywords for `spork-mode'.")

;;; Indentation

;; Mark def-like forms
(dolist (sym '(defn def defmacro defclass fn))
  (put sym 'lisp-indent-function 'defun))

;; Custom indentation for a few forms
(dolist (pair '((let . 1)
                (loop . 1)
                (for . 1)
                (while . 1)
                (do . 0)
                (if . 1)
                (match . 1)
                (try . 0)
                (catch . 1)
                (with . 1)
                (async-for . 1)))
  (put (car pair) 'lisp-indent-function (cdr pair)))

;;; Connection State

(defvar-local spork-connection nil
  "The nREPL connection for this buffer.")

(defvar spork-connections nil
  "List of active nREPL connections.")

(defvar spork-message-id 0
  "Counter for nREPL message IDs.")

(defvar spork-pending-requests (make-hash-table :test 'equal)
  "Hash table of pending nREPL requests.")

;;; Connection Structure

(cl-defstruct (spork-conn (:constructor spork-conn-create))
  "Structure representing an nREPL connection."
  process
  host
  port
  session
  buffer
  output-buffer
  (namespace "user"))  ; Current namespace, default is "user"

;;; Utility Functions

(defun spork--next-message-id ()
  "Generate the next message ID."
  (setq spork-message-id (1+ spork-message-id))
  (number-to-string spork-message-id))

(defun spork--status-contains (status value)
  "Check if STATUS contains VALUE.
STATUS can be a list or vector (from JSON parsing)."
  (cond
   ((vectorp status) (seq-contains-p status value))
   ((listp status) (member value status))
   (t nil)))

(defun spork--read-port-file ()
  "Read port number from .nrepl-port file."
  (when (file-exists-p ".nrepl-port")
    (with-temp-buffer
      (insert-file-contents ".nrepl-port")
      (string-to-number (buffer-string)))))

(defun spork--ensure-connection ()
  "Ensure we have an active connection, or signal an error."
  (unless (spork--current-connection)
    (error "No active Spork connection. Use M-x spork-jack-in or M-x spork-connect")))

(defun spork--current-connection ()
  "Get the current connection."
  (or spork-connection
      (car spork-connections)))

;;; Network Communication

(defun spork--send-message (conn message callback)
  "Send MESSAGE to nREPL connection CONN and call CALLBACK with response."
  (let* ((id (spork--next-message-id))
         (session (spork-conn-session conn))
         (full-message (append message
                               `((id . ,id))
                               (when session `((session . ,session)))))
         (json-str (concat (json-encode full-message) "\n")))
    (puthash id callback spork-pending-requests)
    (process-send-string (spork-conn-process conn) json-str)))

(defun spork--handle-response (conn response)
  "Handle nREPL RESPONSE from CONN."
  (let ((id (cdr (assoc 'id response)))
        (status (cdr (assoc 'status response)))
        (value (cdr (assoc 'value response)))
        (out (cdr (assoc 'out response)))
        (error-msg (cdr (assoc 'error response)))
        (new-session (cdr (assoc 'new-session response))))

    ;; Handle session creation
    (when new-session
      (setf (spork-conn-session conn) new-session))

    ;; Call the pending callback
    (when id
      (let ((callback (gethash id spork-pending-requests)))
        (when callback
          (funcall callback response)
          (when (spork--status-contains status "done")
            (remhash id spork-pending-requests)
            ;; Ensure prompt is always present after done
            (spork--ensure-repl-prompt conn)))))))

(defun spork--process-filter (proc string)
  "Process filter for nREPL connection PROC receiving STRING."
  (let ((conn (process-get proc 'spork-connection)))
    (when conn
      (with-current-buffer (process-buffer proc)
        (goto-char (point-max))
        (insert string)

        ;; Process complete JSON messages (newline-delimited)
        (goto-char (point-min))
        (while (search-forward "\n" nil t)
          (let* ((line (buffer-substring-no-properties (point-min) (point)))
                 (response (ignore-errors (json-read-from-string line))))
            (when response
              (delete-region (point-min) (point))
              (spork--handle-response conn response)
              (goto-char (point-min)))))))))

(defun spork--process-sentinel (proc event)
  "Sentinel for nREPL connection PROC receiving EVENT."
  (let ((conn (process-get proc 'spork-connection)))
    (when conn
      (message "Spork nREPL connection closed: %s" (string-trim event))
      (setq spork-connections (delq conn spork-connections))
      (when (eq spork-connection conn)
        (setq spork-connection nil)))))

;;; Connection Management

(defun spork-connect (host port)
  "Connect to Spork nREPL server at HOST:PORT."
  (interactive
   (list (read-string "Host: " spork-default-host)
         (read-number "Port: " (or (spork--read-port-file) spork-default-port))))

  (let* ((buffer (generate-new-buffer " *spork-connection*"))
         (proc (open-network-stream "spork-nrepl" buffer host port))
         (conn (spork-conn-create
                :process proc
                :host host
                :port port
                :buffer buffer
                :output-buffer (get-buffer-create spork-repl-buffer))))

    (process-put proc 'spork-connection conn)
    (set-process-filter proc #'spork--process-filter)
    (set-process-sentinel proc #'spork--process-sentinel)
    (set-process-coding-system proc 'utf-8-unix 'utf-8-unix)

    (push conn spork-connections)
    (setq spork-connection conn)

    ;; Clone a session
    (spork--send-message conn
                         '((op . "clone"))
                         (lambda (response)
                           (message "Connected to Spork nREPL at %s:%s" host port)))

    ;; Set up REPL buffer
    (with-current-buffer (spork-conn-output-buffer conn)
      (unless (derived-mode-p 'spork-repl-mode)
        (spork-repl-mode))
      (setq spork-connection conn)
      (goto-char (point-max)))

    conn))

(defun spork--find-project-root ()
  "Find the Spork project root by looking for spork.it file.
Falls back to other markers if spork.it is not found."
  (or (locate-dominating-file default-directory "spork.it")
      (locate-dominating-file default-directory ".nrepl-port")
      (locate-dominating-file default-directory "pyproject.toml")
      default-directory))

(defun spork-jack-in ()
  "Start a Spork nREPL server and connect to it.
Uses the global spork command (from pipx or pip) and runs it from
the project root directory. The project root is found by searching
for a spork.it file."
  (interactive)
  (let* ((project-root (spork--find-project-root))
         (default-directory project-root)
         (buffer (get-buffer-create "*spork-server*"))
         (port (or (spork--read-port-file) spork-default-port))
         (spork-cmd spork-command))

    ;; Start the server from project root
    (with-current-buffer buffer
      (erase-buffer)
      (insert (format "Starting Spork nREPL server on port %d...\n" port))
      (insert (format "Project root: %s\n" project-root))
      (insert (format "Command: %s --nrepl --port %d\n\n" spork-cmd port))
      (let ((proc (start-process "spork-server" buffer
                                 spork-cmd
                                 "--nrepl"
                                 "--port" (number-to-string port))))
        (set-process-query-on-exit-flag proc nil)))

    ;; Wait a bit for server to start, then connect
    (run-with-timer 2 nil
                    (lambda ()
                      (condition-case err
                          (progn
                            (spork-connect spork-default-host port)
                            (message "Connected to Spork nREPL server at %s" project-root)
                            ;; Display REPL buffer in right split
                            (let ((repl-buffer (get-buffer spork-repl-buffer)))
                              (when repl-buffer
                                (display-buffer-in-side-window repl-buffer '((side . right))))))
                        (error (message "Failed to connect: %s. Make sure the server is running." (error-message-string err))))))))

(defun spork-quit ()
  "Close the current Spork nREPL connection."
  (interactive)
  (when (spork--current-connection)
    (let ((conn (spork--current-connection)))
      (spork--send-message conn
                           '((op . "close"))
                           (lambda (_response)
                             (message "Spork connection closed")))
      (delete-process (spork-conn-process conn))
      (setq spork-connections (delq conn spork-connections))
      (setq spork-connection nil))))

;;; REPL Buffer

(defun spork--insert-prompt (&optional input conn)
  "Insert a colored Spork prompt with optional INPUT text after it.
Uses the namespace from CONN if provided."
  (let* ((connection (or conn (spork--current-connection)))
         (ns (if connection (spork-conn-namespace connection) "user")))
    (insert (propertize ns 'face '(:foreground "blue")) "> " (or input ""))))

(defun spork--ensure-repl-prompt (conn)
  "Ensure REPL prompt is present at end of buffer for CONN."
  (with-current-buffer (spork-conn-output-buffer conn)
    (let ((inhibit-read-only t))
      (goto-char (point-max))
      ;; Check if we already have a prompt at the end
      (unless (save-excursion
                (beginning-of-line)
                (looking-at spork-prompt-regexp))
        (unless (bolp) (insert "\n"))
        (insert "\n")
        (spork--insert-prompt nil conn))
      (goto-char (point-max)))))

(defun spork--insert-repl-output (conn text)
  "Insert TEXT into CONN's REPL buffer."
  (with-current-buffer (spork-conn-output-buffer conn)
    (let ((inhibit-read-only t)
          (saved-input nil))
      (goto-char (point-max))
      ;; If we're on a prompt line, save and delete it
      (when (save-excursion
              (beginning-of-line)
              (looking-at spork-prompt-regexp))
        (beginning-of-line)
        (setq saved-input (buffer-substring (match-end 0) (point-max)))
        (delete-region (point) (point-max)))
      ;; Insert the output (add newline before if needed)
      (goto-char (point-max))
      (unless (bolp) (insert "\n"))
      (insert (propertize text 'face 'default))
      (goto-char (point-max))
      ;; Restore prompt with saved input (with blank line before)
      (when saved-input
        (unless (bolp) (insert "\n"))
        (insert "\n")
        (spork--insert-prompt saved-input conn)
        (goto-char (point-max)))
      ;; Scroll windows showing this buffer to the end
      (dolist (window (get-buffer-window-list (current-buffer) nil t))
        (set-window-point window (point-max))))))

(defun spork--insert-repl-result (conn result)
  "Insert RESULT into CONN's REPL buffer."
  (with-current-buffer (spork-conn-output-buffer conn)
    (let ((inhibit-read-only t)
          (saved-input nil))
      (goto-char (point-max))
      ;; If we're on a prompt line, save and delete it
      (when (save-excursion
              (beginning-of-line)
              (looking-at spork-prompt-regexp))
        (beginning-of-line)
        (setq saved-input (buffer-substring (match-end 0) (point-max)))
        (delete-region (point) (point-max)))
      (unless (bolp) (insert "\n"))
      (insert (propertize (format "=> %s\n" result) 'face 'font-lock-constant-face))
      ;; Restore prompt with saved input (with blank line before)
      (insert "\n")
      (spork--insert-prompt saved-input conn)
      (goto-char (point-max))
      ;; Scroll windows showing this buffer to the end
      (dolist (window (get-buffer-window-list (current-buffer) nil t))
        (set-window-point window (point-max))))))

(defun spork--insert-repl-error (conn error)
  "Insert ERROR into CONN's REPL buffer."
  (with-current-buffer (spork-conn-output-buffer conn)
    (let ((inhibit-read-only t)
          (saved-input nil))
      (goto-char (point-max))
      ;; If we're on a prompt line, save and delete it
      (when (save-excursion
              (beginning-of-line)
              (looking-at spork-prompt-regexp))
        (beginning-of-line)
        (setq saved-input (buffer-substring (match-end 0) (point-max)))
        (delete-region (point) (point-max)))
      (unless (bolp) (insert "\n"))
      (insert (propertize (format "Error: %s\n" error) 'face 'error))
      ;; Restore prompt with saved input (with blank line before)
      (insert "\n")
      (spork--insert-prompt saved-input conn)
      (goto-char (point-max))
      ;; Scroll windows showing this buffer to the end
      (dolist (window (get-buffer-window-list (current-buffer) nil t))
        (set-window-point window (point-max))))))

(defun spork-repl-send-input ()
  "Send the current input in the REPL buffer."
  (interactive)
  (message "spork-repl-send-input called!")
  (let* ((conn (spork--current-connection)))
    (unless conn
      (error "No active Spork connection"))

    (let* ((input-start (save-excursion
                          (goto-char (point-max))
                          (beginning-of-line)
                          (if (looking-at spork-prompt-regexp)
                              (match-end 0)
                            (point))))
           (input (string-trim (buffer-substring-no-properties input-start (point-max)))))

      (message "Input: '%s'" input)
      (when (not (string-empty-p input))
        (goto-char (point-max))
        (insert "\n")

        (spork--send-message conn
                             `((op . "eval")
                               (code . ,input)
                               (ns . ,(spork-conn-namespace conn)))
                             (lambda (response)
                               (let ((value (cdr (assoc 'value response)))
                                     (out (cdr (assoc 'out response)))
                                     (error-msg (cdr (assoc 'error response)))
                                     (status (cdr (assoc 'status response)))
                                     (new-ns (cdr (assoc 'ns response))))
                                 ;; Update namespace if server returns one
                                 (when new-ns
                                   (setf (spork-conn-namespace conn) new-ns))
                                 ;; Handle output
                                 (when out
                                   (spork--insert-repl-output conn out))

                                 (cond
                                  ;; Handle error status
                                  ((spork--status-contains status "error")
                                   (spork--insert-repl-error conn (or error-msg "Unknown error")))
                                  ;; Handle incomplete status (syntax errors)
                                  ((spork--status-contains status "incomplete")
                                   (spork--insert-repl-error conn "Incomplete expression (syntax error)"))
                                  ;; Handle done status
                                  ((spork--status-contains status "done")
                                   (cond
                                    (value (spork--insert-repl-result conn value))
                                    (t (spork--ensure-repl-prompt conn))))
                                  ;; Default case
                                  (t (spork--ensure-repl-prompt conn))))))))))

(defvar spork-repl-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'spork-repl-send-input)
    (define-key map (kbd "C-c C-d") #'spork-doc)
    (define-key map (kbd "C-c C-q") #'spork-quit)
    (define-key map (kbd "C-c C-m") #'spork-macroexpand)
    (define-key map (kbd "C-c C-t") #'spork-transpile)
    (define-key map (kbd "C-c C-i") #'spork-inspect)
    (define-key map (kbd "C-c C-p") #'spork-list-protocols)
    ;; Namespace commands
    (define-key map (kbd "C-c C-n") #'spork-set-ns)
    (define-key map (kbd "C-c n") #'spork-current-ns)
    (define-key map (kbd "C-c C-S-n") #'spork-list-ns)
    map)
  "Keymap for `spork-repl-mode'.")

(define-derived-mode spork-repl-mode fundamental-mode "Spork REPL"
  "Major mode for Spork REPL interaction.

\\{spork-repl-mode-map}"
  (setq-local comint-prompt-regexp spork-prompt-regexp)
  (setq-local comint-use-prompt-regexp t)
  (when (= (point-min) (point-max))
    (insert "Spork REPL\n")
    (insert "Type Spork expressions and press RET to evaluate.\n\n")
    (spork--insert-prompt nil nil)))

(defun spork-switch-to-repl ()
  "Switch to the Spork REPL buffer."
  (interactive)
  (if (spork--current-connection)
      (let ((conn (spork--current-connection)))
        (switch-to-buffer-other-window (spork-conn-output-buffer conn))
        (goto-char (point-max)))
    (message "No active Spork connection. Use M-x spork-jack-in or M-x spork-connect")))

;;; Evaluation

(defun spork-eval-code (code &optional show-result file-path)
  "Evaluate CODE and optionally SHOW-RESULT in echo area.
If FILE-PATH is provided, send it for namespace context."
  (spork--ensure-connection)
  (let* ((conn (spork--current-connection))
         (msg `((op . "eval")
                (code . ,code)
                (ns . ,(spork-conn-namespace conn)))))
    ;; Add file path if provided (for namespace resolution)
    (when file-path
      (setq msg (append msg `((file . ,file-path)))))
    (spork--send-message conn
                         msg
                         (lambda (response)
                           (let ((value (cdr (assoc 'value response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (out (cdr (assoc 'out response)))
                                 (status (cdr (assoc 'status response)))
                                 (new-ns (cdr (assoc 'ns response))))
                             ;; Update namespace if server returns one
                             (when new-ns
                               (setf (spork-conn-namespace conn) new-ns))

                             ;; Show output in REPL
                             (when out
                               (spork--insert-repl-output conn out))

                             (cond
                              ;; Handle incomplete status (syntax errors)
                              ((spork--status-contains status "incomplete")
                               (spork--insert-repl-error conn "Incomplete expression (syntax error)")
                               (message "Error: Incomplete expression (syntax error)"))
                              ;; Handle done status
                              ((spork--status-contains status "done")
                               (cond
                                (error-msg
                                 (spork--insert-repl-error conn error-msg)
                                 (message "Error: %s" error-msg))
                                (value
                                 (spork--insert-repl-result conn value)
                                 (when (or show-result spork-show-evaluation-result)
                                   (message "=> %s" value)))
                                (t
                                 (when show-result
                                   (spork--ensure-repl-prompt conn)
                                   (message "=> nil")))))))))))

(defun spork-eval-last-sexp ()
  "Evaluate the form before point."
  (interactive)
  (let ((code (buffer-substring-no-properties
               (save-excursion (backward-sexp) (point))
               (point))))
    (spork-eval-code code t (buffer-file-name))))

(defun spork-eval-current-sexp ()
  "Evaluate the form at or around point."
  (interactive)
  (save-excursion
    (let* ((start (progn
                    (if (looking-at "[[:space:]\n]")
                        (skip-chars-forward " \t\n"))
                    (if (or (looking-at "(")
                            (looking-back ")" 1))
                        (backward-up-list 1 t t)
                      (beginning-of-defun))
                    (point)))
           (end (progn
                  (forward-sexp)
                  (point)))
           (code (buffer-substring-no-properties start end)))
      (spork-eval-code code t))))

(defun spork-eval-defun-at-point ()
  "Evaluate the top-level form at point."
  (interactive)
  (save-excursion
    (end-of-defun)
    (let ((end (point)))
      (beginning-of-defun)
      (let ((code (buffer-substring-no-properties (point) end)))
        (spork-eval-code code t (buffer-file-name))))))

(defun spork-eval-region (start end)
  "Evaluate the region between START and END."
  (interactive "r")
  (let ((code (buffer-substring-no-properties start end)))
    (spork-eval-code code t (buffer-file-name))))

(defun spork-eval-buffer ()
  "Evaluate the entire buffer."
  (interactive)
  (let ((code (buffer-substring-no-properties (point-min) (point-max))))
    (spork-eval-code code t (buffer-file-name))))

(defun spork-load-file (filename)
  "Load FILENAME into the Spork REPL."
  (interactive (list (buffer-file-name)))
  (unless filename
    (error "Buffer is not visiting a file"))
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (with-temp-buffer
      (insert-file-contents filename)
      (let ((code (buffer-string)))
        (spork--send-message conn
                             `((op . "load-file")
                               (file . ,code)
                               (file-path . ,filename))
                             (lambda (response)
                               (let ((value (cdr (assoc 'value response)))
                                     (out (cdr (assoc 'out response)))
                                     (error-msg (cdr (assoc 'error response)))
                                     (status (cdr (assoc 'status response)))
                                     (new-ns (cdr (assoc 'ns response))))
                                 ;; Update namespace if server returns one
                                 (when new-ns
                                   (setf (spork-conn-namespace conn) new-ns))
                                 ;; Handle output
                                 (when out
                                   (spork--insert-repl-output conn out))

                                 ;; Handle results
                                 (cond
                                  ;; Handle incomplete status (syntax errors)
                                  ((spork--status-contains status "incomplete")
                                   (spork--insert-repl-error conn "Incomplete expression (syntax error)")
                                   (message "Error loading %s: Incomplete expression (syntax error)" filename))
                                  ;; Handle done status
                                  ((spork--status-contains status "done")
                                   (cond
                                    (error-msg
                                     (spork--insert-repl-error conn error-msg)
                                     (message "Error loading %s: %s" filename error-msg))
                                    (value
                                     (spork--insert-repl-result conn value)
                                     (message "Loaded %s" filename))
                                    (t
                                     (message "Loaded %s" filename))))))))))))

(defun spork-load-current-buffer ()
  "Load the current buffer into the Spork REPL."
  (interactive)
  (if (buffer-file-name)
      (spork-load-file (buffer-file-name))
    (spork-eval-buffer)))

;;; Documentation and Info

(defun spork-doc (symbol)
  "Show documentation for SYMBOL."
  (interactive (list (read-string "Symbol: " (thing-at-point 'symbol))))
  (if (spork--current-connection)
      (let ((conn (spork--current-connection)))
        (spork--send-message conn
                             `((op . "info")
                               (symbol . ,symbol))
                             (lambda (response)
                               (let ((doc (cdr (assoc 'doc response)))
                                     (status (cdr (assoc 'status response))))
                                 (if (and doc (spork--status-contains status "done"))
                                     (with-help-window "*spork-doc*"
                                       (princ (format "Documentation for %s:\n\n%s" symbol doc)))
                                   (message "No documentation found for %s" symbol))))))
    (message "No active Spork connection")))

(defun spork-info (symbol)
  "Show rich metadata for SYMBOL including type, arglists, protocol info."
  (interactive (list (read-string "Symbol: " (thing-at-point 'symbol))))
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (spork--send-message conn
                         `((op . "info")
                           (symbol . ,symbol))
                         (lambda (response)
                           (let ((name (cdr (assoc 'name response)))
                                 (ns (cdr (assoc 'ns response)))
                                 (type (cdr (assoc 'type response)))
                                 (doc (cdr (assoc 'doc response)))
                                 (arglists (cdr (assoc 'arglists response)))
                                 (protocol (cdr (assoc 'protocol response)))
                                 (methods (cdr (assoc 'methods response)))
                                 (impls (cdr (assoc 'impls response)))
                                 (source (cdr (assoc 'source response)))
                                 (status (cdr (assoc 'status response))))
                             (if (spork--status-contains status "done")
                                 (with-help-window "*spork-info*"
                                   (princ (format "Symbol: %s\n" (or name symbol)))
                                   (when ns
                                     (princ (format "Namespace: %s\n" ns)))
                                   (when type
                                     (princ (format "Type: %s\n" type)))
                                   (when arglists
                                     (princ (format "Arglists: %s\n"
                                                    (mapconcat (lambda (args)
                                                                 (format "[%s]" (mapconcat #'identity args " ")))
                                                               arglists " "))))
                                   (when protocol
                                     (princ (format "Protocol: %s\n" protocol)))
                                   (when methods
                                     (princ (format "Methods: %s\n"
                                                    (mapconcat #'identity (append methods nil) ", "))))
                                   (when impls
                                     (princ (format "Implementations: %s\n"
                                                    (mapconcat #'identity (append impls nil) ", "))))
                                   (when source
                                     (let ((file (cdr (assoc 'file source)))
                                           (line (cdr (assoc 'line source))))
                                       (when file
                                         (princ (format "Source: %s:%s\n" file (or line "?"))))))
                                   (when doc
                                     (princ (format "\nDocumentation:\n%s\n" doc))))
                               (message "No info found for %s" symbol)))))))

;;; Macroexpand

(defun spork-macroexpand ()
  "Macroexpand the form at point and display the result."
  (interactive)
  (spork--ensure-connection)
  (let* ((bounds (save-excursion
                   (if (looking-at "(")
                       (point)
                     (backward-up-list 1 t t)
                     (point))))
         (end (save-excursion
                (goto-char bounds)
                (forward-sexp)
                (point)))
         (code (buffer-substring-no-properties bounds end))
         (conn (spork--current-connection)))
    (spork--send-message conn
                         `((op . "macroexpand")
                           (code . ,code))
                         (lambda (response)
                           (let ((expansion (cdr (assoc 'expansion response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              (error-msg
                               (message "Macroexpand error: %s" error-msg))
                              ((and expansion (spork--status-contains status "done"))
                               (with-help-window "*spork-macroexpand*"
                                 (princ (format "Original:\n%s\n\nExpanded:\n%s" code expansion))))
                              (t
                               (message "No expansion available"))))))))

(defun spork-macroexpand-1 ()
  "Macroexpand the form at point one level (alias for macroexpand)."
  (interactive)
  (spork-macroexpand))

;;; Transpile to Python

(defun spork-transpile ()
  "Transpile the form at point to Python and display in the REPL buffer."
  (interactive)
  (spork--ensure-connection)
  (let* ((bounds (save-excursion
                   (if (looking-at "(")
                       (point)
                     (backward-up-list 1 t t)
                     (point))))
         (end (save-excursion
                (goto-char bounds)
                (forward-sexp)
                (point)))
         (code (buffer-substring-no-properties bounds end))
         (conn (spork--current-connection)))
    (spork--send-message conn
                         `((op . "transpile")
                           (code . ,code))
                         (lambda (response)
                           (let ((python-code (cdr (assoc 'python response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              (error-msg
                               (spork--insert-repl-error conn error-msg))
                              ((and python-code (spork--status-contains status "done"))
                               (spork--insert-repl-output
                                conn
                                (format ";;; Python output:\n%s" python-code)))
                              (t
                               (message "No Python output available"))))))))

(defun spork-transpile-defun ()
  "Transpile the top-level form (defun) at point to Python."
  (interactive)
  (save-excursion
    (beginning-of-defun)
    (spork-transpile)))

;;; Find Definition

(defun spork-find-definition (symbol)
  "Jump to the definition of SYMBOL."
  (interactive (list (or (thing-at-point 'symbol)
                         (read-string "Symbol: "))))
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (spork--send-message conn
                         `((op . "find-def")
                           (symbol . ,symbol))
                         (lambda (response)
                           (let ((file (cdr (assoc 'file response)))
                                 (line (cdr (assoc 'line response)))
                                 (col (cdr (assoc 'col response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              ((spork--status-contains status "error")
                               (message "Definition not found: %s" (or error-msg symbol)))
                              ((and file line)
                               ;; Push current location to xref stack (compatible with Emacs 28+)
                               (if (fboundp 'xref-push-marker-stack)
                                   (xref-push-marker-stack)
                                 (push-mark))
                               ;; Open file and go to line
                               (find-file file)
                               (goto-char (point-min))
                               (forward-line (1- line))
                               (when col
                                 (forward-char col))
                               (message "Found definition of %s" symbol))
                              (t
                               (message "Definition not found for %s" symbol))))))))

(defun spork-pop-find-definition-stack ()
  "Pop back to where `spork-find-definition' was invoked."
  (interactive)
  (if (fboundp 'xref-go-back)
      (xref-go-back)
    (if (fboundp 'xref-pop-marker-stack)
        (xref-pop-marker-stack)
      (pop-mark))))

;;; Inspector

(defvar spork-inspector-history nil
  "History of inspector handles for navigation.")

(defvar-local spork-inspector-handle nil
  "Current inspector handle in inspector buffer.")

(defun spork-inspect (code)
  "Inspect the result of evaluating CODE."
  (interactive
   (list (if (use-region-p)
             (buffer-substring-no-properties (region-beginning) (region-end))
           (read-string "Inspect: " (thing-at-point 'sexp)))))
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (spork--send-message conn
                         `((op . "inspect-start")
                           (code . ,code))
                         (lambda (response)
                           (let ((handle (cdr (assoc 'handle response)))
                                 (summary (cdr (assoc 'summary response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              ((spork--status-contains status "error")
                               (message "Inspector error: %s" (or error-msg "Unknown error")))
                              ((and handle summary)
                               (setq spork-inspector-history (list handle))
                               (spork--display-inspector handle summary code))
                              (t
                               (message "Could not inspect value"))))))))

(defun spork-inspect-last-sexp ()
  "Inspect the form before point."
  (interactive)
  (let ((code (buffer-substring-no-properties
               (save-excursion (backward-sexp) (point))
               (point))))
    (spork-inspect code)))

(defun spork--display-inspector (handle summary &optional code)
  "Display inspector buffer for HANDLE with SUMMARY.
CODE is the original expression if available."
  (let ((buf (get-buffer-create "*spork-inspector*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (spork-inspector-mode)
        (setq spork-inspector-handle handle)

        ;; Header
        (insert (propertize "Spork Inspector\n" 'face 'bold))
        (insert (make-string 40 ?-) "\n\n")

        ;; Original code if available
        (when code
          (insert (propertize "Expression: " 'face 'font-lock-keyword-face))
          (insert code "\n\n"))

        ;; Type
        (let ((type (cdr (assoc 'type summary))))
          (when type
            (insert (propertize "Type: " 'face 'font-lock-keyword-face))
            (insert (propertize type 'face 'font-lock-type-face) "\n")))

        ;; Value (for primitives)
        (let ((value (cdr (assoc 'value summary))))
          (when value
            (insert (propertize "Value: " 'face 'font-lock-keyword-face))
            (insert (propertize value 'face 'font-lock-constant-face) "\n")))

        ;; Count (for collections)
        (let ((count (cdr (assoc 'count summary))))
          (when count
            (insert (propertize "Count: " 'face 'font-lock-keyword-face))
            (insert (format "%s" count) "\n")))

        ;; Preview (for sequences)
        (let ((preview (cdr (assoc 'preview summary))))
          (when preview
            (insert "\n" (propertize "Preview:\n" 'face 'font-lock-keyword-face))
            (let ((idx 0))
              (dolist (item (append preview nil))
                (insert (format "  [%d] %s\n" idx item))
                (setq idx (1+ idx))))))

        ;; Keys (for maps)
        (let ((keys (cdr (assoc 'keys summary))))
          (when keys
            (insert "\n" (propertize "Keys:\n" 'face 'font-lock-keyword-face))
            (dolist (key (append keys nil))
              (insert (format "  %s\n" key)))))

        ;; Attrs (for objects)
        (let ((attrs (cdr (assoc 'attrs summary))))
          (when attrs
            (insert "\n" (propertize "Attributes:\n" 'face 'font-lock-keyword-face))
            (dolist (attr (append attrs nil))
              (insert (format "  .%s\n" attr)))))

        (insert "\n" (make-string 40 ?-) "\n")
        (insert (propertize "Commands: " 'face 'font-lock-comment-face))
        (insert "n=nav-to-idx  k=nav-to-key  q=quit  b=back\n")

        (goto-char (point-min))))
    (pop-to-buffer buf)))

(defun spork-inspector-nav-index (index)
  "Navigate to INDEX in current inspector value."
  (interactive "nIndex: ")
  (spork--ensure-connection)
  (unless spork-inspector-handle
    (error "No active inspector"))
  (let ((conn (spork--current-connection))
        (handle spork-inspector-handle))
    (spork--send-message conn
                         `((op . "inspect-nav")
                           (handle . ,handle)
                           (path . ,(vector index)))
                         (lambda (response)
                           (let ((new-handle (cdr (assoc 'handle response)))
                                 (summary (cdr (assoc 'summary response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              ((spork--status-contains status "error")
                               (message "Navigation error: %s" (or error-msg "Unknown")))
                              ((and new-handle summary)
                               (push new-handle spork-inspector-history)
                               (spork--display-inspector new-handle summary
                                                         (format "[%d]" index)))
                              (t
                               (message "Could not navigate"))))))))

(defun spork-inspector-nav-key (key)
  "Navigate to KEY in current inspector value."
  (interactive "sKey (use :key for keywords): ")
  (spork--ensure-connection)
  (unless spork-inspector-handle
    (error "No active inspector"))
  (let ((conn (spork--current-connection))
        (handle spork-inspector-handle))
    (spork--send-message conn
                         `((op . "inspect-nav")
                           (handle . ,handle)
                           (path . ,(vector key)))
                         (lambda (response)
                           (let ((new-handle (cdr (assoc 'handle response)))
                                 (summary (cdr (assoc 'summary response)))
                                 (error-msg (cdr (assoc 'error response)))
                                 (status (cdr (assoc 'status response))))
                             (cond
                              ((spork--status-contains status "error")
                               (message "Navigation error: %s" (or error-msg "Unknown")))
                              ((and new-handle summary)
                               (push new-handle spork-inspector-history)
                               (spork--display-inspector new-handle summary
                                                         (format "[%s]" key)))
                              (t
                               (message "Could not navigate"))))))))

(defun spork-inspector-back ()
  "Go back in inspector history."
  (interactive)
  (if (and spork-inspector-history (> (length spork-inspector-history) 1))
      (progn
        (pop spork-inspector-history)
        (let ((handle (car spork-inspector-history)))
          ;; Re-fetch the summary for this handle
          (message "Back to handle %s (history not fully implemented)" handle)))
    (message "No previous inspector state")))

(defun spork-inspector-quit ()
  "Quit the inspector."
  (interactive)
  (quit-window t))

(defvar spork-inspector-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "n") #'spork-inspector-nav-index)
    (define-key map (kbd "k") #'spork-inspector-nav-key)
    (define-key map (kbd "b") #'spork-inspector-back)
    (define-key map (kbd "q") #'spork-inspector-quit)
    (define-key map (kbd "RET") #'spork-inspector-nav-index)
    map)
  "Keymap for `spork-inspector-mode'.")

(define-derived-mode spork-inspector-mode special-mode "Spork Inspector"
  "Major mode for Spork value inspector.

\\{spork-inspector-mode-map}"
  (setq-local revert-buffer-function
              (lambda (_ignore-auto _noconfirm)
                (message "Refresh not implemented"))))

;;; Protocols

(defun spork-list-protocols ()
  "List all registered protocols."
  (interactive)
  (spork--ensure-connection)
  (let ((conn (spork--current-connection)))
    (spork--send-message conn
                         '((op . "protocols"))
                         (lambda (response)
                           (let ((protocols (cdr (assoc 'protocols response)))
                                 (status (cdr (assoc 'status response))))
                             (if (spork--status-contains status "done")
                                 (with-help-window "*spork-protocols*"
                                   (princ "Registered Protocols\n")
                                   (princ (make-string 40 ?=))
                                   (princ "\n\n")
                                   (if protocols
                                       (dolist (proto-pair protocols)
                                         (let* ((name (car proto-pair))
                                                (info (cdr proto-pair))
                                                (methods (cdr (assoc 'methods info)))
                                                (doc (cdr (assoc 'doc info)))
                                                (structural (cdr (assoc 'structural info)))
                                                (impls (cdr (assoc 'impls info))))
                                           (princ (format "%s%s\n"
                                                          (symbol-name name)
                                                          (if (eq structural t) " (structural)" "")))
                                           (when doc
                                             (princ (format "  %s\n" doc)))
                                           (when methods
                                             (princ (format "  Methods: %s\n"
                                                            (mapconcat #'identity
                                                                       (append methods nil) ", "))))
                                           (when impls
                                             (princ (format "  Implementations: %s\n"
                                                            (mapconcat #'identity
                                                                       (append impls nil) ", "))))
                                           (princ "\n")))
                                     (princ "No protocols registered.\n")))
                               (message "Failed to get protocols")))))))

;;; Completion

(defun spork-complete-at-point ()
  "Completion at point function for Spork."
  (let ((bounds (bounds-of-thing-at-point 'symbol)))
    (when bounds
      (list (car bounds)
            (cdr bounds)
            (completion-table-dynamic #'spork--completions)
            :annotation-function (lambda (_) " <spork>")))))

(defun spork--completions (prefix)
  "Get completions for PREFIX from nREPL server."
  (when (spork--current-connection)
    (let ((completions nil)
          (conn (spork--current-connection)))
      (spork--send-message conn
                           `((op . "complete")
                             (prefix . ,prefix))
                           (lambda (response)
                             (setq completions (cdr (assoc 'completions response)))))
      ;; Note: This is synchronous-ish, ideally we'd do better
      completions)))

;;; Keymap

(defvar spork-mode-map
  (let ((map (make-sparse-keymap)))
    (set-keymap-parent map lisp-mode-shared-map)
    (define-key map (kbd "C-c C-c") #'spork-eval-current-sexp)
    (define-key map (kbd "C-c C-e") #'spork-eval-last-sexp)
    (define-key map (kbd "C-c C-r") #'spork-eval-region)
    (define-key map (kbd "C-c C-k") #'spork-load-current-buffer)
    (define-key map (kbd "C-c C-b") #'spork-eval-buffer)
    (define-key map (kbd "C-c C-z") #'spork-switch-to-repl)
    (define-key map (kbd "C-c C-d") #'spork-doc)
    (define-key map (kbd "C-c C-j") #'spork-jack-in)
    (define-key map (kbd "C-c C-q") #'spork-quit)
    ;; Namespace commands
    (define-key map (kbd "C-c C-n") #'spork-set-ns)
    (define-key map (kbd "C-c n") #'spork-current-ns)
    (define-key map (kbd "C-c C-S-n") #'spork-list-ns)
    ;; Runtime features
    (define-key map (kbd "C-c C-m") #'spork-macroexpand)
    (define-key map (kbd "C-c C-t") #'spork-transpile)
    (define-key map (kbd "C-c g") #'spork-find-definition)
    (define-key map (kbd "C-c b") #'spork-pop-find-definition-stack)
    (define-key map (kbd "C-c C-i") #'spork-inspect-last-sexp)
    (define-key map (kbd "C-c i") #'spork-info)
    (define-key map (kbd "C-c C-p") #'spork-list-protocols)
    map)
  "Keymap for `spork-mode'.")

;;; Major Mode Definition

;;;###autoload
(define-derived-mode spork-mode prog-mode "Spork"
  "Major mode for editing Spork (Lisp to Python) with nREPL integration.

Spork is a Lisp dialect that compiles to Python, featuring immutable
data structures, pattern matching, macros, and seamless Python interop.

This mode provides syntax highlighting, Lisp-style indentation, and
full nREPL integration for interactive development.

Key bindings:
\\{spork-mode-map}"
  :syntax-table spork-mode-syntax-table

  ;; Font lock
  (setq-local font-lock-defaults '(spork-font-lock-keywords))

  ;; Comments
  (setq-local comment-start ";")
  (setq-local comment-end "")
  (setq-local comment-start-skip ";+[ \t]*")

  ;; Indentation
  (setq-local lisp-indent-function #'lisp-indent-function)
  (setq-local indent-line-function #'lisp-indent-line)
  (setq-local parse-sexp-ignore-comments t)

  ;; Completion
  (add-hook 'completion-at-point-functions #'spork-complete-at-point nil t)

  ;; Electric pair mode support
  (setq-local electric-pair-skip-whitespace 'chomp)
  (setq-local electric-pair-open-newline-between-pairs t))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.spork\\'" . spork-mode))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.spork\\'" . spork-mode))

(provide 'spork-mode)

;;; spork-mode.el ends here
