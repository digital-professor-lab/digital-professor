"""Math check: is the student's answer correct, by computation rather than by a model's opinion?

``check_math`` returns a ``MathCheck`` record (``specs/tutoring-engine.md`` Appendix A) with one of four
statuses and never raises:

* ``correct``    an expression in the message is proved equal to the expected result;
* ``incorrect``  the student's final answer was read and is proved different;
* ``unknown``    there is math in the message, but nothing could be proved either way;
* ``absent``     the message contains no math.

Two kinds of problem can be checked:

* an indefinite integral: the answer is differentiated and compared with the integrand;
* a derivative: the answer is compared with the derivative that SymPy computes.

The check comes from the Question Schema's ``answer_verification`` payload when the builder stored one.
Otherwise ``derive_answer_check`` reads the function out of the question's own wording ("Differentiate
sin(x^3)", "Evaluate the integral of x cos(x) dx"). Any other question returns ``unknown`` with reason
``no_answer_check``.

Student text is never evaluated as code. An expression is parsed only after every name in it has been
checked against a short list of functions and single-letter variables.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

_FUNCTIONS = ("sin", "cos", "tan", "sec", "csc", "cot", "log", "exp", "sqrt", "asin", "acos", "atan")
_ALLOWED_NAMES = frozenset(_FUNCTIONS) | {"pi", "E"}
_ALLOWED_CHARS = re.compile(r"^[0-9a-zA-Z+\-*/().,\s]*$")
_CONSTANT = re.compile(r"\+\s*[Cc]\b")
_MATH_SIGNAL = re.compile(r"[=+*/^]|\d|\\[a-z]+|\b(?:sin|cos|tan|sec|log|ln|exp|sqrt)\b", re.IGNORECASE)
_MAX_EXPRESSION_CHARS = 160
_MAX_CANDIDATES = 8


def math_check(status: str, *, reason: str | None = None, method: str | None = None,
               flags: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"status": status, "reason": reason, "method": method, "flags": list(flags)}


def check_math(student_text: str, answer_verification: Mapping[str, Any] | None, *,
               final_answer: str | None = None) -> dict[str, Any]:
    """Check the message against the question's ``answer_verification`` payload. Never raises."""
    stated = _to_sympy_text(final_answer) if final_answer else ""
    candidates = [c for c in ([stated] if stated else []) + extract_candidates(student_text) if c]
    candidates = list(dict.fromkeys(candidates))[:_MAX_CANDIDATES]
    if not candidates or not (final_answer or _MATH_SIGNAL.search(student_text)):
        return math_check("absent")
    check = answer_verification or {}
    variable = check.get("variable")
    integrand, derivative_of = check.get("integrand"), check.get("derivative_of")
    if check.get("value") is not None:
        return _check_value(student_text, str(check["value"]), stated)
    if not (variable and (integrand or derivative_of)):
        return math_check("unknown", reason="no_answer_check")
    try:
        import sympy
    except ImportError:
        return math_check("unknown", reason="no_answer_check")
    symbol = sympy.Symbol(str(variable))
    try:
        if integrand:
            expected = _parse(str(integrand), sympy)
        else:
            function = _parse(str(derivative_of), sympy)
            expected = None if function is None else sympy.diff(function, symbol)
    except Exception:
        expected = None
    if expected is None:
        return math_check("unknown", reason="no_answer_check")
    parsed_any = stated_parsed = False
    for candidate in candidates:
        expression = _parse(candidate, sympy)
        if expression is None:
            continue
        parsed_any = True
        stated_parsed = stated_parsed or candidate == stated
        try:
            value = sympy.diff(expression, symbol) if integrand else expression
            if sympy.simplify(value - expected) == 0:
                source = final_answer or student_text
                flags = ("missing_constant",) if integrand and not _CONSTANT.search(source) else ()
                return math_check("correct", method="symbolic", flags=flags)
        except Exception:       # sympy can fail on odd input; that proves nothing
            continue
    if stated_parsed:                # the stated final answer was read and is not the answer
        return math_check("incorrect", method="symbolic")
    if not parsed_any and not final_answer and not _MATH_SIGNAL.search(student_text):
        return math_check("absent")
    return math_check("unknown", reason="equivalence_unproven" if parsed_any else "parse_failed")


