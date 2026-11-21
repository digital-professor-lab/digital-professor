"""Teaching policy data for the Tutoring Engine.

The Engine keeps a small, checkable skeleton in code and leaves the teaching itself to the language model:

* One hard rule: the student does the solving. The tutor never states the final answer and never carries
  out a step of the problem for them. Reply checks enforce it.
* Pacing: the opening reply gives no hint, and the method name and the textbook passage are held back
  until the student is stuck a second time (two help requests, two wrong attempts, or one of each).
* Everything else (which move, how much to say, in what words) is the model's judgment. The help level
  (0 to 3) is recorded as a fact, not used as a cap.
* Code checks the math, keeps the learner state, and checks every reply before it is sent.

This replaces the 21 action cards and 9 ladders of the first implementation. Running that version with
real students' wording showed that code was deciding not only how much to disclose but also exactly how
to teach, and the replies came out formulaic.
"""

from __future__ import annotations

from dataclasses import dataclass

POLICY_VERSION = "tutoring-policy@3.0"


@dataclass(frozen=True, slots=True)
class Settings:
    max_turns_per_question: int = 20
    max_stall_turns: int = 6
    guess_limit: int = 3
    max_model_retries: int = 1
    max_reply_rewrites: int = 1
    max_reply_words: int = 150          # asked of the writer; a reply is rejected only above twice this
    retrieval_enabled: bool = True
    model_guard_enabled: bool = True
    passages_per_reply: int = 3


TURN_TYPES = ("ANSWER", "PARTIAL", "NEW_QUESTION", "DEMAND", "CONCEPT", "HELP", "VAGUE", "ACK", "OFF_TOPIC",
              "DISTRESS", "INVALID")
ATTEMPT_TURNS = ("ANSWER", "PARTIAL")

# What the judge may say about an attempt. ON_TRACK is "right so far, not finished": without it a student
# who takes a correct step can only be given an error code, and progress is mistaken for being stuck.
DIAGNOSIS_MEANING = {
    "ON_TRACK": "Correct so far, but not finished",
    "D0": "No starting idea",
    "D1": "Misread the question",
    "D2": "Missing prerequisite",
    "D3": "Wrong method",
    "D4": "Right method, wrong setup",
    "D5": "Right method, rule misused or a step missing",
    "D6": "Right method, careless slip (sign or arithmetic)",
    "D7": "Nearly done, incomplete (for example a missing + C)",
    "CORRECT": "The final answer is correct",
    "UNCLEAR": "Not enough evidence to tell",
}
DIAGNOSIS_EXAMPLE = {
    "ON_TRACK": "identifies the right structure or completes a correct first step, with more still to do",
    "D0": 'says "I have no idea"',
    "D1": "gives the derivative when asked for a maximum",
    "D2": "cannot say what a composite function is",
    "D3": "picks a different technique from the one the problem needs",
    "D4": "uses the right technique but sets it up wrongly, such as swapping u and dv",
    "D5": "leaves out the inner derivative",
    "D6": "makes a sign or arithmetic error",
    "D7": "omits + C, or does not check the endpoints",
}
MODEL_DIAGNOSES = tuple(DIAGNOSIS_MEANING)
ERROR_DIAGNOSES = frozenset({"D1", "D2", "D3", "D4", "D5", "D6", "D7"})
CONFIDENCES = ("high", "medium", "low")
EXPLANATION_QUALITIES = ("sound", "weak", "contradicts", "none")
GAP_STATUSES = ("open", "partial", "closed")


# How much help a move gives. Code does not choose the move; it records the most help given so far, which
# decides whether a correct answer counts as unaided and is told to the writer as a fact.
HELP_NAMES = ("asked questions only", "pointed at a feature or a step", "named the method or taught the rule",
              "worked a similar example")
MAX_LEVEL = len(HELP_NAMES) - 1
MOVE_HELP = {"ask_plan": 0, "ask_work": 0, "ask_reason": 0, "clarify": 0, "encourage_retry": 0, "redirect": 0,
             "point": 1, "check_prerequisite": 1, "answer_concept": 1,
             "teach_rule": 2, "refer_to_text": 2, "review_prerequisite": 2, "similar_example": 3}

# The moves a writer can choose from. The label goes into the log and maps to a shared TutoringAction type.
MOVES: dict[str, str] = {
    "ask_plan": "elicit", "ask_work": "inspect", "ask_reason": "probe", "clarify": "probe",
    "point": "hint", "check_prerequisite": "probe", "review_prerequisite": "explain",
    "teach_rule": "hint", "refer_to_text": "hint", "similar_example": "demonstrate",
    "encourage_retry": "retry", "answer_concept": "explain", "confirm_ask_why": "check_understanding",
    "wrap_up": "verify", "redirect": "elicit", "discuss_solution": "explain",
}
DEFAULT_MOVE = {"open": "ask_plan", "help": "ask_plan", "attempt": "ask_reason", "concept": "answer_concept",
                "wrap_up": "wrap_up", "after_solved": "discuss_solution", "redirect": "redirect",
                "unclear": "clarify"}

# Used when no model is available or a reply fails its checks twice. They state no course content.
FALLBACK_TEXT = {
    "open": "How would you start this one? Tell me what you notice about the problem, or what you have tried.",
    "help": "Let's take it one step at a time. What is the first thing you notice about the expression?",
    "attempt": "Thanks for showing that. Can you walk me through how you got your most recent step?",
    "concept": "Good question. Which part of that idea feels least clear to you?",
    "wrap_up": "Well done. You solved this question, and your progress is saved.",
    "after_solved": "You have finished this question. Is there a part of it you would like to go over?",
    "redirect": "Let's come back to the problem. What would your next step be?",
    "unclear": "I'm not sure I followed. Do you want help getting started, or shall I look at a step you wrote?",
}
PARK_TEXT = ("Let's pause here. Your progress is saved. You can come back to this at any time, or ask your "
             "instructor about this step.")
SWITCH_TEXT = "That looks like a different problem. Do you want to switch to it, or finish this one first?"
# Development placeholder: approved wording is required before real student use.
SAFETY_TEXT = ("I'm stopping our math session because what you wrote matters more. You don't have to handle this "
               "alone. In the US, you can call or text 988 at any time. If you are in immediate danger, call 911.")
SAFETY_PHRASES = ("kill myself", "end my life", "want to die", "hurt myself", "suicide", "self harm", "self-harm")

# Words that describe the structure of an expression or name a standard method. None of them may appear in
# the opening reply; method names stay out until the student has asked for help, made an error or stalled,
# unless the student used the word first.
STRUCTURE_WORDS = ("inner", "outer", "inside function", "outside function", "composite", "composition",
                   "nested", "product of", "quotient of")
METHOD_NAMES = ("chain rule", "product rule", "quotient rule", "power rule", "integration by parts", "by parts",
                "substitution", "u-substitution", "partial fractions", "l'hopital", "l'hôpital",
                "implicit differentiation", "logarithmic differentiation", "trigonometric substitution")
