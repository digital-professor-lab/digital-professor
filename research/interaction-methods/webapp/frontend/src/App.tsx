import { FormEvent, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import { api } from "./api";
import type { HandwritingReview, TurnResult } from "./types";
import Sketchpad from "./Sketchpad";

const DEMO_QUESTION = "Solve $2(x+3)=10$ and explain each step.";

function Markdown({ children }: { children: string }) {
  const normalized = children
    .replace(/\\\[/g, "$$")
    .replace(/\\\]/g, "$$")
    .replace(/\\\(/g, "$")
    .replace(/\\\)/g, "$");
  return <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{normalized}</ReactMarkdown>;
}

export default function App() {
  const [response, setResponse] = useState("");
  const [explanation, setExplanation] = useState("");
  const [uncertainty, setUncertainty] = useState("unsure");
  const [turns, setTurns] = useState<TurnResult[]>([]);
  const [pending, setPending] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [handwritingReview, setHandwritingReview] = useState<HandwritingReview | null>(null);
  const [confirmedContent, setConfirmedContent] = useState("");
  const [ambiguityResolutions, setAmbiguityResolutions] = useState<Record<string, string>>({});
  const [sketchOpen, setSketchOpen] = useState(false);
  const [error, setError] = useState("");
  const handwritingInput = useRef<HTMLInputElement>(null);
  const sessionId = useMemo(() => crypto.randomUUID(), []);
  const previous = turns.at(-1);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!response.trim() || pending) return;
    setPending(true);
    setError("");
    try {
      const result = await api.runTurn({
        user_id: "browser-student",
        course_id: "demo-course",
        session_id: sessionId,
        turn_id: crypto.randomUUID(),
        question_id: "question-demo-1",
        attempt_id: "attempt-demo-1",
        submitted_text: response,
        evidence_kind: previous ? "revision" : "initial_attempt",
        parent_submission_id: previous?.submission.submission_id ?? null,
        parent_evidence_id: previous?.evidence.evidence_id ?? null,
        response_to_action_id: previous?.action.action_id ?? null,
        student_explanation: explanation.trim() || null,
        student_uncertainty: { level: uncertainty },
      });
      setTurns((current) => [...current, result]);
      setResponse("");
      setExplanation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The turn could not be completed.");
    } finally {
      setPending(false);
    }
  }

  async function recognizeHandwriting(file: File, modality: "handwriting_upload" | "stylus_canvas" = "handwriting_upload") {
    setRecognizing(true);
    setError("");
    try {
      const review = await api.recognizeHandwriting(file, {
        user_id: "browser-student",
        course_id: "demo-course",
        session_id: sessionId,
        turn_id: crypto.randomUUID(),
        question_id: "question-demo-1",
        attempt_id: "attempt-demo-1",
        evidence_kind: previous ? "revision" : "initial_attempt",
        parent_submission_id: previous?.submission.submission_id ?? null,
        parent_evidence_id: previous?.evidence.evidence_id ?? null,
        response_to_action_id: previous?.action.action_id ?? null,
        student_explanation: explanation.trim() || null,
        student_uncertainty: uncertainty,
        modality,
      });
      setHandwritingReview(review);
      setConfirmedContent(review.recognition.recognized_content);
      setAmbiguityResolutions({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Handwriting recognition failed.");
    } finally {
      setRecognizing(false);
      if (handwritingInput.current) handwritingInput.current.value = "";
    }
  }

  async function confirmHandwriting() {
    if (!handwritingReview || !confirmedContent.trim()) return;
    setConfirming(true);
    setError("");
    try {
      const completed = await api.confirmHandwriting(
        handwritingReview.recognition.recognition_id,
        confirmedContent,
        ambiguityResolutions,
      );
      setTurns((current) => [...current, completed.result]);
      setHandwritingReview(null);
      setConfirmedContent("");
      setAmbiguityResolutions({});
      setExplanation("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The transcription could not be confirmed.");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">DP</div>
          <div><strong>Digital Professor</strong><span>Student Evidence V1</span></div>
        </div>
        <div className="scope-card">
          <p className="eyebrow">Active slice</p>
          <strong>Text + handwriting</strong>
          <span>Mock engine · Mock delivery</span>
        </div>
        <ol className="pipeline-list">
          <li>Preserve submission</li>
          <li>Validate evidence</li>
          <li>Request tutoring action</li>
          <li>Record delivery</li>
        </ol>
        <p className="status"><span className="status-dot ready" />V1 contracts active</p>
      </aside>

      <main>
        <header className="topbar">
          <div><p className="eyebrow">Demo course · Question 1</p><h1>Typed tutoring turn</h1></div>
          <span className="source-count">{turns.length} {turns.length === 1 ? "attempt" : "attempts"}</span>
        </header>
        {error && <div className="error-banner"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}

        <section className="turn-page">
          <div className="question-card">
            <p className="message-label">Assigned question</p>
            <Markdown>{DEMO_QUESTION}</Markdown>
          </div>
          <div className="messages" aria-live="polite">
            {turns.length === 0 && (
              <div className="welcome">
                <div className="professor-avatar">DP</div>
                <h2>Show how you approached the problem</h2>
                <p>Your original text is preserved exactly before it becomes Student Evidence.</p>
              </div>
            )}
            {turns.map((turn, index) => (
              <article className="turn" key={turn.submission.submission_id}>
                <div className="message student">
                  <p className="message-label">Student · {index ? "Revision" : "Initial attempt"}</p>
                  <div className="message-body"><Markdown>{turn.submission.submitted_text}</Markdown></div>
                </div>
                <div className="message professor">
                  <p className="message-label">Mock tutoring action</p>
                  <div className="message-body"><Markdown>{turn.action.content.text}</Markdown></div>
                  <div className="record-strip">
                    <span>Evidence: {turn.evidence.validation_status}</span>
                    <span>Action: {turn.action.action_type}</span>
                    <span>Delivery: {turn.delivery.presentation_status}</span>
                  </div>
                  <details>
                    <summary>Inspect handoff trace</summary>
                    <ol>{turn.trace_events.map((item) => <li key={item.event_id}>{item.event_type}</li>)}</ol>
                  </details>
                </div>
              </article>
            ))}
          </div>

          <form className="composer" onSubmit={submit}>
            <div className="handwriting-row">
              <span>Submit typed work below, or upload handwritten work for review.</span>
              <div className="input-actions">
                <button type="button" className="secondary-button" disabled={recognizing} onClick={() => setSketchOpen(true)}>Open sketchpad</button>
                <button type="button" className="secondary-button" disabled={recognizing} onClick={() => handwritingInput.current?.click()}>{recognizing ? "Recognizing…" : "Upload handwriting"}</button>
              </div>
              <input
                ref={handwritingInput}
                className="sr-only"
                type="file"
                accept="application/pdf,image/png,image/jpeg,image/webp"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void recognizeHandwriting(file);
                }}
              />
            </div>
            <div className="support-fields">
              <label>Confidence
                <select value={uncertainty} onChange={(event) => setUncertainty(event.target.value)}>
                  <option value="confident">Confident</option><option value="unsure">Unsure</option><option value="guessing">Guessing</option>
                </select>
              </label>
              <label>Explanation (optional)
                <input value={explanation} onChange={(event) => setExplanation(event.target.value)} placeholder="Why did you take this step?" />
              </label>
            </div>
            <div className="composer-row">
              <textarea rows={3} value={response} onChange={(event) => setResponse(event.target.value)} placeholder={previous ? "Revise your work. Markdown, `code`, and $$LaTeX$$ are supported." : "Enter your work. Markdown, `code`, and $$LaTeX$$ are supported."} />
              <button type="submit" disabled={pending || !response.trim()}>{pending ? "Sending…" : previous ? "Submit revision" : "Submit attempt"}</button>
            </div>
            <p>The Interaction module records evidence; the mock engine selects the displayed probe.</p>
          </form>
        </section>
      </main>

      {handwritingReview && (
        <div className="modal-backdrop" role="presentation">
          <section className="recognition-modal" role="dialog" aria-modal="true" aria-labelledby="recognition-title">
            <div className="sketch-header">
              <div><p className="eyebrow">Recognition review</p><h2 id="recognition-title">Confirm what you wrote</h2></div>
              <button className="icon-button" onClick={() => setHandwritingReview(null)} aria-label="Close recognition review">×</button>
            </div>
            <p className="review-purpose">Check the transcription, not the solution. The system will not send ambiguous work downstream until you confirm it.</p>
            <div className="recognition-meta">
              <span>{handwritingReview.recognition.page_count} page(s)</span>
              <span>{handwritingReview.recognition.provider} · {handwritingReview.recognition.model_version}</span>
              <span>{handwritingReview.recognition.latency_ms ?? "—"} ms</span>
            </div>
            {handwritingReview.recognition.ambiguities.filter((item) => item.meaning_may_change).map((item) => (
              <label className="ambiguity-card" key={item.ambiguity_id}>
                <strong>{item.description || "Meaning-changing notation is unclear"}</strong>
                <span>Page {item.page_number ?? "?"}, {item.region || "unknown region"}; read as <code>{item.raw_value || "?"}</code></span>
                <input
                  value={ambiguityResolutions[item.ambiguity_id] ?? ""}
                  onChange={(event) => setAmbiguityResolutions((current) => ({ ...current, [item.ambiguity_id]: event.target.value }))}
                  placeholder={item.candidates?.length ? `Confirm: ${item.candidates.join(" or ")}` : "Enter exactly what you wrote"}
                />
              </label>
            ))}
            <label className="transcription-field">Recognized work
              <textarea rows={10} value={confirmedContent} onChange={(event) => setConfirmedContent(event.target.value)} />
              <span className="field-help">If you resolve an ambiguous symbol differently, make the same edit in this transcription.</span>
            </label>
            <div className="review-actions">
              <button type="button" className="secondary-button" onClick={() => setHandwritingReview(null)}>Cancel</button>
              <button type="button" className="primary-button" disabled={confirming || !confirmedContent.trim()} onClick={() => void confirmHandwriting()}>
                {confirming ? "Continuing…" : handwritingReview.confirmation_required ? "Confirm and continue" : "Use transcription"}
              </button>
            </div>
          </section>
        </div>
      )}
      {sketchOpen && (
        <Sketchpad onClose={() => setSketchOpen(false)} onSubmit={(file) => recognizeHandwriting(file, "stylus_canvas")} />
      )}
    </div>
  );
}