def _check_value(student_text: str, value: str, stated: str) -> dict[str, Any]:
    """A question whose answer is one number (a definite integral, a limit).

    Numbers turn up all through a student's working, so only a stated final answer or what follows the
    last "=" is compared; anything else proves nothing.
    """
    try:
        import sympy
    except ImportError:
        return math_check("unknown", reason="no_answer_check")
    expected = _parse(value, sympy)
    if expected is None:
        return math_check("unknown", reason="no_answer_check")
    tail = _to_sympy_text(re.split(r"[\n;]|\.\s|\.$|,\s", student_text.rsplit("=", 1)[1])[0]) if "=" in student_text else ""
    tail = re.sub(r"\s*[a-zA-Z]{2,}.*$", "", tail).strip() if tail and _parse(tail, sympy) is None else tail   # "200*pi cm^3/s"
    read_any = False
    for candidate in dict.fromkeys(c for c in (stated, tail) if c):
        expression = _parse(candidate, sympy)
        if expression is None or expression.free_symbols:
            continue
        read_any = True
        try:
            if sympy.simplify(expression - expected) == 0 or abs(float(sympy.N(expression - expected))) <= 1e-3 * max(
                    1.0, abs(float(sympy.N(expected)))):
                return math_check("correct", method="symbolic")
        except Exception:
            continue
    return math_check("incorrect", method="symbolic") if read_any else math_check("unknown", reason="no_final_value")


_DEFINITE_PROMPT = re.compile(
    r"integral\s+of\s+(?P<f>.+?)\s*(?:d\s*x\s*)?,?\s+from\s+(?:x\s*=\s*)?(?P<a>[-\w./*^()]+)\s+to\s+"
    r"(?:x\s*=\s*)?(?P<b>[-\w./*^()]+)", re.IGNORECASE)
_LIMIT_PROMPT = re.compile(
    r"limit\s+of\s+(?P<f>.+?)\s+as\s+x\s*(?:approaches|goes\s+to|tends\s+to|->|→)\s*(?P<a>[-\w./*^()]+)", re.IGNORECASE)
_DERIVATIVE_PROMPT = re.compile(
    r"(?:dif+\w*ntiat\w*|find\s+the\s+derivative\s+of|derivative\s+of|compute\s+the\s+derivative\s+of|"
    r"d\s*/\s*dx(?:\s+of)?)\s*:?\s*(?:the\s+(?:function\s+)?)?(?P<f>.+)", re.IGNORECASE)
_INTEGRAL_PROMPT = re.compile(
    r"(?:(?:indefinite\s+)?integral\s+of|integrate|antiderivative\s+of|∫)\s*:?\s*(?:the\s+(?:function\s+)?)?"
    r"(?P<f>.+?)(?:\s*d\s*x\b|[.?]?\s*$)", re.IGNORECASE)


