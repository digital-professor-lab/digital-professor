import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { api } from "./api";
import type { Message, ProviderConfig, SkillInstructions, SourceRecord, Tab, TranscriptionResult } from "./types";
import Sketchpad from "./Sketchpad";
import VoiceInput from "./VoiceInput";

const tabLabels: Record<Tab, string> = {
  sources: "Sources",
  settings: "Provider settings",
  chat: "Chat",
};

function normalizeMathDelimiters(value: string) {
  return value
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((segment) => {
      if (segment.startsWith("`")) return segment;
      return segment
        .replace(/\\\[/g, () => "$$")
        .replace(/\\\]/g, () => "$$")
        .replace(/\\\(/g, () => "$")
        .replace(/\\\)/g, () => "$");
    })
    .join("");
}

function Markdown({ children }: { children: string }) {
  const normalized = normalizeMathDelimiters(children);
  return (
    <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
      {normalized}
    </ReactMarkdown>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function App() {
  const [tab, setTab] = useState<Tab>("sources");
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [config, setConfig] = useState<ProviderConfig | null>(null);
  const [model, setModel] = useState("gpt-4o");
  const [inputRate, setInputRate] = useState("");
  const [outputRate, setOutputRate] = useState("");
  const [skills, setSkills] = useState<SkillInstructions>({
    tutoring_instructions: "",
    explanation_instructions: "",
    review_instructions: "",
  });
  const [sourceType, setSourceType] = useState("auto");
  const [recognitionProvider, setRecognitionProvider] = useState<"openai_vision" | "tesseract">("openai_vision");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ completed: number; total: number; name: string } | null>(null);
  const [chatUploading, setChatUploading] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState("");
  const [sketchOpen, setSketchOpen] = useState(false);
  const [transcriptionModel, setTranscriptionModel] = useState("gpt-4o-mini-transcribe");
  const [transcriptionProvider, setTranscriptionProvider] = useState<"openai" | "faster_whisper">("openai");
  const [transcribing, setTranscribing] = useState(false);
  const [lastTranscription, setLastTranscription] = useState<TranscriptionResult | null>(null);
  const [recognitionDraft, setRecognitionDraft] = useState<{ interactionId: string; text: string } | null>(null);
  const [exposeSources, setExposeSources] = useState(true);
  const [ratedSources, setRatedSources] = useState<Record<string, number>>({});
  const fileInput = useRef<HTMLInputElement>(null);
  const chatFileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    Promise.all([api.config(), api.sources()])
      .then(([nextConfig, nextSources]) => {
        setConfig(nextConfig);
        setSources(nextSources);
        setModel(nextConfig.model);
        setInputRate(nextConfig.input_cost_per_1m?.toString() ?? "");
        setOutputRate(nextConfig.output_cost_per_1m?.toString() ?? "");
        setSkills(nextConfig.skills);
        setRecognitionProvider(nextConfig.recognition_provider);
        setTranscriptionModel(nextConfig.transcription_model);
        setTranscriptionProvider(nextConfig.transcription_provider);
        setExposeSources(nextConfig.expose_sources);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const syllabus = [...sources].reverse().find((source) => source.source_type === "syllabus");
  const courseTitle = useMemo(() => {
    if (!syllabus?.course) return "Course workspace";
    return [syllabus.course.course_number, syllabus.course.course_name].filter(Boolean).join(" · ");
  }, [syllabus]);

  async function upload(files: FileList | File[]) {
    const selected = Array.from(files);
    if (selected.length === 0) return;
    setUploading(true);
    setError("");
    const failures: string[] = [];
    try {
      for (const [index, file] of selected.entries()) {
        setUploadProgress({ completed: index, total: selected.length, name: file.name });
        try {
          const added = await api.upload(file, sourceType, recognitionProvider);
          setSources((current) => [...current, added]);
        } catch (reason) {
          failures.push(`${file.name}: ${reason instanceof Error ? reason.message : "Upload failed."}`);
        }
      }
      if (failures.length > 0) setError(failures.join("\n"));
      setSourceType("auto");
    } finally {
      setUploading(false);
      setUploadProgress(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function removeSource(id: string) {
    try {
      await api.removeSource(id);
      setSources((current) => current.filter((source) => source.id !== id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove source.");
    }
  }

  async function rateRecognition(id: string, rating: number) {
    try {
      await api.rateRecognition(id, rating);
      setRatedSources((current) => ({ ...current, [id]: rating }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save recognition feedback.");
    }
  }

  async function uploadChatFiles(files: FileList | File[]) {
    setChatUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        const isImage = /\.(png|jpe?g|webp)$/i.test(file.name);
        const added = await api.upload(file, isImage ? "handwriting" : "auto", recognitionProvider);
        setSources((current) => [...current, added]);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Attachment upload failed.");
    } finally {
      setChatUploading(false);
      if (chatFileInput.current) chatFileInput.current.value = "";
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const nextQuestion = question.trim();
    if (!nextQuestion || thinking) return;
    setQuestion("");
    setError("");
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "student", text: nextQuestion },
    ]);
    setThinking(true);
    try {
      const result = await api.chat({
        question: nextQuestion,
        model,
        input_cost_per_1m: inputRate ? Number(inputRate) : null,
        output_cost_per_1m: outputRate ? Number(outputRate) : null,
        skills,
        expose_sources: exposeSources,
        recognition_interaction_id: recognitionDraft?.interactionId ?? null,
        recognition_draft: recognitionDraft?.text ?? null,
      });
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "professor",
          text: result.answer_markdown,
          result,
        },
      ]);
      setRecognitionDraft(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The tutor could not respond.");
    } finally {
      setThinking(false);
    }
  }

  async function transcribe(file: File) {
    setTranscribing(true);
    setError("");
    try {
      const result = await api.transcribe(file, transcriptionProvider, transcriptionModel);
      const draft = [question.trim(), result.text].filter(Boolean).join(" ");
      setQuestion(draft);
      setLastTranscription(result);
      setRecognitionDraft({ interactionId: result.interaction_id, text: draft });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Audio transcription failed.");
    } finally {
      setTranscribing(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">DP</div>
          <div>
            <strong>Digital Professor</strong>
            <span>Assessment prototype</span>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {(Object.keys(tabLabels) as Tab[]).map((item) => (
            <button
              className={tab === item ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => setTab(item)}
            >
              <span className="nav-dot" />
              {tabLabels[item]}
              {item === "sources" && <small>{sources.length}</small>}
            </button>
          ))}
        </nav>
        <button className="office-hours" disabled>
          <span>Office Hours</span>
          <small>Coming soon</small>
        </button>
        <div className="status">
          <span className={config?.api_key_configured ? "status-dot ready" : "status-dot"} />
          {config?.api_key_configured ? "Tutor connected" : "API key needed"}
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p className="eyebrow">Current workspace</p>
            <h1>{courseTitle}</h1>
          </div>
          <div className="source-count">{sources.length} source{sources.length === 1 ? "" : "s"}</div>
        </header>

        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button onClick={() => setError("")} aria-label="Dismiss error">×</button>
          </div>
        )}

        {tab === "sources" && (
          <section className="page sources-page">
            <div className="page-heading">
              <div>
                <p className="eyebrow">Ground the professor</p>
                <h2>Course sources</h2>
                <p>Upload syllabi, lecture notes, and textbooks. Each file becomes a separate source.</p>
              </div>
            </div>

            {!syllabus && (
              <div className="onboarding-card">
                <span className="step-label">First step</span>
                <h3>Upload your course material</h3>
                <p>Start with a syllabus and lecture notes; their types are detected automatically.</p>
              </div>
            )}

            {syllabus?.course && (
              <div className="course-card">
                <div>
                  <span className="step-label">Detected course</span>
                  <h3>{syllabus.course.course_name || "Course name needs review"}</h3>
                </div>
                <div className="course-facts">
                  <span>{syllabus.course.course_number || "No course number detected"}</span>
                  <span>{syllabus.course.semester || "No semester detected"}</span>
                </div>
              </div>
            )}

            {syllabus?.course?.course_overview && (
              <div className="course-overview">
                <span className="step-label dark">Course overview</span>
                <p>{syllabus.course.course_overview}</p>
              </div>
            )}

            <div className="upload-row">
              <label>
                Document type
                <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                  <option value="auto">Detect automatically</option>
                  <option value="syllabus">Syllabus (override)</option>
                  <option value="lecture_notes">Lecture notes (override)</option>
                  <option value="textbook">Textbook (override)</option>
                  <option value="document">Other document (override)</option>
                  <option value="handwriting">Handwritten work</option>
                </select>
              </label>
              <label className="file-button">
                {uploading && uploadProgress ? `Processing ${uploadProgress.completed + 1}/${uploadProgress.total}…` : "Choose files"}
                <input
                  ref={fileInput}
                  type="file"
                  accept=".pdf,.txt,.md,.tex,.png,.jpg,.jpeg,.webp"
                  multiple
                  disabled={uploading}
                  onChange={(event) => event.target.files && upload(event.target.files)}
                />
              </label>
            </div>
            {uploadProgress && <p className="upload-progress" role="status">Uploading {uploadProgress.name} ({uploadProgress.completed + 1} of {uploadProgress.total})</p>}

            <div className="source-grid">
              {sources.map((source) => (
                <article className="source-card" key={source.id}>
                  <div className="source-card-top">
                    <span className={`source-icon ${source.source_type}`}>{source.source_type[0].toUpperCase()}</span>
                    <div>
                      <h3>{source.filename}</h3>
                      <p>{source.source_type} · {source.page_count} page{source.page_count === 1 ? "" : "s"}</p>
                    </div>
                    <button className="icon-button" onClick={() => removeSource(source.id)} aria-label="Remove source">×</button>
                  </div>
                  <p className="preview">{source.preview || "No embedded text was found."}</p>
                  {source.analysis_warning && <p className="source-analysis-warning">{source.analysis_warning}</p>}
                  {source.source_type === "textbook" && (
                    <div className="source-course-details">
                      <strong>{source.textbook_name || "Textbook title needs review"}</strong>
                      <span>Textbook · {source.page_count} pages</span>
                    </div>
                  )}
                  {source.source_type === "syllabus" && source.course && (
                    <div className="source-course-details">
                      <strong>{source.course.course_name || "Course name needs review"}</strong>
                      <span>{source.course.course_number || "Course number not found"} · {source.course.semester || "Semester not found"}</span>
                      {source.course.course_overview && (
                        <details>
                          <summary>Extracted course overview</summary>
                          <p>{source.course.course_overview}</p>
                        </details>
                      )}
                    </div>
                  )}
                  {source.topics.length > 0 && (
                    <details className="topic-outline">
                      <summary>{source.topics.length} topics in the lecture-note outline</summary>
                      <ol>
                        {source.topics.map((topic, index) => (
                          <li key={`${topic.section_number ?? index}-${index}`} className={`topic-level-${Math.min(topic.level, 3)}`}>
                            <span>{topic.section_number ? `${topic.section_number} ` : ""}{topic.title}</span>
                            {topic.page_number && <small>PDF p. {topic.page_number}</small>}
                          </li>
                        ))}
                      </ol>
                    </details>
                  )}
                  {source.request_metadata.length > 0 && (
                    <p className="recognition-note">
                      Recognized in {source.request_metadata.reduce((sum, item) => sum + item.elapsed_seconds, 0).toFixed(2)}s
                    </p>
                  )}
                  <p className="recognition-note">
                    {source.recognition_method === "rendered_page_vision" && "OpenAI visual handwriting recognition"}
                    {source.recognition_method === "tesseract_local" && "Local Tesseract OCR baseline"}
                    {source.recognition_method === "embedded_text" && "Embedded text extraction"}
                  </p>
                  <div className="quality-actions" aria-label={`Rate recognition quality for ${source.filename}`}>
                    <span>{ratedSources[source.id] ? `Quality rated ${ratedSources[source.id]}/5` : "Recognition quality"}</span>
                    <button type="button" onClick={() => rateRecognition(source.id, 5)}>Good</button>
                    <button type="button" onClick={() => rateRecognition(source.id, 2)}>Needs correction</button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {tab === "settings" && (
          <section className="page settings-page">
            <div className="page-heading">
              <div>
                <p className="eyebrow">Runtime configuration</p>
                <h2>Provider settings</h2>
                <p>The browser sends model and pricing choices per request. The API key stays on the backend.</p>
              </div>
            </div>
            <div className="settings-card">
              <label>
                Provider
                <select disabled value="OpenAI"><option>OpenAI</option></select>
              </label>
              <label>
                Model ID
                <select value={model} onChange={(event) => setModel(event.target.value)}>
                  {(config?.models ?? [model]).map((modelId) => (
                    <option key={modelId} value={modelId}>{modelId}</option>
                  ))}
                </select>
                <small className="field-help">Models are loaded from the configured API account. Specialized models may not support tutoring responses.</small>
              </label>
              <div className="rate-grid">
                <label>
                  Input USD / 1M tokens
                  <input type="number" min="0" step="0.01" value={inputRate} onChange={(event) => setInputRate(event.target.value)} placeholder="Optional" />
                </label>
                <label>
                  Output USD / 1M tokens
                  <input type="number" min="0" step="0.01" value={outputRate} onChange={(event) => setOutputRate(event.target.value)} placeholder="Optional" />
                </label>
              </div>
              <label className="toggle-row">
                <input type="checkbox" checked={exposeSources} onChange={(event) => setExposeSources(event.target.checked)} />
                <span>
                  <strong>Expose sources in answers</strong>
                  <small className="field-help">Show citations for uploaded material used by the tutor. Uncheck to keep source references hidden in the response.</small>
                </span>
              </label>
              <label>
                Handwriting recognition
                <select value={recognitionProvider} onChange={(event) => setRecognitionProvider(event.target.value as "openai_vision" | "tesseract")}>
                  <option value="openai_vision">OpenAI vision</option>
                  <option value="tesseract" disabled={!config?.tesseract_available}>Tesseract local baseline{config?.tesseract_available ? "" : " — not installed"}</option>
                </select>
                <small className="field-help">Tesseract provides a zero-API-cost baseline for comparison but is not designed to reconstruct handwritten equations as LaTeX.</small>
              </label>
              <label>
                Voice transcription provider
                <select
                  value={transcriptionProvider}
                  onChange={(event) => {
                    const provider = event.target.value as "openai" | "faster_whisper";
                    setTranscriptionProvider(provider);
                    setTranscriptionModel(provider === "openai" ? "gpt-4o-mini-transcribe" : "base");
                  }}
                >
                  <option value="openai">OpenAI API</option>
                  <option value="faster_whisper" disabled={!config?.faster_whisper_available}>Local faster-whisper{config?.faster_whisper_available ? "" : " — not installed"}</option>
                </select>
              </label>
              <label>
                Voice transcription model
                <select value={transcriptionModel} onChange={(event) => setTranscriptionModel(event.target.value)}>
                  {((transcriptionProvider === "openai" ? config?.transcription_models : config?.local_transcription_models) ?? [transcriptionModel]).map((modelId) => (
                    <option key={modelId} value={modelId}>{modelId}</option>
                  ))}
                </select>
                <small className="field-help">Record the same question with different models to compare transcription accuracy and processing time. Model availability depends on the configured API account.</small>
              </label>
              <div className="key-status">
                <span className={config?.api_key_configured ? "status-dot ready" : "status-dot"} />
                <div>
                  <strong>{config?.api_key_configured ? "Backend key configured" : "Backend key missing"}</strong>
                  <p>{config?.api_key_configured ? "Ready for recognition and tutoring requests." : "Set OPENAI_API_KEY in the root .env and restart FastAPI."}</p>
                </div>
              </div>
              <div className="skill-settings">
                <div>
                  <span className="step-label dark">Instruction skills</span>
                  <h3>Professor behavior</h3>
                  <p>Edit these session instructions to test tutoring behavior without changing application code.</p>
                </div>
                <label>
                  Tutoring instructions
                  <textarea rows={5} value={skills.tutoring_instructions} onChange={(event) => setSkills({...skills, tutoring_instructions: event.target.value})} />
                </label>
                <label>
                  Explanation instructions
                  <textarea rows={6} value={skills.explanation_instructions} onChange={(event) => setSkills({...skills, explanation_instructions: event.target.value})} />
                </label>
                <label>
                  Review instructions
                  <textarea rows={5} value={skills.review_instructions} onChange={(event) => setSkills({...skills, review_instructions: event.target.value})} />
                </label>
                <button className="secondary-button" type="button" onClick={() => config && setSkills(config.skills)}>Reset instruction defaults</button>
              </div>
            </div>
          </section>
        )}

        {tab === "chat" && (
          <section className="chat-page">
            <div className="messages">
              {messages.length === 0 && (
                <div className="welcome">
                  <div className="professor-avatar">DP</div>
                  <p className="eyebrow">Digital Professor</p>
                  <h2>Work through course material</h2>
                  <p>Ask about a section, paste an equation, or discuss your work. Section quizzes and response critique are the next build step.</p>
                  <div className="suggestions">
                    {["Explain $\\nabla f(x)=0$", "Check my optimization setup", "Give me a hint from the notes"].map((suggestion) => (
                      <button key={suggestion} onClick={() => setQuestion(suggestion)}>{suggestion}</button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="message-label">{message.role === "student" ? "You" : "Digital Professor"}</div>
                  <div className="message-body"><Markdown>{message.text}</Markdown></div>
                  {message.result && (
                    <>
                      {message.result.assumptions.length > 0 && (
                        <details><summary>Assumptions</summary><ul>{message.result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></details>
                      )}
                      {message.result.citations.length > 0 && (
                        <div className="citations">
                          <strong>Sources</strong>
                          <ol>
                            {message.result.citations.map((citation, index) => (
                              <li key={`${citation.source_id}-${index}`}>
                                <span>{citation.filename}{citation.page_number ? `, p. ${citation.page_number}` : ""}</span>
                                <p>{citation.basis}</p>
                              </li>
                            ))}
                          </ol>
                        </div>
                      )}
                      <div className="check-in"><strong>Check your understanding</strong><Markdown>{message.result.comprehension_check}</Markdown></div>
                      <div className="metrics">
                        <Metric label="Time" value={`${message.result.request.elapsed_seconds.toFixed(2)}s`} />
                        <Metric label="Tokens" value={message.result.request.total_tokens?.toLocaleString() ?? "—"} />
                        <Metric label="Est. cost" value={message.result.request.estimated_cost_usd == null ? "—" : `$${message.result.request.estimated_cost_usd.toFixed(5)}`} />
                      </div>
                    </>
                  )}
                </article>
              ))}
              {thinking && <div className="thinking"><span /><span /><span /> Digital Professor is working…</div>}
            </div>
            <form className="composer" onSubmit={ask}>
              <div className="attached-sources">
                {sources.map((source) => (
                  <span key={source.id} title={source.filename}>{source.filename}</span>
                ))}
                {chatUploading && <span className="uploading-chip">Processing attachment…</span>}
              </div>
              <div className="composer-row">
                <label className="attach-button" title="Attach course documents">
                <span aria-hidden="true">＋</span>
                <span className="sr-only">Attach documents</span>
                <input
                  ref={chatFileInput}
                  type="file"
                  multiple
                  accept=".pdf,.txt,.md,.tex,.png,.jpg,.jpeg,.webp"
                  disabled={chatUploading || thinking}
                  onChange={(event) => event.target.files && uploadChatFiles(event.target.files)}
                />
                </label>
                <button className="sketch-button" type="button" title="Open handwriting sketchpad" onClick={() => setSketchOpen(true)} disabled={chatUploading || thinking}>
                  <span aria-hidden="true">✎</span><span className="sr-only">Open sketchpad</span>
                </button>
                <VoiceInput
                  disabled={chatUploading || thinking || transcribing}
                  onAudio={transcribe}
                  onError={setError}
                />
                <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder={transcribing ? "Transcribing your recording…" : "Ask, record, use ``` for code, or $$ for display math…"}
                rows={2}
                />
                <button type="submit" disabled={!question.trim() || thinking || chatUploading || transcribing}>Ask</button>
              </div>
              <p>
                {transcribing
                  ? "Converting speech to text…"
                  : lastTranscription
                    ? `Last transcription: ${lastTranscription.provider} / ${lastTranscription.model} · ${lastTranscription.elapsed_seconds.toFixed(2)}s`
                    : "Enter to send · Shift + Enter for a new line · Voice is transcribed before sending"}
              </p>
            </form>
          </section>
        )}
      </main>
      {sketchOpen && (
        <Sketchpad
          onClose={() => setSketchOpen(false)}
          onUpload={async (file) => uploadChatFiles([file])}
        />
      )}
    </div>
  );
}

export default App;
