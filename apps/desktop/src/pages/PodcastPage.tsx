import { useState, useEffect, useRef, useCallback } from "react";
import type { PodcastJob } from "../lib/api";
import {
  generatePodcast,
  getPodcastStatus,
  listPodcastJobs,
} from "../lib/api";

// ── Constants ──────────────────────────────────────────────────────

const DURATIONS = [15, 30, 60, 90] as const;
const LEVELS = ["beginner", "intermediate", "advanced"] as const;

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  planning: "Planning Curriculum",
  researching: "Researching Topics",
  writing: "Writing Script",
  producing: "Producing Audio",
  done: "Complete",
  error: "Error",
};

const STAGE_ICONS: Record<string, string> = {
  queued: "⏳",
  planning: "📋",
  researching: "🔍",
  writing: "✍️",
  producing: "🎵",
  done: "✅",
  error: "❌",
};

// ── Component ──────────────────────────────────────────────────────

export default function PodcastPage() {
  // Form state
  const [topic, setTopic] = useState("");
  const [duration, setDuration] = useState<number>(30);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("intermediate");

  // Job state
  const [activeJob, setActiveJob] = useState<PodcastJob | null>(null);
  const [jobs, setJobs] = useState<PodcastJob[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Audio player
  const audioRef = useRef<HTMLAudioElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  // ── Load past jobs on mount ───────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const data = await listPodcastJobs();
        setJobs(data.jobs);
      } catch {
        // Jobs list is non-critical
      }
    })();
  }, []);

  // ── Poll active job status ────────────────────────────────────
  const startPolling = useCallback((jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      try {
        const status = await getPodcastStatus(jobId);
        setActiveJob(status);

        if (status.status === "done" || status.status === "error") {
          clearInterval(pollRef.current);
          setIsGenerating(false);

          // Refresh job list
          const data = await listPodcastJobs();
          setJobs(data.jobs);

          if (status.status === "error") {
            setError(status.error || "Unknown error");
          }
        }
      } catch (err) {
        // Polling failure is transient
      }
    }, 1500);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ── Generate ──────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!topic.trim()) return;

    setError(null);
    setIsGenerating(true);
    setActiveJob(null);

    try {
      const result = await generatePodcast({
        topic: topic.trim(),
        duration_minutes: duration,
        level,
      });

      setActiveJob({
        job_id: result.job_id,
        topic: topic.trim(),
        status: "queued",
        progress_pct: 0,
        created_at: new Date().toISOString(),
        duration_minutes: duration,
        level,
      });

      startPolling(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start generation");
      setIsGenerating(false);
    }
  };

  // ── Audio URL ─────────────────────────────────────────────────
  const audioUrl =
    activeJob?.status === "done" && activeJob?.job_id
      ? `http://127.0.0.1:13420/api/podcast/download/${activeJob.job_id}`
      : null;

  // ── Render ────────────────────────────────────────────────────
  return (
    <div className="podcast-page">
      <div className="page-header">
        <h1>🎙️ Podcast Studio</h1>
        <p style={{ color: "var(--text-muted)", margin: "4px 0 0" }}>
          Generate custom audio learning sessions on any topic
        </p>
      </div>

      <div className="podcast-layout">
        {/* ── Input Form ── */}
        <div className="podcast-form-card glass-card">
          <h3 style={{ margin: "0 0 16px" }}>New Podcast</h3>

          {/* Topic */}
          <label className="form-label">Topic</label>
          <input
            id="podcast-topic"
            type="text"
            className="form-input"
            placeholder="e.g. Advanced Rust Concurrency Patterns"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            disabled={isGenerating}
            onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
          />

          {/* Duration */}
          <label className="form-label" style={{ marginTop: 16 }}>
            Duration
          </label>
          <div className="btn-group">
            {DURATIONS.map((d) => (
              <button
                key={d}
                className={`btn-option ${duration === d ? "active" : ""}`}
                onClick={() => setDuration(d)}
                disabled={isGenerating}
              >
                {d} min
              </button>
            ))}
          </div>

          {/* Level */}
          <label className="form-label" style={{ marginTop: 16 }}>
            Level
          </label>
          <div className="btn-group">
            {LEVELS.map((l) => (
              <button
                key={l}
                className={`btn-option ${level === l ? "active" : ""}`}
                onClick={() => setLevel(l)}
                disabled={isGenerating}
              >
                {l.charAt(0).toUpperCase() + l.slice(1)}
              </button>
            ))}
          </div>

          {/* Generate Button */}
          <button
            id="podcast-generate-btn"
            className="btn-primary podcast-generate-btn"
            onClick={handleGenerate}
            disabled={isGenerating || !topic.trim()}
            style={{ marginTop: 24, width: "100%" }}
          >
            {isGenerating ? "Generating..." : "🎙️ Generate Podcast"}
          </button>

          {error && (
            <div className="podcast-error" style={{ marginTop: 12 }}>
              ❌ {error}
            </div>
          )}
        </div>

        {/* ── Progress / Player ── */}
        <div className="podcast-progress-card glass-card">
          {activeJob ? (
            <>
              {/* Title */}
              <h3 style={{ margin: "0 0 8px" }}>
                {STAGE_ICONS[activeJob.status] || "🎙️"}{" "}
                {activeJob.topic}
              </h3>
              <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "0 0 16px" }}>
                {activeJob.duration_minutes} min • {activeJob.level}
              </p>

              {/* Progress Bar */}
              <div className="progress-bar-container">
                <div
                  className="progress-bar-fill"
                  style={{
                    width: `${activeJob.progress_pct}%`,
                    transition: "width 0.8s ease",
                  }}
                />
              </div>
              <div className="progress-label">
                <span>{STAGE_LABELS[activeJob.status] || activeJob.status}</span>
                <span>{activeJob.progress_pct}%</span>
              </div>

              {/* Stage Indicators */}
              <div className="stage-indicators">
                {["planning", "researching", "writing", "producing", "done"].map(
                  (stage) => {
                    const stageOrder = [
                      "queued", "planning", "researching", "writing", "producing", "done",
                    ];
                    const currentIdx = stageOrder.indexOf(activeJob.status);
                    const stageIdx = stageOrder.indexOf(stage);
                    const isDone = stageIdx < currentIdx;
                    const isCurrent = stage === activeJob.status;

                    return (
                      <div
                        key={stage}
                        className={`stage-indicator ${isDone ? "done" : ""} ${isCurrent ? "current" : ""}`}
                      >
                        <span className="stage-dot" />
                        <span className="stage-name">{STAGE_LABELS[stage]}</span>
                      </div>
                    );
                  }
                )}
              </div>

              {/* Audio Player */}
              {audioUrl && (
                <div className="audio-player-card" style={{ marginTop: 20 }}>
                  <audio
                    ref={audioRef}
                    controls
                    src={audioUrl}
                    style={{ width: "100%" }}
                  />
                  <a
                    href={audioUrl}
                    download
                    className="btn-primary"
                    style={{
                      display: "inline-block",
                      marginTop: 10,
                      textDecoration: "none",
                      textAlign: "center",
                    }}
                  >
                    ⬇️ Download MP3
                  </a>
                </div>
              )}
            </>
          ) : (
            <div className="podcast-empty-state">
              <div style={{ fontSize: 48, marginBottom: 12 }}>🎧</div>
              <h3 style={{ margin: "0 0 8px", color: "var(--text-primary)" }}>
                Ready to Learn
              </h3>
              <p style={{ color: "var(--text-muted)", fontSize: 14 }}>
                Enter a topic and click Generate to create your personalized
                audio learning session.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Recent Jobs ── */}
      {jobs.length > 0 && (
        <div className="podcast-history glass-card" style={{ marginTop: 20 }}>
          <h3 style={{ margin: "0 0 12px" }}>Recent Podcasts</h3>
          <div className="jobs-list">
            {jobs.slice(0, 8).map((job) => (
              <div
                key={job.job_id}
                className={`job-item ${activeJob?.job_id === job.job_id ? "active" : ""}`}
                onClick={() => {
                  if (job.status === "done") {
                    setActiveJob(job);
                  }
                }}
                style={{ cursor: job.status === "done" ? "pointer" : "default" }}
              >
                <span className="job-icon">
                  {STAGE_ICONS[job.status] || "🎙️"}
                </span>
                <div className="job-info">
                  <div className="job-topic">{job.topic}</div>
                  <div className="job-meta">
                    {job.duration_minutes}min • {job.level} •{" "}
                    {STAGE_LABELS[job.status]}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Scoped Styles ── */}
      <style>{`
        .podcast-page {
          padding: 0;
          max-width: 900px;
        }

        .podcast-layout {
          display: grid;
          grid-template-columns: 340px 1fr;
          gap: 20px;
          margin-top: 20px;
        }

        @media (max-width: 768px) {
          .podcast-layout {
            grid-template-columns: 1fr;
          }
        }

        .glass-card {
          background: var(--bg-secondary, rgba(30, 30, 46, 0.7));
          border: 1px solid var(--border-color, rgba(255,255,255,0.08));
          border-radius: 14px;
          padding: 20px;
          backdrop-filter: blur(12px);
        }

        .podcast-form-card,
        .podcast-progress-card {
          min-height: 300px;
        }

        .form-label {
          display: block;
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-muted, #888);
          margin-bottom: 6px;
        }

        .form-input {
          width: 100%;
          padding: 10px 14px;
          background: var(--bg-tertiary, rgba(0,0,0,0.3));
          border: 1px solid var(--border-color, rgba(255,255,255,0.1));
          border-radius: 8px;
          color: var(--text-primary, #e0e0e0);
          font-size: 14px;
          outline: none;
          transition: border-color 0.2s;
          box-sizing: border-box;
        }
        .form-input:focus {
          border-color: var(--accent, #7c5cfc);
        }

        .btn-group {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .btn-option {
          padding: 8px 16px;
          border-radius: 8px;
          border: 1px solid var(--border-color, rgba(255,255,255,0.1));
          background: var(--bg-tertiary, rgba(0,0,0,0.2));
          color: var(--text-muted, #aaa);
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }
        .btn-option:hover:not(:disabled) {
          border-color: var(--accent, #7c5cfc);
          color: var(--text-primary, #fff);
        }
        .btn-option.active {
          background: var(--accent, #7c5cfc);
          border-color: var(--accent, #7c5cfc);
          color: #fff;
          font-weight: 600;
        }
        .btn-option:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .podcast-generate-btn {
          padding: 12px;
          font-size: 15px;
          font-weight: 600;
          border-radius: 10px;
          border: none;
          background: linear-gradient(135deg, #7c5cfc, #a855f7);
          color: #fff;
          cursor: pointer;
          transition: all 0.3s;
          box-shadow: 0 4px 15px rgba(124, 92, 252, 0.3);
        }
        .podcast-generate-btn:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 6px 20px rgba(124, 92, 252, 0.4);
        }
        .podcast-generate-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          transform: none;
        }

        .podcast-error {
          padding: 10px 14px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 8px;
          color: #ef4444;
          font-size: 13px;
        }

        .progress-bar-container {
          width: 100%;
          height: 8px;
          background: var(--bg-tertiary, rgba(0,0,0,0.3));
          border-radius: 4px;
          overflow: hidden;
        }

        .progress-bar-fill {
          height: 100%;
          background: linear-gradient(90deg, #7c5cfc, #a855f7, #ec4899);
          border-radius: 4px;
          background-size: 200% 100%;
          animation: shimmer 2s ease infinite;
        }

        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }

        .progress-label {
          display: flex;
          justify-content: space-between;
          margin-top: 6px;
          font-size: 12px;
          color: var(--text-muted, #888);
        }

        .stage-indicators {
          display: flex;
          justify-content: space-between;
          margin-top: 20px;
          padding-top: 16px;
          border-top: 1px solid var(--border-color, rgba(255,255,255,0.06));
        }

        .stage-indicator {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          opacity: 0.4;
          transition: opacity 0.3s;
        }
        .stage-indicator.done { opacity: 0.7; }
        .stage-indicator.current {
          opacity: 1;
        }

        .stage-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: var(--text-muted, #555);
          transition: all 0.3s;
        }
        .stage-indicator.done .stage-dot {
          background: #22c55e;
        }
        .stage-indicator.current .stage-dot {
          background: var(--accent, #7c5cfc);
          box-shadow: 0 0 8px var(--accent, #7c5cfc);
          animation: pulse 1.5s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 4px var(--accent, #7c5cfc); }
          50% { box-shadow: 0 0 12px var(--accent, #7c5cfc); }
        }

        .stage-name {
          font-size: 10px;
          color: var(--text-muted, #888);
          text-align: center;
          max-width: 70px;
        }

        .audio-player-card {
          background: var(--bg-tertiary, rgba(0,0,0,0.2));
          padding: 16px;
          border-radius: 10px;
          border: 1px solid var(--border-color, rgba(255,255,255,0.06));
        }

        .podcast-empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          min-height: 260px;
          text-align: center;
          opacity: 0.8;
        }

        .podcast-history .jobs-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .job-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 14px;
          border-radius: 8px;
          background: var(--bg-tertiary, rgba(0,0,0,0.15));
          transition: background 0.2s;
        }
        .job-item:hover {
          background: var(--bg-tertiary, rgba(0,0,0,0.3));
        }
        .job-item.active {
          border: 1px solid var(--accent, #7c5cfc);
        }

        .job-icon {
          font-size: 20px;
          flex-shrink: 0;
        }

        .job-info {
          flex: 1;
          min-width: 0;
        }

        .job-topic {
          font-size: 14px;
          font-weight: 500;
          color: var(--text-primary, #e0e0e0);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .job-meta {
          font-size: 12px;
          color: var(--text-muted, #888);
          margin-top: 2px;
        }
      `}</style>
    </div>
  );
}
