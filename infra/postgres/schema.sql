CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS courses (
    course_id text PRIMARY KEY,
    name text NOT NULL,
    note text NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id text PRIMARY KEY,
    course_id text NOT NULL REFERENCES courses(course_id),
    source_type text NOT NULL,
    filename text NOT NULL,
    source_path text NOT NULL,
    snapshot_path text NOT NULL,
    sha256 text NOT NULL,
    line_count integer NOT NULL,
    provenance text NOT NULL,
    review_status text NOT NULL
);

CREATE TABLE IF NOT EXISTS sections (
    section_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES documents(document_id),
    parent_id text REFERENCES sections(section_id),
    level integer NOT NULL,
    title text NOT NULL,
    heading_kind text NOT NULL,
    start_line integer NOT NULL,
    end_line integer NOT NULL
);

CREATE TABLE IF NOT EXISTS passages (
    passage_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES documents(document_id),
    section_id text NOT NULL REFERENCES sections(section_id),
    passage_kind text NOT NULL,
    scope_status text NOT NULL,
    start_line integer NOT NULL,
    end_line integer NOT NULL,
    raw_latex text NOT NULL,
    readable_text text NOT NULL
);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id text PRIMARY KEY,
    course_id text NOT NULL REFERENCES courses(course_id),
    title text NOT NULL,
    summary text NOT NULL,
    extraction_method text NOT NULL,
    review_status text NOT NULL
);

CREATE TABLE IF NOT EXISTS concept_evidence (
    concept_id text NOT NULL REFERENCES concepts(concept_id),
    passage_id text NOT NULL REFERENCES passages(passage_id),
    relation text NOT NULL,
    PRIMARY KEY (concept_id, passage_id)
);

CREATE TABLE IF NOT EXISTS review_issues (
    issue_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES documents(document_id),
    source_line integer NOT NULL,
    severity text NOT NULL,
    status text NOT NULL,
    description text NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_inputs (
    record_id text PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('concept', 'passage')),
    entity_id text NOT NULL,
    segment_index integer NOT NULL,
    segment_count integer NOT NULL,
    course_id text NOT NULL REFERENCES courses(course_id),
    document_id text NOT NULL REFERENCES documents(document_id),
    source_type text NOT NULL,
    section_path text NOT NULL,
    scope_status text NOT NULL,
    review_status text NOT NULL,
    source_line_start integer NOT NULL,
    source_line_end integer NOT NULL,
    input_text text NOT NULL,
    input_sha256 text NOT NULL,
    bge_token_count integer NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_models (
    model_key text PRIMARY KEY,
    repository text NOT NULL,
    revision text NOT NULL,
    input_sha256 text NOT NULL,
    vector_sha256 text NOT NULL,
    dimensions integer NOT NULL,
    normalized boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_bge (
    record_id text PRIMARY KEY REFERENCES embedding_inputs(record_id),
    embedding vector(768) NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_qwen (
    record_id text PRIMARY KEY REFERENCES embedding_inputs(record_id),
    embedding vector(1024) NOT NULL
);

CREATE INDEX IF NOT EXISTS embedding_inputs_course_scope_idx
    ON embedding_inputs (course_id, scope_status);
CREATE INDEX IF NOT EXISTS embedding_inputs_text_idx
    ON embedding_inputs USING gin (to_tsvector('english', input_text));
CREATE INDEX IF NOT EXISTS embedding_bge_cosine_idx
    ON embedding_bge USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS embedding_qwen_cosine_idx
    ON embedding_qwen USING hnsw (embedding vector_cosine_ops);