def derive_answer_check(prompt: str, existing: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """An ``answer_verification`` payload read from the question's wording, when the builder stored none.

    Four plain forms in ``x`` are recognized: a derivative, an indefinite integral, a definite integral and
    a limit. A word problem or anything that does not parse returns None, and the question then has no
    computed check.
    """
    if existing and existing.get("variable") and (existing.get("integrand") or existing.get("derivative_of")
                                                  or existing.get("value") is not None):
        return dict(existing)
    try:
        import sympy
    except ImportError:
        return None
    # Full-width brackets and punctuation from a Chinese keyboard ("sin（x^3）") read as plain ones.
    text = " ".join(unicodedata.normalize("NFKC", prompt).replace("$", " ").split()).rstrip(".?! ")
    x = sympy.Symbol("x")
    try:
        if (match := _DEFINITE_PROMPT.search(text)):
            f, a, b = (_parse(_to_sympy_text(match.group(k)), sympy) for k in ("f", "a", "b"))
            if f is not None and a is not None and b is not None:
                value = sympy.simplify(sympy.integrate(f, (x, a, b)))
                if value.is_finite and not value.free_symbols and not value.has(sympy.Integral):
                    return {"status": "derived_from_prompt", "method": "sympy", "variable": "x",
                            "value": str(value), "kind": "definite_integral"}
        elif (match := _LIMIT_PROMPT.search(text)):
            f, a = (_parse(_to_sympy_text(match.group(k).replace("infinity", "oo")), sympy) for k in ("f", "a"))
            if f is not None and a is not None:
                value = sympy.limit(f, x, a)
                if value.is_finite and not value.free_symbols and not value.has(sympy.Limit):
                    return {"status": "derived_from_prompt", "method": "sympy", "variable": "x",
                            "value": str(sympy.simplify(value)), "kind": "limit"}
    except Exception:           # sympy could not do it: the question simply has no computed check
        return None
    if re.search(r"\bfrom\b.+\bto\b|\bdefinite\b|\bmaxim|\bminim|\btangent\b|\bat\s+x\s*=", text, re.IGNORECASE):
        return None
    for kind, pattern in (("integrand", _INTEGRAL_PROMPT), ("derivative_of", _DERIVATIVE_PROMPT)):
        match = pattern.search(text)
        if not match:
            continue
        body = match.group("f")
        body = re.sub(r"(?i)\s+with\s+respect\s+to\s+x\b.*$", "", body)
        body = re.sub(r"(?i)^\s*(?:y|f\s*\(\s*x\s*\))\s*=\s*", "", body).strip(" .:")
        expression = _to_sympy_text(body)
        if _parse(expression, sympy) is not None and "x" in expression:
            return {"status": "derived_from_prompt", "method": "sympy", "variable": "x", kind: expression}
    return None


def is_correct_expression(expression_text: str, answer_verification: Mapping[str, Any] | None) -> bool:
    """True when one expression is proved to be the answer. Used by the reply leak check.

    A one-digit answer ("1", "3") appears in ordinary tutoring ("$e^0 = 1$") and is left to the guard model.
    """
    value = (answer_verification or {}).get("value")
    if value is not None and len(str(value)) < 3:
        return False
    return check_math("", answer_verification, final_answer=expression_text)["status"] == "correct"


def _parse(text: str, sympy: Any) -> Any:
    """Parse one expression, or return None. Only whitelisted names are ever handed to sympy."""
    text = text.strip()
    if not text or len(text) > _MAX_EXPRESSION_CHARS or not _ALLOWED_CHARS.match(text):
        return None
    names = set(re.findall(r"[A-Za-z_]+", text))
    if any(name not in _ALLOWED_NAMES and len(name) != 1 for name in names):
        return None
    local = {name: getattr(sympy, name) for name in _ALLOWED_NAMES if hasattr(sympy, name)}
    local.update({name: sympy.Symbol(name) for name in names if len(name) == 1 and name not in ("E", "e")})
    local["e"] = sympy.E
    try:
        return sympy.sympify(text, locals=local)
    except Exception:
        return None


def extract_candidates(text: str) -> list[str]:
    """Expressions in free text that could be the student's answer."""
    candidates: list[str] = []
    for part in re.split(r"=", text)[1:]:                       # whatever follows an "="
        raw = re.split(r"[\n;]|\.\s|\.$", part)[0].strip()
        if raw:
            candidates.append(_to_sympy_text(raw))
    for inner in re.findall(r"\$\$?([^$]+)\$\$?", text):         # $...$ and $$...$$
        candidates.append(_to_sympy_text(inner.split("=")[-1].strip()))
    functions = "(?:" + "|".join(_FUNCTIONS) + "|ln)"
    prefix, argument = r"[-a-zA-Z0-9\*]*?", r"\([^()]*\)"
    term = rf"[-a-zA-Z0-9\*]*?(?:{functions}\s*{argument}|[a-zA-Z0-9]+)"
    for match in re.finditer(rf"({prefix}{functions}\s*{argument}(?:\s*[\+\-]\s*{term})*)", text, re.IGNORECASE):
        candidates.append(_to_sympy_text(match.group(1).strip()))
    for match in re.finditer(r"[a-zA-Z]\s*(?:\*\*|\^)\s*[0-9]+"
                             r"(?:\s*[\+\-\*\/]\s*[a-zA-Z0-9]+(?:\s*(?:\*\*|\^)\s*[0-9]+)?)*", text):
        candidates.append(_to_sympy_text(match.group(0).strip()))
    # Runs of math between ordinary words: "ok so cos(x^3) * 3x^2" -> "cos(x^3) * 3x^2".
    run: list[str] = []
    for word in [*text.replace("$", " ").split(), "end"]:
        bare = word.strip(".,;:!?")
        if re.fullmatch(r"[A-Za-z]{2,}", bare) and bare.lower() not in _FUNCTIONS and bare.lower() != "ln":
            joined = " ".join(run).strip(".,;:!? ")
            if len(run) >= 1 and re.search(r"[+*/^(]|\d", joined) and len(joined) <= _MAX_EXPRESSION_CHARS:
                candidates.append(_to_sympy_text(joined))
            run = []
        else:
            run.append(word)
    whole = text.strip()
    if whole and len(whole) <= _MAX_EXPRESSION_CHARS and not re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{2,}", whole):
        candidates.append(_to_sympy_text(whole))                 # the whole message, when it is not prose
    seen: set[str] = set()
    return [c for c in candidates if c and not (c in seen or seen.add(c))]


def _to_sympy_text(raw: str) -> str:
    """Best-effort conversion of common LaTeX and student notation to sympy syntax."""
    s = unicodedata.normalize("NFKC", raw).strip().strip("$").strip().rstrip("!?. ")         # "ln(x)!!" is emphasis, not a factorial
    s = _CONSTANT.sub("", s).strip()
    for latex, name in ((r"\sin", "sin"), (r"\cos", "cos"), (r"\tan", "tan"), (r"\sec", "sec"), (r"\ln", "log"),
                        (r"\log", "log"), (r"\exp", "exp"), (r"\sqrt", "sqrt"), (r"\pi", "pi")):
        s = s.replace(latex, name)
    s = re.sub(r"\bln\b", "log", s)
    s = s.replace(r"\cdot", "*").replace(r"\times", "*").replace(r"\left", "").replace(r"\right", "")
    s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = s.replace("{", "(").replace("}", ")")
    names_ = "|".join(_FUNCTIONS)
    # sec^2(x) / sec^2 x / sin^{2}(x) -> (sec(x))^2
    s = re.sub(rf"\b({names_})\s*\^\s*\(?\s*(\d+)\s*\)?\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)", r"(\1(\3))^\2", s)
    s = re.sub(rf"\b({names_})\s*\^\s*\(?\s*(\d+)\s*\)?\s+([a-zA-Z0-9]+)\b", r"(\1(\3))^\2", s)
    s = s.replace("^", "**")
    s = re.sub(r"\)\s*\(", ")*(", s)
    names = "|".join(_FUNCTIONS)
    s = re.sub(rf"([a-zA-Z\d)])\s*({names})\b", r"\1*\2", s)     # x sin(x) -> x*sin(x)
    s = re.sub(rf"\b({names})\s+([a-zA-Z])\b", r"\1(\2)", s)     # sin x -> sin(x)
    s = re.sub(r"(\d)\s*([a-zA-Z(])", r"\1*\2", s)               # 2x -> 2*x
    s = re.sub(rf"\b(?!(?:{names})\b)([a-zA-Z])\s*\(", r"\1*(", s)   # x(…) -> x*(…), but not sin(…)
    s = re.sub(r"\)\s*([a-zA-Z\d])", r")*\1", s)                 # (…)x -> (…)*x
    s = re.sub(r"\b([a-zA-Z])\s+([a-zA-Z])\b", r"\1*\2", s)      # x y -> x*y
    return s.strip().rstrip(".").strip()
