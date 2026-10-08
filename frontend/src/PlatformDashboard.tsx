import { FormEvent, useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import {
  approveEuc,
  CertificationResponse,
  EucDetails,
  EucSummary,
  ExecutionRecord,
  executeEuc,
  getEuc,
  getEucs,
  getExecution,
  getExecutions,
  GitHubSaveResponse,
  rejectEuc,
  saveEucToGitHub,
  submitEucForCertification,
  updateEuc,
} from "./api";
import { parseExecutionInput } from "./executionInput";

type DashboardSection =
  | "dashboard"
  | "eucs"
  | "certifications"
  | "executions";

interface PlatformDashboardProps {
  section: DashboardSection;
  initialEucName: string;
  onExecuteEuc: (name: string) => void;
  onNavigate: (section: DashboardSection | "create" | "migration") => void;
}

export default function PlatformDashboard({
  section,
  initialEucName,
  onExecuteEuc,
  onNavigate,
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
  const [isEditingEuc, setIsEditingEuc] = useState(false);
  const [editedFiles, setEditedFiles] = useState<Record<string, string>>({});
  const [editError, setEditError] = useState("");
  const [editNotice, setEditNotice] = useState("");
  const [isSavingEdit, setIsSavingEdit] = useState(false);
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
  const [ownerEmail, setOwnerEmail] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [certificationError, setCertificationError] = useState("");
  const [certificationNotice, setCertificationNotice] = useState("");
  const [isSavingCertification, setIsSavingCertification] = useState(false);

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
        if (
          initialEucName &&
          items.some(
            (item) =>
              item.name === initialEucName &&
              item.certification_status === "CERTIFIED",
          )
        ) {
          return initialEucName;
        }
        return items.some(
          (item) =>
            item.name === current && item.certification_status === "CERTIFIED",
        )
          ? current
          : (items.find((item) => item.certification_status === "CERTIFIED")
              ?.name ?? "");
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

    let input: Record<string, unknown>;
    try {
      input = parseExecutionInput(executionInput);
    } catch (error) {
      setInputError(errorMessage(error));
      return;
    }

    setIsExecuting(true);
    try {
      const record = await executeEuc(
        eucToExecute,
        input,
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

  function startEditingEuc() {
    if (!details) return;
    setEditedFiles(
      Object.fromEntries(
        details.files
          .filter((file) => isEditableBusinessPath(file.path))
          .map((file) => [file.path, file.content]),
      ),
    );
    setEditError("");
    setEditNotice("");
    setIsEditingEuc(true);
  }

  function cancelEditingEuc() {
    setEditedFiles({});
    setEditError("");
    setIsEditingEuc(false);
  }

  async function saveEucEdits() {
    if (!details || isSavingEdit) return;
    const changedFiles = details.files
      .filter(
        (file) =>
          isEditableBusinessPath(file.path) &&
          editedFiles[file.path] !== undefined &&
          editedFiles[file.path] !== file.content,
      )
      .map((file) => ({ path: file.path, content: editedFiles[file.path] }));
    if (changedFiles.length === 0) {
      setEditError("No business-file changes to save.");
      return;
    }
    setEditError("");
    setEditNotice("");
    setIsSavingEdit(true);
    try {
      const result = await updateEuc(details.name, changedFiles);
      await refreshEucs();
      const refreshedDetails = await getEuc(details.name);
      setDetails(refreshedDetails);
      setIsEditingEuc(false);
      setEditedFiles({});
      setEditNotice(
        `Changes saved. Certification status: ${result.certification_status}.`,
      );
    } catch (error) {
      setEditError(errorMessage(error));
    } finally {
      setIsSavingEdit(false);
    }
  }

  async function updateCertification(
    action: "submit" | "approve" | "reject",
  ) {
    if (!details) return;
    setCertificationError("");
    setCertificationNotice("");
    setIsSavingCertification(true);
    try {
      let result: CertificationResponse;
      if (action === "submit") {
        result = await submitEucForCertification(details.name);
      } else if (action === "approve") {
        if (!ownerEmail.trim()) {
          setCertificationError("Enter the approving owner's email address.");
          return;
        }
        if (!window.confirm(`Approve ${details.name} as ${ownerEmail.trim()}?`)) {
          return;
        }
        result = await approveEuc(details.name, ownerEmail.trim());
      } else {
        if (!ownerEmail.trim()) {
          setCertificationError("Enter the rejecting owner's email address.");
          return;
        }
        if (!window.confirm(`Reject ${details.name} as ${ownerEmail.trim()}?`)) {
          return;
        }
        result = await rejectEuc(
          details.name,
          ownerEmail.trim(),
          rejectionReason.trim(),
        );
      }
      setCertificationNotice(
        `Certification status updated to ${result.certification_status}.`,
      );
      await refreshEucs();
      setDetails(await getEuc(details.name));
      setOwnerEmail("");
      setRejectionReason("");
    } catch (error) {
      setCertificationError(errorMessage(error));
    } finally {
      setIsSavingCertification(false);
    }
  }

  const selectedFileContent = details?.files.find(
    (file) => file.path === selectedFile,
  )?.content;
  const pendingCertifications = eucs.filter(
    (euc) => euc.certification_status === "PENDING_APPROVAL",
  );
  const certifiedEucs = eucs.filter(
    (euc) => euc.certification_status === "CERTIFIED",
  );

  useEffect(() => {
    if (
      section === "certifications" &&
      !pendingCertifications.some((euc) => euc.name === selectedEucName) &&
      pendingCertifications[0]
    ) {
      setSelectedEucName(pendingCertifications[0].name);
    }
  }, [section, pendingCertifications, selectedEucName]);

  return section === "dashboard" ? (
    <section className="dashboard-layout">
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Platform dashboard</h2>
            <p>Manage EUCs through creation, certification, and execution.</p>
          </div>
          <button className="secondary-button" onClick={() => void refreshEucs()}>
            Refresh
          </button>
        </div>
        {eucError && <p className="alert error">{eucError}</p>}
        <div className="dashboard-cards">
          <button className="summary-card" onClick={() => onNavigate("eucs")}>
            <span>EUCs</span><strong>{isLoadingEucs ? "…" : eucs.length}</strong>
          </button>
          <button className="summary-card" onClick={() => onNavigate("certifications")}>
            <span>Pending certification</span>
            <strong>{isLoadingEucs ? "…" : pendingCertifications.length}</strong>
          </button>
          <button className="summary-card" onClick={() => onNavigate("executions")}>
            <span>Certified and executable</span>
            <strong>{isLoadingEucs ? "…" : certifiedEucs.length}</strong>
          </button>
        </div>
        <div className="github-actions">
          <button className="secondary-button" onClick={() => onNavigate("create")}>
            Create EUC
          </button>
          <button className="secondary-button" onClick={() => onNavigate("migration")}>
            Migrate MAXX EUC
          </button>
        </div>
      </section>
      <section className="card">
        <h2>Pending approval</h2>
        {isLoadingEucs ? (
          <Loading label="Loading certification queue…" />
        ) : pendingCertifications.length === 0 ? (
          <p className="muted">No EUCs are waiting for owner approval.</p>
        ) : (
          <EucTable
            eucs={pendingCertifications}
            onView={(name) => {
              setSelectedEucName(name);
              onNavigate("eucs");
            }}
            onExecute={onExecuteEuc}
          />
        )}
      </section>
    </section>
  ) : section === "certifications" ? (
    <section className="dashboard-layout">
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Certifications</h2>
            <p>One listed owner is sufficient to approve or reject an EUC.</p>
          </div>
          <button className="secondary-button" onClick={() => void refreshEucs()}>
            Refresh
          </button>
        </div>
        {isLoadingEucs ? (
          <Loading label="Loading certification queue…" />
        ) : eucError ? (
          <p className="alert error">{eucError}</p>
        ) : pendingCertifications.length === 0 ? (
          <p className="muted">No EUCs are pending approval.</p>
        ) : (
          <EucTable
            eucs={pendingCertifications}
            onView={setSelectedEucName}
            onExecute={onExecuteEuc}
          />
        )}
      </section>
      {selectedEucName &&
        pendingCertifications.some((euc) => euc.name === selectedEucName) && (
        <CertificationReview
          name={selectedEucName}
          details={details}
          loading={!details && !detailsError}
          error={detailsError}
          actionError={certificationError}
          actionNotice={certificationNotice}
          ownerEmail={ownerEmail}
          rejectionReason={rejectionReason}
          busy={isSavingCertification}
          setOwnerEmail={setOwnerEmail}
          setRejectionReason={setRejectionReason}
          onApprove={() => void updateCertification("approve")}
          onReject={() => void updateCertification("reject")}
          onViewEuc={() => onNavigate("eucs")}
        />
      )}
    </section>
  ) : section === "eucs" ? (
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
          <EucTable
            eucs={eucs}
            onView={setSelectedEucName}
            onExecute={onExecuteEuc}
          />
        )}
      </section>

      {selectedEucName && (
        <section className="card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Generated standardized EUC artifacts</p>
              <h2>{selectedEucName}</h2>
            </div>
            {details?.certification_status === "CERTIFIED" && (
              <button
                className="secondary-button"
                onClick={() => onExecuteEuc(selectedEucName)}
              >
                Execute EUC
              </button>
            )}
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
                  <dt>Owners</dt>
                  <dd>{details.owners.length ? details.owners.join(", ") : "Not available"}</dd>
                </div>
                <div>
                  <dt>Certification</dt>
                  <dd><CertificationPill status={details.certification_status} /></dd>
                </div>
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
              <div className="github-actions">
                {details.github_url ? (
                  <a className="secondary-button link-button" href={details.github_url} target="_blank" rel="noreferrer">
                    Open Repository
                  </a>
                ) : null}
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => void saveSelectedEucToGitHub()}
                  disabled={isSavingToGitHub}
                >
                  {isSavingToGitHub
                    ? "Saving to GitHub…"
                    : details.github_url
                      ? "Save update to GitHub"
                      : "Save to GitHub"}
                </button>
                {!isEditingEuc ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={startEditingEuc}
                  >
                    Edit EUC
                  </button>
                ) : (
                  <>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={cancelEditingEuc}
                      disabled={isSavingEdit}
                    >
                      Cancel
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => void saveEucEdits()}
                      disabled={isSavingEdit}
                    >
                      {isSavingEdit ? "Saving changes…" : "Save Changes"}
                    </button>
                  </>
                )}
                {details.certification_status === "DRAFT" ||
                details.certification_status === "REJECTED" ? (
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={isSavingCertification}
                    onClick={() => void updateCertification("submit")}
                  >
                    {isSavingCertification ? "Submitting…" : "Submit for certification"}
                  </button>
                ) : details.certification_status === "PENDING_APPROVAL" ? (
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => onNavigate("certifications")}
                  >
                    Review certification
                  </button>
                ) : null}
              </div>
              {githubError && <p className="alert error">{githubError}</p>}
              {editError && <p className="alert error">{editError}</p>}
              {editNotice && (
                <p className="alert success-message" role="status">
                  {editNotice}
                </p>
              )}
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
              {certificationNotice && <p className="alert success-message" role="status">{certificationNotice}</p>}
              {certificationError && <p className="alert error">{certificationError}</p>}
              {details.certification_status === "CERTIFIED" ? (
                <p className="certification-callout certified-callout">
                  CERTIFIED — approved by <strong>{details.approved_by}</strong>
                  {" "}at {formatTimestamp(details.approved_at)}.
                </p>
              ) : (
                <p className="certification-callout">
                  {details.certification_status === "PENDING_APPROVAL"
                    ? "PENDING APPROVAL — this EUC must be approved before it can be executed."
                    : "This EUC must be certified before it can be executed."}
                  {details.certification_status === "REJECTED" &&
                    ` Rejected by ${details.rejected_by ?? "an owner"} at ${formatTimestamp(details.rejected_at)}.`}
                </p>
              )}
              <dl className="metadata-grid">
                {details.approved_by && (
                  <div><dt>Approved by</dt><dd>{details.approved_by}</dd></div>
                )}
                {details.approved_at && (
                  <div><dt>Approved at</dt><dd>{formatTimestamp(details.approved_at)}</dd></div>
                )}
                {details.rejected_by && (
                  <div><dt>Rejected by</dt><dd>{details.rejected_by}</dd></div>
                )}
                {details.rejected_at && (
                  <div><dt>Rejected at</dt><dd>{formatTimestamp(details.rejected_at)}</dd></div>
                )}
              </dl>
              {details.rejection_reason && (
                <p className="muted">Rejection reason: {details.rejection_reason}</p>
              )}
              <p className="muted">
                {details.status === "REGISTERED"
                  ? "Generated standardized files are available from the local registry."
                  : "Generated files exist on disk, but this process has not registered the artifact. It must be registered and certified before execution."}
                {" "}Description and support-team metadata are not returned by the current EUC API.
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
                    <div className="monaco-editor read-only-editor">
                      <Editor
                        height="320px"
                        language={selectedFile?.endsWith(".py") ? "python" : "plaintext"}
                        value={
                          isEditingEuc && isEditableBusinessPath(selectedFile)
                            ? editedFiles[selectedFile] ?? selectedFileContent ?? ""
                            : selectedFileContent ?? ""
                        }
                        onChange={(value) => {
                          if (isEditingEuc && isEditableBusinessPath(selectedFile)) {
                            setEditedFiles((current) => ({
                              ...current,
                              [selectedFile]: value ?? "",
                            }));
                          }
                        }}
                        theme="vs"
                        options={{
                          readOnly:
                            !isEditingEuc || !isEditableBusinessPath(selectedFile),
                          automaticLayout: true,
                          fontSize: 13,
                          lineNumbers: "on",
                          minimap: { enabled: false },
                          scrollBeyondLastLine: false,
                          wordWrap: "on",
                        }}
                      />
                    </div>
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
        {certifiedEucs.length === 0 && !isLoadingEucs ? (
          <p className="muted">No certified EUCs are available to execute. Submit an EUC for certification and have one of its owners approve it first.</p>
        ) : (
          <form className="execute-form" onSubmit={submitExecution}>
            <label className="field">
              <span>EUC</span>
              <select
                value={eucToExecute}
                onChange={(event) => setEucToExecute(event.target.value)}
                required
              >
                {certifiedEucs.map((euc) => (
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

function EucTable({
  eucs,
  onView,
  onExecute,
}: {
  eucs: EucSummary[];
  onView: (name: string) => void;
  onExecute: (name: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Owners</th>
            <th>Certification</th>
            <th>GitHub</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {eucs.map((euc) => (
            <tr key={euc.name}>
              <td>
                <strong>{euc.name}</strong>
                <span className="table-subtext">{euc.version} · {euc.status}</span>
              </td>
              <td>{euc.owners.length ? euc.owners.join(", ") : "—"}</td>
              <td><CertificationPill status={euc.certification_status} /></td>
              <td>
                {euc.github_url ? (
                  <a href={euc.github_url} target="_blank" rel="noreferrer">
                    {euc.github_repo ?? "Open repository"}
                  </a>
                ) : "—"}
              </td>
              <td className="table-actions">
                <button className="text-button" onClick={() => onView(euc.name)}>
                  {euc.certification_status === "PENDING_APPROVAL" ? "Review" : "View"}
                </button>
                {euc.certification_status === "CERTIFIED" && (
                  <button className="text-button" onClick={() => onExecute(euc.name)}>
                    Execute
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CertificationReview({
  name,
  details,
  loading,
  error,
  actionError,
  actionNotice,
  ownerEmail,
  rejectionReason,
  busy,
  setOwnerEmail,
  setRejectionReason,
  onApprove,
  onReject,
  onViewEuc,
}: {
  name: string;
  details: EucDetails | null;
  loading: boolean;
  error: string;
  actionError: string;
  actionNotice: string;
  ownerEmail: string;
  rejectionReason: string;
  busy: boolean;
  setOwnerEmail: (value: string) => void;
  setRejectionReason: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onViewEuc: () => void;
}) {
  const [selectedFile, setSelectedFile] = useState("");
  useEffect(() => {
    if (details) {
      setSelectedFile((current) =>
        details.files.some((file) => file.path === current)
          ? current
          : (details.files[0]?.path ?? ""),
      );
    }
  }, [details]);
  const currentFile = details?.files.find((file) => file.path === selectedFile);

  return (
    <section className="card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Certification review</p>
          <h2>{name}</h2>
        </div>
        {details && <CertificationPill status={details.certification_status} />}
      </div>
      {error ? (
        <p className="alert error">{error}</p>
      ) : loading ? (
        <Loading label="Loading EUC review…" />
      ) : !details ? (
        <p className="muted">EUC details are unavailable.</p>
      ) : (
        <>
          <dl className="metadata-grid">
            <div><dt>Name</dt><dd>{details.name}</dd></div>
            <div><dt>Owners</dt><dd>{details.owners.length ? details.owners.join(", ") : "—"}</dd></div>
            <div><dt>Version</dt><dd>{details.version}</dd></div>
            <div>
              <dt>GitHub repository</dt>
              <dd>
                {details.github_url ? (
                  <a href={details.github_url} target="_blank" rel="noreferrer">
                    {details.github_repo ?? details.github_url}
                  </a>
                ) : "Not saved"}
              </dd>
            </div>
          </dl>
          <p className="muted">
            The current EUC API does not return description or support-team metadata.
            The backend validates generated files on submission; no separate validation
            report endpoint is available.
          </p>
          {details.certification_status === "PENDING_APPROVAL" ? (
            <>
              <label className="field approval-field">
                <span>Owner email for approval/rejection</span>
                <input
                  type="email"
                  value={ownerEmail}
                  onChange={(event) => setOwnerEmail(event.target.value)}
                  placeholder="owner@example.com"
                />
              </label>
              <label className="field approval-field">
                <span>Rejection reason (optional)</span>
                <textarea
                  value={rejectionReason}
                  onChange={(event) => setRejectionReason(event.target.value)}
                  rows={3}
                />
              </label>
              <p className="muted">
                Any one listed owner may approve. The backend verifies the supplied email.
              </p>
              {actionError && <p className="alert error">{actionError}</p>}
              {actionNotice && <p className="alert success-message" role="status">{actionNotice}</p>}
              <div className="github-actions">
                <button className="submit-button compact-button" onClick={onApprove} disabled={busy}>
                  {busy ? "Saving…" : "Approve"}
                </button>
                <button className="remove-button" onClick={onReject} disabled={busy}>
                  Reject
                </button>
                <button className="secondary-button" onClick={onViewEuc}>
                  Open EUC details
                </button>
              </div>
            </>
          ) : details.certification_status === "CERTIFIED" ? (
            <p className="certification-callout certified-callout">
              Approved by <strong>{details.approved_by}</strong> at{" "}
              {formatTimestamp(details.approved_at)}.
            </p>
          ) : (
            <p className="muted">
              This EUC is no longer pending approval. Refresh the queue to see current status.
            </p>
          )}
          <h3>Generated standardized EUC files</h3>
          {details.files.length === 0 ? (
            <p className="muted">No generated files were returned.</p>
          ) : (
            <div className="file-viewer">
              <nav className="file-list" aria-label="Files for certification review">
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
                <h3>{selectedFile}</h3>
                <div className="monaco-editor read-only-editor">
                  <Editor
                    height="320px"
                    language={selectedFile.endsWith(".py") ? "python" : "plaintext"}
                    value={currentFile?.content ?? ""}
                    theme="vs"
                    options={{
                      readOnly: true,
                      automaticLayout: true,
                      fontSize: 13,
                      lineNumbers: "on",
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      wordWrap: "on",
                    }}
                  />
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function CertificationPill({
  status,
}: {
  status: EucSummary["certification_status"];
}) {
  return (
    <span className={`status-pill certification-${status.toLowerCase()}`}>
      {status}
    </span>
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

function isEditableBusinessPath(path: string): boolean {
  return (
    path === "src/main.py" ||
    path === "src/logic.py" ||
    (/^tests\/[A-Za-z0-9][A-Za-z0-9._-]*\.py$/.test(path) &&
      path !== "tests/test_euc_contract.py")
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
