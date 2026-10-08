import { FormEvent, useState } from "react";
import Editor from "@monaco-editor/react";
import {
  createEuc,
  EucMetadata,
  GitHubSaveResponse,
  MigrationResult,
  saveEucToGitHub,
} from "./api";

interface CreateEucFormProps {
  onViewEuc: (name: string) => void;
}

const defaultSource = `def run(input_data, context):
    name = input_data.get("name", "world")
    return {"message": f"Hello, {name}!"}
`;

export default function CreateEucForm({ onViewEuc }: CreateEucFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [owners, setOwners] = useState([""]);
  const [supportTeam, setSupportTeam] = useState("");
  const [pythonVersion, setPythonVersion] = useState("3.12");
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [sourceCode, setSourceCode] = useState(defaultSource);
  const [result, setResult] = useState<MigrationResult | null>(null);
  const [githubSave, setGithubSave] = useState<GitHubSaveResponse | null>(null);
  const [githubError, setGithubError] = useState("");
  const [isSavingToGitHub, setIsSavingToGitHub] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const canSubmit =
    name.trim() !== "" &&
    pythonVersion.trim() !== "" &&
    sourceCode.trim() !== "" &&
    owners.length > 0 &&
    owners.every((owner) => isValidEmail(owner.trim()));

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || isSubmitting) return;

    setError("");
    setResult(null);
    setGithubSave(null);
    setGithubError("");
    setIsSubmitting(true);
    const metadata: EucMetadata = {
      name: name.trim(),
      description: description.trim() || null,
      python_version: pythonVersion.trim(),
      owners: owners.map((owner) => owner.trim()),
      support_team: supportTeam.trim() || null,
      schedule: null,
      sharepoint_url: null,
      secret_references: [],
      dependencies: dependencies.map((item) => item.trim()).filter(Boolean),
    };

    try {
      setResult(
        await createEuc({
          metadata,
          source_code: sourceCode,
          source_filename: "main.py",
        }),
      );
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The EUC could not be created.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const succeeded =
    result?.status === "COMPLETED" && result.validation.valid;

  async function saveCreatedEucToGitHub() {
    if (!result || !succeeded) return;
    setGithubError("");
    setGithubSave(null);
    setIsSavingToGitHub(true);
    try {
      setGithubSave(await saveEucToGitHub(result.generated_euc.name));
    } catch (requestError) {
      setGithubError(
        requestError instanceof Error
          ? requestError.message
          : "The EUC could not be saved to GitHub.",
      );
    } finally {
      setIsSavingToGitHub(false);
    }
  }

  return (
    <section className="dashboard-layout">
      <form className="migration-form" onSubmit={handleSubmit}>
        <section className="card">
          <h2>Create EUC</h2>
          <p className="muted">
            Provide platform-compatible Python source. The platform validates,
            packages, builds, and registers the EUC without MAXX transformation.
          </p>
          <div className="field-grid">
            <label className="field">
              <span>Name <b>*</b></span>
              <input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="customer-greeting"
              />
            </label>
            <label className="field">
              <span>Python version <b>*</b></span>
              <input
                required
                value={pythonVersion}
                onChange={(event) => setPythonVersion(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Description</span>
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What does this EUC do?"
              />
            </label>
            <label className="field">
              <span>Support team (optional)</span>
              <input
                value={supportTeam}
                onChange={(event) => setSupportTeam(event.target.value)}
                placeholder="Platform Engineering"
              />
            </label>
          </div>
          <div className="field owner-fields">
            <span>Owners <b>*</b></span>
            {owners.map((owner, index) => (
              <div className="dependency-row" key={`owner-${index}`}>
                <input
                  type="email"
                  required
                  aria-label={`Owner email ${index + 1}`}
                  value={owner}
                  onChange={(event) =>
                    setOwners((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? event.target.value : item,
                      ),
                    )
                  }
                  placeholder="aman@example.com"
                />
                <button
                  className="remove-button"
                  type="button"
                  onClick={() =>
                    setOwners((current) =>
                      current.filter((_, itemIndex) => itemIndex !== index),
                    )
                  }
                >
                  Remove owner
                </button>
              </div>
            ))}
            <button
              className="secondary-button"
              type="button"
              onClick={() => setOwners((current) => [...current, ""])}
            >
              + Add owner
            </button>
          </div>
        </section>

        <section className="card">
          <div className="section-heading">
            <div>
              <h2>Dependencies</h2>
              <p>Python packages required by this EUC.</p>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setDependencies((current) => [...current, ""])}
            >
              + Add dependency
            </button>
          </div>
          {dependencies.length === 0 ? (
            <p className="muted">No dependencies added.</p>
          ) : (
            <div className="repeatable-list">
              {dependencies.map((dependency, index) => (
                <div className="dependency-row" key={`dependency-${index}`}>
                  <input
                    aria-label={`Dependency ${index + 1}`}
                    value={dependency}
                    onChange={(event) =>
                      setDependencies((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? event.target.value : item,
                        ),
                      )
                    }
                    placeholder="requests"
                  />
                  <button
                    className="remove-button"
                    type="button"
                    onClick={() =>
                      setDependencies((current) =>
                        current.filter((_, itemIndex) => itemIndex !== index),
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="section-heading">
            <div>
              <h2>Python source</h2>
              <p>Source is analyzed and validated without being executed.</p>
            </div>
            <span className="file-badge">main.py</span>
          </div>
          <div className="monaco-editor" aria-label="Python source editor">
            <Editor
              height="360px"
              language="python"
              value={sourceCode}
              onChange={(value) => setSourceCode(value ?? "")}
              theme="vs"
              options={{
                automaticLayout: true,
                fontSize: 14,
                lineNumbers: "on",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: "on",
              }}
            />
          </div>
        </section>

        {error && <p className="alert error">{error}</p>}
        <button className="submit-button" disabled={!canSubmit || isSubmitting}>
          {isSubmitting ? "Creating and building…" : "Create EUC"}
        </button>
      </form>

      {isSubmitting && (
        <div className="status-panel loading" role="status">
          <span className="spinner" />
          Validating source, generating artifacts, and building the Docker image…
        </div>
      )}

      {result && (
        <section className={`result-card ${succeeded ? "success" : "failure"}`}>
          <div className="result-heading">
            <div>
              <p className="eyebrow">Direct EUC creation</p>
              <h2>{result.generated_euc.name}</h2>
            </div>
            <span className="status-pill">{result.status}</span>
          </div>
          <p className="validation-line">
            Validation: <strong>{result.validation.valid ? "VALID" : "INVALID"}</strong>
          </p>
          {succeeded && (
            <div className="github-actions">
              <button
                className="secondary-button"
                type="button"
                onClick={() => onViewEuc(result.generated_euc.name)}
              >
                View created EUC
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => void saveCreatedEucToGitHub()}
                disabled={isSavingToGitHub}
              >
                {isSavingToGitHub ? "Saving to GitHub…" : "Save to GitHub"}
              </button>
            </div>
          )}
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
          {result.validation.errors.length > 0 && (
            <ul className="creation-errors">
              {result.validation.errors.map((item, index) => (
                <li key={`${item}-${index}`}>{item}</li>
              ))}
            </ul>
          )}
          <p className="muted">
            {succeeded
              ? "The generated artifact was built and registered as executable."
              : "This EUC was not registered as executable."}
          </p>
        </section>
      )}
    </section>
  );
}

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}
