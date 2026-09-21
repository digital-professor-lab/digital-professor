import { useRef, useState } from "react";

interface VoiceInputProps {
  disabled: boolean;
  onAudio: (file: File) => Promise<void>;
  onError: (message: string) => void;
}

function recordingFormat() {
  const choices = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return choices.find((choice) => window.MediaRecorder?.isTypeSupported(choice)) ?? "";
}

export default function VoiceInput({ disabled, onAudio, onError }: VoiceInputProps) {
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  async function begin() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      fileInput.current?.click();
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = recordingFormat();
      const nextRecorder = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined);
      chunks.current = [];
      nextRecorder.ondataavailable = (event) => {
        if (event.data.size) chunks.current.push(event.data);
      };
      nextRecorder.onstop = async () => {
        const type = nextRecorder.mimeType || "audio/webm";
        const extension = type.includes("mp4") ? "m4a" : "webm";
        const audio = new File(chunks.current, `voice-question-${Date.now()}.${extension}`, { type });
        stream.current?.getTracks().forEach((track) => track.stop());
        stream.current = null;
        if (audio.size) await onAudio(audio);
      };
      recorder.current = nextRecorder;
      nextRecorder.start();
      setRecording(true);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Microphone access was not available.");
    }
  }

  function stop() {
    recorder.current?.stop();
    recorder.current = null;
    setRecording(false);
  }

  return (
    <>
      <button
        className={recording ? "voice-button recording" : "voice-button"}
        type="button"
        title={recording ? "Stop and transcribe" : "Record a voice question"}
        aria-label={recording ? "Stop recording and transcribe" : "Record a voice question"}
        disabled={disabled}
        onClick={recording ? stop : begin}
      >
        <span aria-hidden="true">{recording ? "■" : "●"}</span>
      </button>
      <input
        ref={fileInput}
        className="sr-only"
        type="file"
        accept="audio/*,.webm"
        capture="user"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void onAudio(file);
          event.target.value = "";
        }}
      />
    </>
  );
}
