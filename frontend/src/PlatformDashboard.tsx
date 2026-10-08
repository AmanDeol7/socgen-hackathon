import { FormEvent, useEffect, useState } from "react";
import {
  EucDetails,
  EucSummary,
  ExecutionRecord,
  executeEuc,
  getEuc,
  getEucs,
  getExecution,
  getExecutions,
  GitHubSaveResponse,
  saveEucToGitHub,
} from "./api";

type DashboardSection = "eucs" | "executions";

interface PlatformDashboardProps {
  section: DashboardSection;
  initialEucName: string;
  onExecuteEuc: (name: string) => void;
}

export default function PlatformDashboard({
  section,
  initialEucName,
  onExecuteEuc,
}: PlatformDashboardProps) {
  const [eucs, setEucs] = useState<EucSummary[]>([]);
  const [eucError, setEucError] = useState("");
  const [isLoadingEucs, setIsLoadingEucs] = useState(true);
  const [selectedEucName, setSelectedEucName] = useState(initialEucName);
  const [details, setDetails] = useState<EucDetails | null>(null);
  const [detailsError, setDetailsError] = useState("");
  const [selectedFile, setSelectedFile] = useState("");
  const [githubSave, setGithubSave] = useState<GitHubSaveResponse | null>(null);
  const [githubError, setGithubError] = useState("");
  const [isSavingToGitHub, setIsSavingToGitHub] = useState(false);
  const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [selectedExecution, setSelectedExecution] =
    useState<ExecutionRecord | null>(null);
  const [selectedExecutionError, setSelectedExecutionError] = useState("");
  const [eucToExecute, setEucToExecute] = useState(initialEucName);
  const [executionInput, setExecutionInput] = useState('{\n  "name": "Aman"\n}');
  const [executionError, setExecutionError] = useState("");
  const [executionResult, setExecutionResult] =
    useState<ExecutionRecord | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [inputError, setInputError] = useState("");

  async function refreshEucs() {
    setIsLoadingEucs(true);
    setEucError("");
    try {
      const items = await getEucs();
      setEucs(items);
      setSelectedEucName((current) => {
        if (initialEucName && items.some((item) => item.name === initialEucName)) {
          return initialEucName;
        }
        return items.some((item) => item.name === current)
          ? current
          : (items[0]?.name ?? "");
      });
      setEucToExecute((current) => {
        if (initialEucName && items.some((item) => item.name === initialEucName)) {
          return initialEucName;
        }
        return items.some((item) => item.name === current)
          ? current
          : (items[0]?.name ?? "");
      });
    } catch (error) {
      setEucError(errorMessage(error));
    } finally {
      setIsLoadingEucs(false);
    }
  }

  async function refreshExecutions() {
    setIsLoadingHistory(true);
    setHistoryError("");
    try {
      setExecutions(await getExecutions());
    } catch (error) {
      setHistoryError(errorMessage(error));
    } finally {
      setIsLoadingHistory(false);
    }
  }

  useEffect(() => {
    void refreshEucs();
    void refreshExecutions();
  }, []);

  useEffect(() => {
    if (!selectedEucName) {
      setDetails(null);
      return;
    }
    let active = true;
    setDetails(null);
    setDetailsError("");
    getEuc(selectedEucName)
      .then((value) => {
        if (active) {
          setDetails(value);
          setSelectedFile((current) =>
            value.files.some((file) => file.path === current)
              ? current
              : (value.files[0]?.path ?? ""),
          );
        }
      })
      .catch((error: unknown) => {
        if (active) setDetailsError(errorMessage(error));
      });
    return () => {
      active = false;
    };
  }, [selectedEucName]);

  async function submitExecution(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setExecutionError("");
    setInputError("");
    setExecutionResult(null);
    if (!eucToExecute) {
      setExecutionError("Select a registered EUC to execute.");
      return;
    }

    let input: unknown;
    try {
      input = JSON.parse(executionInput);
    } catch {
      setInputError("Enter valid JSON before submitting.");
      return;
    }
    if (typeof input !== "object" || input === null || Array.isArray(input)) {
      setInputError("Execution input must be a JSON object.");
      return;
    }

    setIsExecuting(true);
    try {
      const record = await executeEuc(
        eucToExecute,
        input as Record<string, unknown>,
      );
      setExecutionResult(record);
      await refreshExecutions();
    } catch (error) {
      setExecutionError(errorMessage(error));
    } finally {
      setIsExecuting(false);
    }
  }

  async function openExecution(executionId: string) {
    setSelectedExecutionError("");
    try {
      setSelectedExecution(await getExecution(executionId));
    } catch (error) {
      setSelectedExecutionError(errorMessage(error));
    }
  }

  async function saveSelectedEucToGitHub() {
    if (!details) return;
    setGithubError("");
    setGithubSave(null);
    setIsSavingToGitHub(true);
    try {
      setGithubSave(await saveEucToGitHub(details.name));
      await refreshEucs();
      const refreshedDetails = await getEuc(details.name);
      setDetails(refreshedDetails);
    } catch (error) {
      setGithubError(errorMessage(error));
    } finally {
      setIsSavingToGitHub(false);
    }
  }

  const selectedFileContent = details?.files.find(
    (file) => file.path === selectedFile,
  )?.content;

  return section === "eucs" ? (
    <section className="dashboard-layout">
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Registered EUCs</h2>
            <p>Generated standardized artifacts ready for local execution.</p>
          </div>
          <button className="secondary-button" onClick={() => void refreshEucs()}>
            Refresh
          </button>
        </div>
        {isLoadingEucs ? (
          <Loading label="Loading registered EUCs…" />
        ) : eucError ? (
          <p className="alert error">{eucError}</p>
        ) : eucs.length === 0 ? (
          <p className="muted">
            No EUCs are registered in this backend process. Run a successful
            migration to register an EUC.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Version</th>
                  <th>Readiness</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {eucs.map((euc) => (
                  <tr key={euc.name}>
                    <td>{euc.name}</td>
                    <td>{euc.version}</td>
                    <td>
                      <span className={`status-pill ${euc.status === "REGISTERED" ? "ready" : "status-pending"}`}>
                        {euc.status === "REGISTERED" ? "READY" : "ARTIFACT PRESENT"}
                      </span>
                    </td>
                    <td className="table-actions">
                      <button
                        className="text-button"
                        onClick={() => setSelectedEucName(euc.name)}
                      >
                        View
                      </button>
                      <button
                        className="text-button"
                        onClick={() => onExecuteEuc(euc.name)}
                      >
                        Execute
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selectedEucName && (
        <section className="card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Generated standardized EUC artifacts</p>
              <h2>{selectedEucName}</h2>
            </div>
            <button
              className="secondary-button"
              onClick={() => onExecuteEuc(selectedEucName)}
            >
              Execute EUC
            </button>
          </div>
          {detailsError ? (
            <p className="alert error">{detailsError}</p>
          ) : !details ? (
            <Loading label="Loading generated artifacts…" />
          ) : (
            <>
              <dl className="metadata-grid">
                <div><dt>Registry status</dt><dd>{details.status}</dd></div>
                <div><dt>Image</dt><dd>{details.image}:{details.version}</dd></div>
                <div><dt>Generated files</dt><dd>{details.files.length}</dd></div>
                <div>
                  <dt>GitHub repository</dt>
                  <dd>
                    {details.github_url ? (
                      <a href={details.github_url} target="_blank" rel="noreferrer">
                        {details.github_repo}
                      </a>
                    ) : "Not saved"}
                  </dd>
                </div>
              </dl>
              <button
                className="secondary-button"
                type="button"
                onClick={() => void saveSelectedEucToGitHub()}
                disabled={isSavingToGitHub}
              >
                {isSavingToGitHub ? "Saving to GitHub…" : "Save to GitHub"}
              </button>
              {githubError && <p className="alert error">{githubError}</p>}
              {githubSave && (
                <p className="github-save-success" role="status">
                  Saved to{" "}
                  <a href={githubSave.github_url} target="_blank" rel="noreferrer">
                    {githubSave.github_repo}
                  </a>
                  {" · Commit "}
                  <code>{githubSave.github_commit_sha}</code>
                </p>
              )}
              <p className="muted">
                {details.status === "REGISTERED"
                  ? "Registered execution metadata and generated standardized files."
                  : "Generated standardized files were found on disk, but this backend process has not registered this artifact. Execution will resolve it through the existing local registry behavior."}
                {" "}Original owner and support metadata is not persisted by the backend.
              </p>
              {details.files.length === 0 ? (
                <p className="muted">No generated files were returned.</p>
              ) : (
                <div className="file-viewer">
                  <nav className="file-list" aria-label="Generated EUC files">
                    {details.files.map((file) => (
                      <button
                        className={selectedFile === file.path ? "file-button selected" : "file-button"}
                        key={file.path}
                        onClick={() => setSelectedFile(file.path)}
                      >
                        {file.path}
                      </button>
                    ))}
                  </nav>
                  <div className="file-content">
                    <h3>{selectedFile || "Select a file"}</h3>
                    <pre>{selectedFileContent}</pre>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}
    </section>
  ) : (
    <section className="dashboard-layout">
      <section className="card">
        <h2>Execute EUC</h2>
        {eucError && <p className="alert error">{eucError}</p>}
        {eucs.length === 0 && !isLoadingEucs ? (
          <p className="muted">Migrate an EUC successfully before executing it.</p>
        ) : (
          <form className="execute-form" onSubmit={submitExecution}>
            <label className="field">
              <span>EUC</span>
              <select
                value={eucToExecute}
                onChange={(event) => setEucToExecute(event.target.value)}
                required
              >
                {eucs.map((euc) => (
                  <option key={euc.name} value={euc.name}>{euc.name}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>JSON input</span>
              <textarea
                className="json-editor"
                value={executionInput}
                onChange={(event) => setExecutionInput(event.target.value)}
                spellCheck={false}
              />
            </label>
            {inputError && <p className="alert error">{inputError}</p>}
            {executionError && <p className="alert error">{executionError}</p>}
            <button className="submit-button" disabled={isExecuting || isLoadingEucs}>
              {isExecuting ? "Executing…" : "Execute"}
            </button>
          </form>
        )}
        {executionResult && <ExecutionResultView record={executionResult} />}
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Execution history</h2>
            <p>Recent synchronous executions recorded by the backend.</p>
          </div>
          <button
            className="secondary-button"
            onClick={() => void refreshExecutions()}
          >
            Refresh
          </button>
        </div>
        {isLoadingHistory ? (
          <Loading label="Loading execution history…" />
        ) : historyError ? (
          <p className="alert error">{historyError}</p>
        ) : executions.length === 0 ? (
          <p className="muted">No execution records are available.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Execution ID</th>
                  <th>EUC</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Started</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((record) => (
                  <tr key={record.execution_id}>
                    <td>{record.execution_id}</td>
                    <td>{record.euc_name}</td>
                    <td><StatusPill status={record.status} /></td>
                    <td>{formatDuration(record.duration_ms)}</td>
                    <td>{formatTimestamp(record.started_at)}</td>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => void openExecution(record.execution_id)}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selectedExecutionError && <p className="alert error">{selectedExecutionError}</p>}
        {selectedExecution && (
          <ExecutionResultView record={selectedExecution} />
        )}
      </section>
    </section>
  );
}

function ExecutionResultView({ record }: { record: ExecutionRecord }) {
  return (
    <section className={`execution-result ${record.status.toLowerCase()}`}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Execution result</p>
          <h3>{record.euc_name}</h3>
        </div>
        <StatusPill status={record.status} />
      </div>
      <dl className="metadata-grid">
        <div><dt>Execution ID</dt><dd>{record.execution_id}</dd></div>
        <div><dt>Duration</dt><dd>{formatDuration(record.duration_ms)}</dd></div>
        <div><dt>Exit code</dt><dd>{record.exit_code ?? "—"}</dd></div>
        <div><dt>Started</dt><dd>{formatTimestamp(record.started_at)}</dd></div>
        <div><dt>Completed</dt><dd>{formatTimestamp(record.completed_at)}</dd></div>
      </dl>
      <div className="output-grid">
        <OutputBlock label="stdout" value={record.stdout} />
        <OutputBlock label="stderr" value={record.stderr} />
      </div>
    </section>
  );
}

function StatusPill({ status }: { status: ExecutionRecord["status"] }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}>{status}</span>;
}

function OutputBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <h3>{label}</h3>
      <pre className="output-block">{value || "(empty)"}</pre>
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="status-panel loading" role="status">
      <span className="spinner" />
      {label}
    </div>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function formatDuration(duration: number | null): string {
  return duration === null ? "—" : `${duration} ms`;
}

function formatTimestamp(timestamp: string | null): string {
  return timestamp ? new Date(timestamp).toLocaleString() : "—";
}
