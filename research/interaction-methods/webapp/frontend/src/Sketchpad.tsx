import { PointerEvent, useEffect, useRef, useState } from "react";

interface Props {
  onClose: () => void;
  onSubmit: (file: File) => Promise<void>;
}

export default function Sketchpad({ onClose, onSubmit }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [lineWidth, setLineWidth] = useState(4);
  const [submitting, setSubmitting] = useState(false);

  function clear() {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
  }

  useEffect(clear, []);

  function point(event: PointerEvent<HTMLCanvasElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * (event.currentTarget.width / bounds.width),
      y: (event.clientY - bounds.top) * (event.currentTarget.height / bounds.height),
    };
  }

  function start(event: PointerEvent<HTMLCanvasElement>) {
    drawing.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    const context = event.currentTarget.getContext("2d");
    const next = point(event);
    context?.beginPath();
    context?.moveTo(next.x, next.y);
  }

  function move(event: PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const context = event.currentTarget.getContext("2d");
    if (!context) return;
    const next = point(event);
    context.strokeStyle = "#15231f";
    context.lineWidth = lineWidth * (event.currentTarget.width / event.currentTarget.clientWidth);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineTo(next.x, next.y);
    context.stroke();
  }

  function stop(event: PointerEvent<HTMLCanvasElement>) {
    drawing.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  async function submit() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setSubmitting(true);
    try {
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Canvas export failed.")), "image/png");
      });
      await onSubmit(new File([blob], `stylus-${Date.now()}.png`, { type: "image/png" }));
      onClose();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="sketch-modal" role="dialog" aria-modal="true" aria-labelledby="sketch-title">
        <div className="sketch-header">
          <div><p className="eyebrow">Direct stylus input</p><h2 id="sketch-title">Show your work</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close sketchpad">×</button>
        </div>
        <p>Write with a mouse, finger, or stylus. The original canvas export will be preserved before recognition.</p>
        <canvas ref={canvasRef} width={1200} height={600} onPointerDown={start} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} />
        <div className="sketch-actions">
          <label>Pen size <input type="range" min="2" max="10" value={lineWidth} onChange={(event) => setLineWidth(Number(event.target.value))} /></label>
          <button className="secondary-button" type="button" onClick={clear}>Clear</button>
          <button className="primary-button" type="button" disabled={submitting} onClick={() => void submit()}>{submitting ? "Recognizing…" : "Review handwriting"}</button>
        </div>
      </section>
    </div>
  );
}
