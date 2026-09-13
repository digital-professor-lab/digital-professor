"""Versioned prompts for recognition and tutor-style generation."""

RECOGNITION_INSTRUCTIONS = """You transcribe instructional material faithfully.
Preserve prose, steps, labels, and layout in readable Markdown. Write every mathematical
expression as valid LaTeX using $...$ or $$...$$. Keep page numbers supplied by the caller."""

TEXT_RECOGNITION_PROMPT = """Normalize this extracted document text into faithful Markdown.
Recover equations when the extraction is clear, but record uncertainty instead of guessing.
The text may have lost visual layout during PDF extraction. Source: {source_name}\n\n{text}"""

IMAGE_RECOGNITION_PROMPT = """Transcribe page {page_number} of {source_name}. Treat it as
student-provided course material. Preserve mistakes exactly and flag ambiguous handwriting."""

TUTOR_PROMPT = """STUDENT REQUEST:
{question}

OPTIONAL COURSE OR RECOGNITION CONTEXT:
{context}"""
