#!/usr/bin/env python3
"""
Security Scorer - Security dimension scoring module

This module provides comprehensive security assessment for Python scripts,
evaluating sensitive data exposure, safe file operations, command injection
prevention, and input validation quality.

Author: Claude Skills Engineering Team
Version: 2.0.0
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# =============================================================================
# CONSTANTS - Scoring thresholds and weights
# =============================================================================

# Maximum score per component (25 points each, 4 components = 100 total)
MAX_COMPONENT_SCORE: int = 25

# Minimum score floor (never go below 0)
MIN_SCORE: int = 0

# Security score thresholds for tier recommendations
SECURITY_SCORE_POWERFUL_TIER: int = 70  # Required for POWERFUL tier
SECURITY_SCORE_STANDARD_TIER: int = 50  # Required for STANDARD tier

# Scoring modifiers (magic numbers replaced with named constants)
BASE_SCORE_SENSITIVE_DATA: int = 25  # Start with full points
BASE_SCORE_FILE_OPS: int = 15  # Base score for file operations
BASE_SCORE_COMMAND_INJECTION: int = 25  # Start with full points
BASE_SCORE_INPUT_VALIDATION: int = 10  # Base score for input validation

# Penalty amounts (negative scoring)
CRITICAL_VULNERABILITY_PENALTY: int = -25  # Critical issues (hardcoded passwords, etc.)
HIGH_SEVERITY_PENALTY: int = -10  # High severity issues
MEDIUM_SEVERITY_PENALTY: int = -5  # Medium severity issues
LOW_SEVERITY_PENALTY: int = -2  # Low severity issues

# Bonus amounts (positive scoring)
SAFE_PATTERN_BONUS: int = 2  # Bonus for using safe patterns
GOOD_PRACTICE_BONUS: int = 3  # Bonus for good security practices

# =============================================================================
# PRE-COMPILED REGEX PATTERNS - Sensitive Data Detection
# =============================================================================

# Hardcoded credentials patterns (CRITICAL severity).
# Anchored to an assignment at statement position (start of line, optionally a
# dotted/underscored prefix such as `self.` or `OPENROUTER_`): an "api_key ="
# inside a string literal or help text (e.g. print("export API_KEY='...'"))
# is documentation, not a credential.
PATTERN_HARDCODED_PASSWORD = re.compile(
    r'^\s*(?:[\w.]*[._])?password\s*=\s*["\'][^"\']{4,}["\']',
    re.IGNORECASE | re.MULTILINE
)
PATTERN_HARDCODED_API_KEY = re.compile(
    r'^\s*(?:[\w.]*[._])?api_key\s*=\s*["\'][^"\']{8,}["\']',
    re.IGNORECASE | re.MULTILINE
)
PATTERN_HARDCODED_SECRET = re.compile(
    r'^\s*(?:[\w.]*[._])?secret\s*=\s*["\'][^"\']{4,}["\']',
    re.IGNORECASE | re.MULTILINE
)
PATTERN_HARDCODED_TOKEN = re.compile(
    r'^\s*(?:[\w.]*[._])?token\s*=\s*["\'][^"\']{8,}["\']',
    re.IGNORECASE | re.MULTILINE
)
PATTERN_HARDCODED_PRIVATE_KEY = re.compile(
    r'^\s*(?:[\w.]*[._])?private_key\s*=\s*["\'][^"\']{20,}["\']',
    re.IGNORECASE | re.MULTILINE
)
PATTERN_HARDCODED_AWS_KEY = re.compile(
    r'^\s*(?:[\w.]*[._])?aws_access_key\s*=\s*["\'][^"\']{16,}["\']',
    re.IGNORECASE | re.MULTILINE
)
PATTERN_HARDCODED_AWS_SECRET = re.compile(
    r'^\s*(?:[\w.]*[._])?aws_secret\s*=\s*["\'][^"\']{20,}["\']',
    re.IGNORECASE | re.MULTILINE
)

# Multi-line string patterns (CRITICAL severity). The delimiters must be a
# matched homogeneous pair (""" with """), and the sensitive word must sit in
# a key:value/key=value position — a docstring merely *mentioning* "token",
# or a cluster of mixed quotes like strip('"').strip("'"), is not a secret.
PATTERN_MULTILINE_STRING = re.compile(
    r'("""|\'\'\')(?:(?!\1).)*?(?:password|api_key|secret|token|private_key)\s*[:=](?:(?!\1).)*?\1',
    re.IGNORECASE | re.DOTALL
)

