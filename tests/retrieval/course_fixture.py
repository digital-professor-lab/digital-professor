"""A small Calculus I course written for the retrieval tests: a syllabus and three pages of lecture notes.

The notes are original text, laid out the way the ingestion segmenter expects (numbered sections, then
``Definition`` / ``Theorem`` / ``Example`` / ``Remark`` blocks). Each page is separated by a form feed and
becomes one PDF page in ``notes_pdf``.
"""

from __future__ import annotations

SYLLABUS = b"""110.108 Calculus I
Fall 2026
Course Description
This course introduces limits, derivatives, integrals, and their applications.
Topics
Limits and continuity. Differentiation rules. Applications of the derivative.
The definite integral. Techniques of integration.
Grading
Homework 30 percent. Exams 70 percent.
"""

NOTES_PAGES = [
    """110.108 Calculus I Lecture Notes
Chapter 3 Differentiation Rules
3.1 The Product Rule
Theorem 3.1 (Product rule). If f and g are differentiable at x, then the derivative of
the product f(x)g(x) is f'(x)g(x) + f(x)g'(x).
Example 3.1. Differentiate x^2 sin(x). Take f(x) = x^2 and g(x) = sin(x). The product rule
gives 2x sin(x) + x^2 cos(x).
Remark. A common error is to multiply the two derivatives. The derivative of a product is
not the product of the derivatives.
3.2 The Chain Rule
Definition 3.2. A composite function has the form f(g(x)), where g is the inner function
and f is the outer function.
Theorem 3.2 (Chain rule). If g is differentiable at x and f is differentiable at g(x), then
the composite function f(g(x)) is differentiable at x and its derivative is f'(g(x)) g'(x).
Example 3.2. Differentiate sin(x^2). The outer function is sine and the inner function is
x^2. The chain rule gives cos(x^2) times 2x.
Remark. Students often forget to multiply by the derivative of the inner function.
""",
    """Chapter 4 Applications of the Derivative
4.1 Critical Points and Local Extrema
Definition 4.1. A critical point of f is a number c in the domain of f where f'(c) = 0
or f'(c) does not exist.
Theorem 4.1 (First derivative test). Suppose c is a critical point of a continuous
function f. If f' changes sign from positive to negative at c, then f has a local maximum
at c. If f' changes sign from negative to positive at c, then f has a local minimum at c.
Example 4.1. Find the local extrema of f(x) = x^3 - 3x. The derivative is 3x^2 - 3, which
is zero at x = -1 and x = 1. The function has a local maximum at -1 and a local minimum at 1.
4.2 Optimization on a Closed Interval
Theorem 4.2 (Closed interval method). To find the absolute maximum and minimum of a
continuous function on a closed interval, evaluate the function at every critical point
inside the interval and at both endpoints. The largest value is the absolute maximum and
the smallest value is the absolute minimum.
Remark. Do not forget to check the endpoints of the interval.
""",
    """Chapter 6 Techniques of Integration
6.1 Substitution
Theorem 6.1 (Substitution rule). If u = g(x) is differentiable, then the integral of
f(g(x)) g'(x) dx equals the integral of f(u) du.
Example 6.1. Evaluate the integral of 2x cos(x^2) dx. Let u = x^2, so du = 2x dx. The
integral becomes the integral of cos(u) du, which is sin(x^2) + C.
6.2 Integration by Parts
Theorem 6.2 (Integration by parts). If u and v are differentiable functions, then the
integral of u dv equals uv minus the integral of v du.
Example 6.2. Evaluate the integral of x cos(x) dx. Choose u = x and dv = cos(x) dx. Then
du = dx and v = sin(x), so the integral is x sin(x) + cos(x) + C.
Remark. Choose u to be the factor that becomes simpler when it is differentiated.
Substitution does not work on the integral of x cos(x) dx, because no inner function has
its derivative as the other factor.
""",
]

NOTES = "\f".join(NOTES_PAGES).encode("utf-8")


def notes_pdf() -> bytes:
    """The notes as a three-page PDF, so blocks carry real page numbers."""
    import fitz  # PyMuPDF, already a product requirement

    document = fitz.open()
    for text in NOTES_PAGES:
        page = document.new_page()
        page.insert_text((54, 60), text, fontsize=9.5)
    data = document.tobytes()
    document.close()
    return data
