"""Course Context — Stage A pipeline.

Turns a course syllabus into a structured CourseContext JSON (Course, Module,
Concept, LearningObjective, Source), per specs/course-context.md.

Provider-agnostic: the LLM is any OpenAI-compatible endpoint (Ollama local by
default; swap base_url/model/key for OpenAI, OpenRouter, DeepSeek, the JHU
Gateway, etc. — all via config, nothing hardcoded).
"""

__version__ = "0.1.0"