# F-string patterns (HIGH severity)
PATTERN_FSTRING_SENSITIVE = re.compile(
    r'f["\'].*?(?:password|api_key|secret|token)\s*=',
    re.IGNORECASE
)

# Base64 encoded secrets (MEDIUM severity)
PATTERN_BASE64_SECRET = re.compile(
    r'(?:base64|b64encode|b64decode)\s*\([^)]*(?:password|api_key|secret|token)',
    re.IGNORECASE
)

# JWT tokens (HIGH severity)
PATTERN_JWT_TOKEN = re.compile(
    r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*'
)

# Connection strings (HIGH severity)
PATTERN_CONNECTION_STRING = re.compile(
    r'(?:connection_string|conn_string|database_url)\s*=\s*["\'][^"\']*(?:password|pwd|passwd)[^"\']*["\']',
    re.IGNORECASE
)

# Safe credential patterns (environment variables are OK)
PATTERN_SAFE_ENV_VAR = re.compile(
    r'os\.(?:getenv|environ)\s*\(\s*["\'][^"\']+["\']',
    re.IGNORECASE
)

# =============================================================================
# PRE-COMPILED REGEX PATTERNS - Path Traversal Detection
# =============================================================================

# Basic path traversal patterns
PATTERN_PATH_TRAVERSAL_BASIC = re.compile(r'\.\.\/')
PATTERN_PATH_TRAVERSAL_WINDOWS = re.compile(r'\.\.\\')

# URL encoded path traversal (MEDIUM severity)
PATTERN_PATH_TRAVERSAL_URL_ENCODED = re.compile(
    r'%2e%2e%2f|%252e%252e%252f|\.\.%2f',
    re.IGNORECASE
)

# Unicode encoded path traversal (MEDIUM severity)
PATTERN_PATH_TRAVERSAL_UNICODE = re.compile(
    r'\\u002e\\u002e|\\uff0e\\uff0e|\u002e\u002e\/',
    re.IGNORECASE
)

# Null byte injection (HIGH severity)
PATTERN_NULL_BYTE = re.compile(r'%00|\\x00|\0')

# Risky file operation patterns
PATTERN_PATH_CONCAT = re.compile(
    r'open\s*\(\s*[^)]*\+',
    re.IGNORECASE
)
PATTERN_USER_INPUT_PATH = re.compile(
    r'\.join\s*\(\s*[^)]*input|os\.path\.join\s*\([^)]*request',
    re.IGNORECASE
)

# Safe file operation patterns
PATTERN_SAFE_BASENAME = re.compile(r'os\.path\.basename', re.IGNORECASE)
PATTERN_SAFE_PATHLIB = re.compile(r'pathlib\.Path\s*\(', re.IGNORECASE)
PATTERN_PATH_VALIDATION = re.compile(r'validate.*path', re.IGNORECASE)
PATTERN_PATH_RESOLVE = re.compile(r'\.resolve\s*\(', re.IGNORECASE)

# =============================================================================
# PRE-COMPILED REGEX PATTERNS - Command Injection Detection
# =============================================================================

# Dangerous patterns (CRITICAL severity)
PATTERN_OS_SYSTEM = re.compile(r'os\.system\s*\(')
PATTERN_OS_POPEN = re.compile(r'os\.popen\s*\(')
# Negative lookbehind: `run_eval(` and `self._recommend_retrieval(` contain
# the substring but are not calls to the builtin.
PATTERN_EVAL = re.compile(r'(?<![\w.])eval\s*\(')
PATTERN_EXEC = re.compile(r'(?<![\w.])exec\s*\(')

# Subprocess with shell=True (HIGH severity)
PATTERN_SUBPROCESS_SHELL_TRUE = re.compile(
    r'subprocess\.(?:call|run|Popen|check_output)\s*\([^)]*shell\s*=\s*True',
    re.IGNORECASE
)

# Asyncio subprocess shell (HIGH severity)
PATTERN_ASYNCIO_SHELL = re.compile(
    r'asyncio\.create_subprocess_shell\s*\(',
    re.IGNORECASE
)

# Pexpect spawn (HIGH severity)
PATTERN_PEXPECT_SPAWN = re.compile(r'pexpect\.spawn\s*\(', re.IGNORECASE)

