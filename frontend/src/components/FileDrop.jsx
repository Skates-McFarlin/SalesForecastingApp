import { useRef, useState } from "react";

const ACCEPT = ".csv,.xlsx,.xls";
const VALID = /\.(csv|xlsx|xls)$/i;

export default function FileDrop({ file, onSelect, onReject }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const accept = (candidate) => {
    if (!candidate) return;
    if (!VALID.test(candidate.name)) {
      onReject?.(`"${candidate.name}" isn't a supported file. Upload a .csv, .xlsx or .xls file.`);
      return;
    }
    onSelect(candidate);
  };

  if (file) {
    return (
      <div className="flex items-center gap-2.5 rounded-lg border border-[var(--line-strong)] bg-[var(--surface-2)] p-3">
        <svg className="size-5 shrink-0 text-accent-500" viewBox="0 0 20 20" fill="none">
          <path
            d="M11.5 2.5H6a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 6 17.5h8a1.5 1.5 0 0 0 1.5-1.5V6.5l-4-4Z"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
          <path d="M11.5 2.5v4h4" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        </svg>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium" title={file.name}>
            {file.name}
          </div>
          <div className="tnum text-xs text-[var(--ink-3)]">{formatBytes(file.size)}</div>
        </div>
        <button
          onClick={() => {
            onSelect(null);
            if (inputRef.current) inputRef.current.value = "";
          }}
          className="shrink-0 rounded p-1 text-[var(--ink-3)] hover:bg-[var(--surface-3)] hover:text-[var(--ink)]"
          aria-label="Remove file"
        >
          <svg className="size-4" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => accept(e.target.files?.[0])}
        />
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          accept(e.dataTransfer.files?.[0]);
        }}
        className={`flex w-full flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-6 text-center transition-colors ${
          dragging
            ? "border-accent-500 bg-accent-500/8"
            : "border-[var(--line-strong)] hover:border-accent-400 hover:bg-[var(--surface-2)]"
        }`}
      >
        <svg
          className={`size-6 ${dragging ? "text-accent-500" : "text-[var(--ink-3)]"}`}
          viewBox="0 0 24 24"
          fill="none"
        >
          <path
            d="M12 15.5V4m0 0L7.5 8.5M12 4l4.5 4.5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
        <span className="text-sm font-medium">Drop your sales file</span>
        <span className="text-xs text-[var(--ink-3)]">or click to browse — CSV or Excel</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => accept(e.target.files?.[0])}
      />
    </>
  );
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
