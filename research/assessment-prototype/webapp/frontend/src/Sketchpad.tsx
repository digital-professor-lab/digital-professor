import { PointerEvent, useEffect, useRef, useState } from "react";

interface SketchpadProps {
  onClose: () => void;
  onUpload: (file: File) => Promise<void>;
}

export default function Sketchpad({ onClose, onUpload }: SketchpadProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [lineWidth, setLineWidth] = useState(4);
  const [uploading, setUploading] = useState(false);

  function clearCanvas() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
  }

  useEffect(clearCanvas, []);

  function coordinates(event: PointerEvent<HTMLCanvasElement>) {
    const canvas = event.currentTarget;
    const bounds = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * (canvas.width / bounds.width),
      y: (event.clientY - bounds.top) * (canvas.height / bounds.height),
    };
  }

  function start(event: PointerEvent<HTMLCanvasElement>) {
    drawing.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    const context = event.currentTarget.getContext("2d");
    const point = coordinates(event);
    if (!context) return;
    context.beginPath();
    context.moveTo(point.x, point.y);
  }

  function move(event: PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const context = event.currentTarget.getContext("2d");
    const point = coordinates(event);
    if (!context) return;
    context.strokeStyle = "#15231f";
    context.lineWidth = lineWidth * (event.currentTarget.width / event.currentTarget.clientWidth);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineTo(point.x, point.y);
    context.stroke();
  }

  function stop(event: PointerEvent<HTMLCanvasElement>) {
    drawing.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  async function upload() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setUploading(true);
    try {
      const blob = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Could not export sketch.")), "image/png"),
      );
      await onUpload(new File([blob], `sketch-${Date.now()}.png`, { type: "image/png" }));
      onClose();
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="sketch-modal" role="dialog" aria-modal="true" aria-labelledby="sketch-title">
        <div className="sketch-header">
          <div><p className="eyebrow">Handwriting input</p><h2 id="sketch-title">Sketchpad</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close sketchpad">×</button>
        </div>
        <p>Write an equation, draw a diagram, or show your work. The sketch will be uploaded as a handwriting source.</p>
        <canvas
          ref={canvasRef}
          width={1200}
          height={600}
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={stop}
          onPointerCancel={stop}
        />
        <div className="sketch-actions">
          <label>Pen size <input type="range" min="2" max="10" value={lineWidth} onChange={(event) => setLineWidth(Number(event.target.value))} /></label>
          <button className="secondary-button" type="button" onClick={clearCanvas}>Clear</button>
          <button className="primary-button" type="button" onClick={upload} disabled={uploading}>{uploading ? "Recognizing…" : "Upload sketch"}</button>
        </div>
      </section>
    </div>
  );
}