# Safe subprocess patterns
PATTERN_SAFE_SUBPROCESS = re.compile(
    r'subprocess\.(?:run|call|Popen)\s*\([^)]*shell\s*=\s*False',
    re.IGNORECASE
)
PATTERN_SHLEX_QUOTE = re.compile(r'shlex\.quote', re.IGNORECASE)
PATTERN_SHLEX_SPLIT = re.compile(r'shlex\.split', re.IGNORECASE)

# =============================================================================
# PRE-COMPILED REGEX PATTERNS - Input Validation Detection
# =============================================================================

# Good validation patterns
PATTERN_ARGPARSE = re.compile(r'argparse')
PATTERN_TRY_EXCEPT = re.compile(r'try\s*:[\s\S]*?except\s+\w*Error')
PATTERN_INPUT_CHECK = re.compile(r'if\s+not\s+\w+\s*:')
PATTERN_ISINSTANCE = re.compile(r'isinstance\s*\(')
PATTERN_ISDIGIT = re.compile(r'\.isdigit\s*\(\)')
PATTERN_REGEX_VALIDATION = re.compile(r're\.(?:match|search|fullmatch)\s*\(')
PATTERN_VALIDATOR_CLASS = re.compile(r'Validator', re.IGNORECASE)
PATTERN_VALIDATE_FUNC = re.compile(r'validate', re.IGNORECASE)
PATTERN_SANITIZE_FUNC = re.compile(r'sanitize', re.IGNORECASE)


def _blank_docstrings(content: str) -> str:
    """Return `content` with module/class/function docstrings blanked out.

    Docstrings frequently *describe* dangerous constructs (`eval()`,
    `os.system()`, credential formats) without containing them. Blanking
    replaces each docstring line with an empty line, so the overall line
    numbering — and therefore finding locations — is unchanged. On any
    parse failure the original content is returned untouched.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return content
    lines = content.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(getattr(body[0], "value", None), ast.Constant)
                    and isinstance(body[0].value.value, str)):
                start = body[0].lineno - 1
                end = body[0].end_lineno or body[0].lineno
                for i in range(start, min(end, len(lines))):
                    lines[i] = "\n" if lines[i].endswith("\n") else ""
    return "".join(lines)


def _blank_comments(content: str) -> str:
    """Strip `#` comment text, keeping the `#` and the line count.

    A comment is documentation with the same status as a docstring. The comment
    explaining what `PATTERN_MULTILINE_STRING` matches necessarily contains a triple
    quote and the words it detects, and matched itself. Prose about a credential is
    not a credential.

    Uses tokenize so a `#` inside a string is untouched. On any tokenize failure the
    content is returned unchanged.
    """
    try:
        import io
        import tokenize
        lines = content.splitlines(keepends=True)
        for tok in tokenize.generate_tokens(io.StringIO(content).readline):
            if tok.type != tokenize.COMMENT:
                continue
            row, col = tok.start[0] - 1, tok.start[1]
            if row < len(lines):
                nl = "\n" if lines[row].endswith("\n") else ""
                lines[row] = lines[row][:col] + "#" + nl
        return "".join(lines)
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return content


def _blank_regex_literals(content: str) -> str:
    """Blank the contents of string literals passed to `re.compile(...)`.

    A regex pattern is never a credential. Without this, a detector whose own pattern
    mentions `password|api_key|secret|token` matches its own source — which is what
    `PATTERN_MULTILINE_STRING` did here, reporting a "multi-line string credential"
    at its own definition.

    Narrower than `_blank_string_literals`: the credential checks must keep ordinary
    string contents, because there the string genuinely is the finding. Only the
    arguments to `re.compile` are removed.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return content

    targets = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_re_compile = (
            (isinstance(func, ast.Attribute) and func.attr == "compile"
             and isinstance(func.value, ast.Name) and func.value.id == "re")
            or (isinstance(func, ast.Name) and func.id == "compile")
        )
        if not is_re_compile:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                targets.append(arg)

    if not targets:
        return content
    lines = content.splitlines(keepends=True)
    for node in sorted(targets, key=lambda n: (n.lineno, -n.end_lineno),
                       reverse=False):
        start, end = node.lineno - 1, (node.end_lineno or node.lineno)
        for i in range(start, min(end, len(lines))):
            lines[i] = "\n" if lines[i].endswith("\n") else ""
    return "".join(lines)


def _blank_string_literals(content: str) -> str:
    """Return `content` with the *contents* of every string literal blanked out.

    Docstring blanking is not enough on its own. A scanner, a linter, or any module
    that defines detection patterns holds the dangerous construct in an ordinary
    string literal:

        PATTERN_SHELL = r'asyncio\\.create_subprocess_shell\\s*\\('

    That is a pattern, not a call, and reporting it as a finding is a false positive —
    the exact one this scorer produced against its own source, costing real points and
    burying the genuine findings under nine that were its own grammar.

    Only apply this to checks that look for *calls* (command injection, path
    traversal). The credential check must keep string contents, because there the
    string literal is the finding.

    Quotes are preserved and each literal keeps its line span, so line numbers, and
    therefore finding locations, are unchanged. On any parse failure the original
    content is returned untouched.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return content

    lines = content.splitlines(keepends=True)
    spans = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.lineno is not None and node.end_lineno is not None):
            spans.append((node.lineno, node.col_offset,
                          node.end_lineno, node.end_col_offset))

    # Longest first, so a nested/overlapping span cannot shift an outer one's offsets.
    for lineno, col, end_lineno, end_col in sorted(
            spans, key=lambda s: (s[0], -s[2], -s[3])):
        if lineno == end_lineno:
            i = lineno - 1
            if i >= len(lines):
                continue
            line = lines[i]
            if end_col > len(line):
                continue
            lines[i] = line[:col] + (" " * (end_col - col)) + line[end_col:]
        else:
            # Multi-line literal: blank the interior, keep the line count intact.
            for i in range(lineno - 1, min(end_lineno, len(lines))):
                keep_prefix = lines[i][:col] if i == lineno - 1 else ""
                keep_suffix = lines[i][end_col:] if i == end_lineno - 1 else ""
                nl = "\n" if lines[i].endswith("\n") else ""
                lines[i] = keep_prefix + keep_suffix.rstrip("\n") + nl
    return "".join(lines)


class SecurityScorer:
    """
    Security dimension scoring engine.
    
    This class evaluates Python scripts for security vulnerabilities and best practices
    across four components:
    1. Sensitive Data Exposure Prevention (25% of security score)
    2. Safe File Operations (25% of security score)
    3. Command Injection Prevention (25% of security score)
    4. Input Validation Quality (25% of security score)
    
    Attributes:
        scripts: List of Python script paths to evaluate
        verbose: Whether to output verbose logging
    """
    
    def __init__(self, scripts: List[Path], verbose: bool = False):
        """
        Initialize the SecurityScorer.
        
        Args:
            scripts: List of Path objects pointing to Python scripts
            verbose: Enable verbose output for debugging
        """
        self.scripts = scripts
        self.verbose = verbose
        self._findings: List[str] = []
        
    def _log_verbose(self, message: str) -> None:
        """Log verbose message if verbose mode is enabled."""
        if self.verbose:
            print(f"[SECURITY] {message}")
            
    def _get_script_content(self, script_path: Path) -> Optional[str]:
        """
        Safely read script content, with docstrings blanked.

        Docstrings are documentation: a scanner that lists the patterns it
        detects (or a module explaining `os.system` risks) must not flag its
        own prose. Line numbers are preserved so findings stay accurate.

        Args:
            script_path: Path to the Python script

        Returns:
            Script content as string, or None if read fails
        """
        try:
            raw = script_path.read_text(encoding='utf-8')
            return _blank_regex_literals(_blank_comments(_blank_docstrings(raw)))
        except Exception as e:
            self._log_verbose(f"Failed to read {script_path}: {e}")
            return None

    def _get_code_only(self, script_path: Path) -> Optional[str]:
        """Script content with docstrings *and* string-literal contents blanked.

        Use for checks that look for dangerous **calls**. A construct appearing inside
        a string is a pattern, an error message, or a doc example — not an invocation.
        Do not use for the credential check, where the string is the finding.
        """
        content = self._get_script_content(script_path)
        return None if content is None else _blank_string_literals(content)
            
    def _clamp_score(self, score: int) -> int:
        """
        Clamp score to valid range [MIN_SCORE, MAX_COMPONENT_SCORE].
        
        Args:
            score: Raw score value
            
        Returns:
            Score clamped to valid range
        """
        return max(MIN_SCORE, min(score, MAX_COMPONENT_SCORE))
        
    def _score_patterns(
        self,
        content: str,
        script_name: str,
        dangerous_patterns: List[Tuple[re.Pattern, str, int]],
        safe_patterns: List[Tuple[re.Pattern, str, int]],
        base_score: int
    ) -> Tuple[int, List[str]]:
        """
        Generic pattern scoring method.
        
        This method evaluates a script against lists of dangerous and safe patterns,
        applying penalties for dangerous patterns found and bonuses for safe patterns.
        
        Args:
            content: Script content to analyze
            script_name: Name of the script (for findings)
            dangerous_patterns: List of (pattern, description, penalty) tuples
            safe_patterns: List of (pattern, description, bonus) tuples
            base_score: Starting score before adjustments
            
        Returns:
            Tuple of (final_score, findings_list)
        """
        score = base_score
        findings = []
        
        # Check for dangerous patterns
        for pattern, description, penalty in dangerous_patterns:
            matches = pattern.findall(content)
            if matches:
                score += penalty  # Penalty is negative
                findings.append(f"{script_name}: {description} ({len(matches)} occurrence(s))")
                
        # Check for safe patterns
        for pattern, description, bonus in safe_patterns:
            if pattern.search(content):
                score += bonus
                self._log_verbose(f"Safe pattern found in {script_name}: {description}")
                
        return self._clamp_score(score), findings
        
    def score_sensitive_data_exposure(self) -> Tuple[float, List[str]]:
        """
        Score sensitive data exposure prevention.
        
        Evaluates scripts for:
        - Hardcoded passwords, API keys, secrets, tokens, private keys
        - Multi-line string credentials
        - F-string sensitive data
        - Base64 encoded secrets
        - JWT tokens
        - Connection strings with credentials
        
        Returns:
            Tuple of (average_score, findings_list)
        """
        if not self.scripts:
            return float(MAX_COMPONENT_SCORE), []
            
        scores = []
        all_findings = []
        
        # Define dangerous patterns with severity-based penalties
        dangerous_patterns = [
            (PATTERN_HARDCODED_PASSWORD, 'hardcoded password', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_HARDCODED_API_KEY, 'hardcoded API key', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_HARDCODED_SECRET, 'hardcoded secret', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_HARDCODED_TOKEN, 'hardcoded token', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_HARDCODED_PRIVATE_KEY, 'hardcoded private key', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_HARDCODED_AWS_KEY, 'hardcoded AWS key', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_HARDCODED_AWS_SECRET, 'hardcoded AWS secret', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_MULTILINE_STRING, 'multi-line string credential', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_FSTRING_SENSITIVE, 'f-string sensitive data', HIGH_SEVERITY_PENALTY),
            (PATTERN_BASE64_SECRET, 'base64 encoded secret', MEDIUM_SEVERITY_PENALTY),
            (PATTERN_JWT_TOKEN, 'JWT token in code', HIGH_SEVERITY_PENALTY),
            (PATTERN_CONNECTION_STRING, 'connection string with credentials', HIGH_SEVERITY_PENALTY),
        ]
        
        # Safe patterns get bonus points
        safe_patterns = [
            (PATTERN_SAFE_ENV_VAR, 'safe environment variable usage', SAFE_PATTERN_BONUS),
        ]
        
        for script_path in self.scripts:
            content = self._get_script_content(script_path)
            if content is None:
                continue
                
            score, findings = self._score_patterns(
                content=content,
                script_name=script_path.name,
                dangerous_patterns=dangerous_patterns,
                safe_patterns=safe_patterns,
                base_score=BASE_SCORE_SENSITIVE_DATA
            )
            
            scores.append(score)
            all_findings.extend(findings)
            
        avg_score = sum(scores) / len(scores) if scores else 0.0
        return avg_score, all_findings
        
    def score_safe_file_operations(self) -> Tuple[float, List[str]]:
        """
        Score safe file operations.
        
        Evaluates scripts for:
        - Path traversal vulnerabilities (basic, URL-encoded, Unicode, null bytes)
        - Unsafe path construction
        - Safe patterns (pathlib, basename, validation)
        
        Returns:
            Tuple of (average_score, findings_list)
        """
        if not self.scripts:
            return float(MAX_COMPONENT_SCORE), []
            
        scores = []
        all_findings = []
        
        # Dangerous patterns with severity-based penalties
        dangerous_patterns = [
            (PATTERN_PATH_TRAVERSAL_BASIC, 'basic path traversal', HIGH_SEVERITY_PENALTY),
            (PATTERN_PATH_TRAVERSAL_WINDOWS, 'Windows-style path traversal', HIGH_SEVERITY_PENALTY),
            (PATTERN_PATH_TRAVERSAL_URL_ENCODED, 'URL-encoded path traversal', HIGH_SEVERITY_PENALTY),
            (PATTERN_PATH_TRAVERSAL_UNICODE, 'Unicode-encoded path traversal', HIGH_SEVERITY_PENALTY),
            (PATTERN_NULL_BYTE, 'null byte injection', HIGH_SEVERITY_PENALTY),
            (PATTERN_PATH_CONCAT, 'potential path injection via concatenation', MEDIUM_SEVERITY_PENALTY),
            (PATTERN_USER_INPUT_PATH, 'user input in path construction', MEDIUM_SEVERITY_PENALTY),
        ]
        
        # Safe patterns get bonus points
        safe_patterns = [
            (PATTERN_SAFE_BASENAME, 'uses basename for safety', SAFE_PATTERN_BONUS),
            (PATTERN_SAFE_PATHLIB, 'uses pathlib', SAFE_PATTERN_BONUS),
            (PATTERN_PATH_VALIDATION, 'path validation', SAFE_PATTERN_BONUS),
            (PATTERN_PATH_RESOLVE, 'path resolution', SAFE_PATTERN_BONUS),
        ]
        
        for script_path in self.scripts:
            content = self._get_code_only(script_path)
            if content is None:
                continue
                
            score, findings = self._score_patterns(
                content=content,
                script_name=script_path.name,
                dangerous_patterns=dangerous_patterns,
                safe_patterns=safe_patterns,
                base_score=BASE_SCORE_FILE_OPS
            )
            
            scores.append(score)
            all_findings.extend(findings)
            
        avg_score = sum(scores) / len(scores) if scores else 0.0
        return avg_score, all_findings
        
    def score_command_injection_prevention(self) -> Tuple[float, List[str]]:
        """
        Score command injection prevention.
        
        Evaluates scripts for:
        - os.system(), os.popen() usage
        - subprocess with shell=True
        - eval(), exec() usage
        - asyncio.create_subprocess_shell()
        - pexpect.spawn()
        - Safe patterns (shlex.quote, shell=False)
        
        Returns:
            Tuple of (average_score, findings_list)
        """
        if not self.scripts:
            return float(MAX_COMPONENT_SCORE), []
            
        scores = []
        all_findings = []
        
        # Dangerous patterns with severity-based penalties
        dangerous_patterns = [
            (PATTERN_OS_SYSTEM, 'os.system usage - potential command injection', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_OS_POPEN, 'os.popen usage', HIGH_SEVERITY_PENALTY),
            (PATTERN_EVAL, 'eval usage - code injection risk', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_EXEC, 'exec usage - code injection risk', CRITICAL_VULNERABILITY_PENALTY),
            (PATTERN_SUBPROCESS_SHELL_TRUE, 'subprocess with shell=True', HIGH_SEVERITY_PENALTY),
            (PATTERN_ASYNCIO_SHELL, 'asyncio.create_subprocess_shell()', HIGH_SEVERITY_PENALTY),
            (PATTERN_PEXPECT_SPAWN, 'pexpect.spawn()', MEDIUM_SEVERITY_PENALTY),
        ]
        
        # Safe patterns get bonus points
        safe_patterns = [
            (PATTERN_SAFE_SUBPROCESS, 'safe subprocess usage (shell=False)', GOOD_PRACTICE_BONUS),
            (PATTERN_SHLEX_QUOTE, 'shell escaping with shlex.quote', GOOD_PRACTICE_BONUS),
            (PATTERN_SHLEX_SPLIT, 'safe argument splitting with shlex.split', GOOD_PRACTICE_BONUS),
        ]
        
        for script_path in self.scripts:
            content = self._get_code_only(script_path)
            if content is None:
                continue
                
            score, findings = self._score_patterns(
                content=content,
                script_name=script_path.name,
                dangerous_patterns=dangerous_patterns,
                safe_patterns=safe_patterns,
                base_score=BASE_SCORE_COMMAND_INJECTION
            )
            
            scores.append(score)
            all_findings.extend(findings)
            
        avg_score = sum(scores) / len(scores) if scores else 0.0
        return avg_score, all_findings
        
    def score_input_validation(self) -> Tuple[float, List[str]]:
        """
        Score input validation quality.
        
        Evaluates scripts for:
        - argparse usage for CLI validation
        - Error handling patterns
        - Type checking (isinstance)
        - Regex validation
        - Validation/sanitization functions
        
        Returns:
            Tuple of (average_score, suggestions_list)
        """
        if not self.scripts:
            return float(MAX_COMPONENT_SCORE), []
            
        scores = []
        suggestions = []
        
        # Good validation patterns (each gives bonus points)
        validation_patterns = [
            (PATTERN_ARGPARSE, GOOD_PRACTICE_BONUS),
            (PATTERN_TRY_EXCEPT, SAFE_PATTERN_BONUS),
            (PATTERN_INPUT_CHECK, SAFE_PATTERN_BONUS),
            (PATTERN_ISINSTANCE, SAFE_PATTERN_BONUS),
            (PATTERN_ISDIGIT, SAFE_PATTERN_BONUS),
            (PATTERN_REGEX_VALIDATION, SAFE_PATTERN_BONUS),
            (PATTERN_VALIDATOR_CLASS, GOOD_PRACTICE_BONUS),
            (PATTERN_VALIDATE_FUNC, SAFE_PATTERN_BONUS),
            (PATTERN_SANITIZE_FUNC, SAFE_PATTERN_BONUS),
        ]
        
        for script_path in self.scripts:
            content = self._get_script_content(script_path)
            if content is None:
                continue
                
            score = BASE_SCORE_INPUT_VALIDATION
            
            # Check for validation patterns
            for pattern, bonus in validation_patterns:
                if pattern.search(content):
                    score += bonus
                    
            scores.append(self._clamp_score(score))
            
        avg_score = sum(scores) / len(scores) if scores else 0.0
        
        if avg_score < 15:
            suggestions.append("Add input validation with argparse, type checking, and error handling")
            
        return avg_score, suggestions
        
    def get_overall_score(self) -> Dict[str, Any]:
        """
        Calculate overall security score and return detailed results.
        
        Returns:
            Dictionary containing:
            - overall_score: Weighted average of all components
            - components: Individual component scores
            - findings: List of security issues found
            - suggestions: Improvement suggestions
        """
        # Score each component
        sensitive_score, sensitive_findings = self.score_sensitive_data_exposure()
        file_ops_score, file_ops_findings = self.score_safe_file_operations()
        command_injection_score, command_findings = self.score_command_injection_prevention()
        input_validation_score, input_suggestions = self.score_input_validation()
        
        # Calculate overall score on a 0-100 scale. Each component is already
        # scored out of MAX_COMPONENT_SCORE (25), so the four sum to 100 --
        # averaging them instead capped the result at 25, which made the
        # 70/50 tier thresholds and the 30-point critical cap below unreachable.
        overall_score = (
            sensitive_score +
            file_ops_score +
            command_injection_score +
            input_validation_score
        )
        
        # Collect all findings
        all_findings = sensitive_findings + file_ops_findings + command_findings
        
        # Generate suggestions based on findings
        suggestions = input_suggestions.copy()
        if sensitive_findings:
            suggestions.append("Remove hardcoded credentials and use environment variables or secure config")
        if file_ops_findings:
            suggestions.append("Validate and sanitize file paths, use pathlib for safe path handling")
        if command_findings:
            suggestions.append("Avoid shell=True in subprocess, use shlex.quote for shell arguments")
            
        # Critical vulnerability check - if any critical issues, cap the score.
        # Two groups, deliberately read from two different views of the source:
        #   - credential patterns need string contents intact; the literal IS the
        #     finding, so they run against comment/docstring-blanked source only.
        #   - call patterns must NOT see string contents, or a detector listing
        #     "os.system" in a pattern flags itself as calling it.
        credential_patterns = [
            PATTERN_HARDCODED_PASSWORD, PATTERN_HARDCODED_API_KEY,
            PATTERN_HARDCODED_PRIVATE_KEY,
        ]
        call_patterns = [PATTERN_OS_SYSTEM, PATTERN_EVAL, PATTERN_EXEC]

        has_critical = False
        for script_path in self.scripts:
            documented = self._get_script_content(script_path)
            if documented is not None and any(p.search(documented)
                                              for p in credential_patterns):
                has_critical = True
                break
            code = self._get_code_only(script_path)
            if code is not None and any(p.search(code) for p in call_patterns):
                has_critical = True
                break


        if has_critical:
            overall_score = min(overall_score, 30)  # Cap at 30 if critical vulnerabilities exist
            
        return {
            'overall_score': round(overall_score, 1),
            'components': {
                'sensitive_data_exposure': round(sensitive_score, 1),
                'safe_file_operations': round(file_ops_score, 1),
                'command_injection_prevention': round(command_injection_score, 1),
                'input_validation': round(input_validation_score, 1),
            },
            'findings': all_findings,
            'suggestions': suggestions,
            'has_critical_vulnerabilities': has_critical,
        }


# =============================================================================
# CLI - this module is documented as a runnable tool, so it needs an entrypoint.
# Without one it produced no output and exited 0, which reads as "passed" to any
# CI gate keying on the exit code.
# =============================================================================

def discover_scripts(skill_path: Path) -> List[Path]:
    """Find the Python scripts in a skill, excluding caches and test files."""
    return [
        p for p in sorted(skill_path.rglob("*.py"))
        if "__pycache__" not in p.parts and not p.name.startswith("test_")
    ]


def format_report(skill_path: Path, result: Dict[str, Any], script_count: int) -> str:
    """Render a human-readable security report."""
    lines = [
        "=" * 60,
        "SECURITY ASSESSMENT REPORT",
        "=" * 60,
        f"Skill: {skill_path}",
        f"Scripts scanned: {script_count}",
        f"Overall Score: {result['overall_score']}/100",
        "",
        "COMPONENTS:",
    ]

    for name, score in result["components"].items():
        label = name.replace("_", " ").title()
        lines.append(f"  {label}: {score}/{MAX_COMPONENT_SCORE}")

    findings = result.get("findings", [])
    lines.extend(["", f"FINDINGS: {len(findings)}"])
    for finding in findings:
        lines.append(f"  - {finding}")

    suggestions = result.get("suggestions", [])
    if suggestions:
        lines.append("")
        lines.append("SUGGESTIONS:")
        for suggestion in suggestions:
            lines.append(f"  - {suggestion}")

    if result.get("has_critical_vulnerabilities"):
        lines.extend(["", "CRITICAL VULNERABILITIES DETECTED - score capped at 30"])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score the security posture of a skill's Python scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 security_scorer.py path/to/skill
  python3 security_scorer.py path/to/skill --json
  python3 security_scorer.py path/to/skill --minimum-score 70

Exit codes:
  0  score meets the minimum and no critical vulnerabilities were found
  1  score below --minimum-score, or a critical vulnerability was found
  2  the skill path is invalid
""",
    )
    parser.add_argument("skill_path", help="Path to the skill directory to assess")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--minimum-score",
        type=float,
        default=None,
        help="Fail with exit code 1 if the score falls below this value (0-100)",
    )
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    if not skill_path.is_dir():
        print(f"Error: not a directory: {skill_path}", file=sys.stderr)
        return 2

    scripts = discover_scripts(skill_path)
    if not scripts:
        # No scripts means no script-level attack surface, not a failure.
        result = {
            "overall_score": 100.0,
            "components": {
                "sensitive_data_exposure": float(MAX_COMPONENT_SCORE),
                "safe_file_operations": float(MAX_COMPONENT_SCORE),
                "command_injection_prevention": float(MAX_COMPONENT_SCORE),
                "input_validation": float(MAX_COMPONENT_SCORE),
            },
            "findings": [],
            "suggestions": [],
            "has_critical_vulnerabilities": False,
            "note": "No Python scripts found - no script security concerns",
        }
    else:
        result = SecurityScorer(scripts, verbose=args.verbose).get_overall_score()

    if args.json:
        payload = dict(result)
        payload["skill_path"] = str(skill_path)
        payload["scripts_scanned"] = len(scripts)
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(skill_path, result, len(scripts)))

    if result.get("has_critical_vulnerabilities"):
        return 1
    if args.minimum_score is not None and result["overall_score"] < args.minimum_score:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())