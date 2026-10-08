import { FormEvent, useState } from "react";
import {
  EucMetadata,
  MigrationResult,
  migrateEuc,
} from "./api";
import {
  addDependency,
  addSecretReference,
  buildMigrationInput,
  removeDependency,
  removeSecretReference,
} from "./migrationForm";

const initialMetadata: EucMetadata = {
  name: "",
  description: null,
  python_version: "3.12",
  owner_team: "",
  support_team: "",
  schedule: null,
  sharepoint_url: null,
  secret_references: [],
  dependencies: [],
};

const initialSource = `def run(json_input):
    return json_input
`;

const requiredMetadataFields = new Set<keyof EucMetadata>([
  "name",
  "python_version",
  "owner_team",
  "support_team",
]);

function App() {
  const [metadata, setMetadata] = useState<EucMetadata>(initialMetadata);
  const [sourceCode, setSourceCode] = useState(initialSource);
  const [result, setResult] = useState<MigrationResult | null>(null);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const canSubmit =
    metadata.name.trim() !== "" &&
    metadata.owner_team.trim() !== "" &&
    metadata.support_team.trim() !== "" &&
    sourceCode.trim() !== "";

  function updateMetadata(field: keyof EucMetadata, value: string) {
    setMetadata((current) => ({
      ...current,
      [field]: requiredMetadataFields.has(field)
        ? value
        : value.trim() === ""
          ? null
          : value,
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || isSubmitting) return;

    setError("");
    setResult(null);
    setIsSubmitting(true);
    const input = buildMigrationInput(metadata, sourceCode);

    try {
      setResult(await migrateEuc(input));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The migration could not be completed.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="hero">
        <p className="eyebrow">MAXX modernization</p>
        <h1>EUC Migration Platform</h1>
        <p className="subtitle">
          Transform a MAXX Python EUC into a standardized, validated application.
        </p>
      </header>

      <form className="migration-form" onSubmit={handleSubmit}>
        <section className="card">
          <h2>EUC metadata</h2>
          <div className="field-grid">
            <Field label="Name" required>
              <input
                required
                value={metadata.name}
                onChange={(event) => updateMetadata("name", event.target.value)}
                placeholder="customer-reconciliation"
              />
            </Field>
            <Field label="Python version" required>
              <input
                required
                value={metadata.python_version}
                onChange={(event) =>
                  updateMetadata("python_version", event.target.value)
                }
              />
            </Field>
            <Field label="Owner team" required>
              <input
                required
                value={metadata.owner_team}
                onChange={(event) =>
                  updateMetadata("owner_team", event.target.value)
                }
                placeholder="Finance Automation"
              />
            </Field>
            <Field label="Support team" required>
              <input
                required
                value={metadata.support_team}
                onChange={(event) =>
                  updateMetadata("support_team", event.target.value)
                }
                placeholder="Platform Support"
              />
            </Field>
            <Field label="Description">
              <input
                value={metadata.description ?? ""}
                onChange={(event) =>
                  updateMetadata("description", event.target.value)
                }
                placeholder="What does this EUC do?"
              />
            </Field>
            <Field label="Schedule">
              <input
                value={metadata.schedule ?? ""}
                onChange={(event) => updateMetadata("schedule", event.target.value)}
                placeholder="Optional schedule"
              />
            </Field>
            <Field label="SharePoint URL" wide>
              <input
                type="url"
                value={metadata.sharepoint_url ?? ""}
                onChange={(event) =>
                  updateMetadata("sharepoint_url", event.target.value)
                }
                placeholder="https://..."
              />
            </Field>
          </div>
        </section>

        <section className="card">
          <div className="section-heading">
            <div>
              <h2>Secret References</h2>
              <p>Declare the secret metadata required by this EUC.</p>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() =>
                setMetadata((current) => ({
                  ...current,
                  secret_references: addSecretReference(current.secret_references),
                }))
              }
            >
              Add secret
            </button>
          </div>
          {metadata.secret_references.length === 0 ? (
            <p className="muted">No secret references added.</p>
          ) : (
            <div className="repeatable-list">
              {metadata.secret_references.map((reference, index) => (
                <div className="repeatable-row" key={`secret-${index}`}>
                  <Field label="Name">
                    <input
                      value={reference.name}
                      onChange={(event) =>
                        setMetadata((current) => ({
                          ...current,
                          secret_references: current.secret_references.map(
                            (item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, name: event.target.value }
                                : item,
                          ),
                        }))
                      }
                      placeholder="client_id"
                    />
                  </Field>
                  <Field label="Vault">
                    <input
                      value={reference.vault}
                      onChange={(event) =>
                        setMetadata((current) => ({
                          ...current,
                          secret_references: current.secret_references.map(
                            (item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, vault: event.target.value }
                                : item,
                          ),
                        }))
                      }
                      placeholder="platform-secrets"
                    />
                  </Field>
                  <Field label="Key">
                    <input
                      value={reference.key}
                      onChange={(event) =>
                        setMetadata((current) => ({
                          ...current,
                          secret_references: current.secret_references.map(
                            (item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, key: event.target.value }
                                : item,
                          ),
                        }))
                      }
                      placeholder="customer-client-id"
                    />
                  </Field>
                  <button
                    className="remove-button"
                    type="button"
                    onClick={() =>
                      setMetadata((current) => ({
                        ...current,
                        secret_references: removeSecretReference(
                          current.secret_references,
                          index,
                        ),
                      }))
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
              <h2>Dependencies</h2>
              <p>List the Python packages required by this EUC.</p>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() =>
                setMetadata((current) => ({
                  ...current,
                  dependencies: addDependency(current.dependencies),
                }))
              }
            >
              Add dependency
            </button>
          </div>
          {metadata.dependencies.length === 0 ? (
            <p className="muted">No dependencies added.</p>
          ) : (
            <div className="repeatable-list">
              {metadata.dependencies.map((dependency, index) => (
                <div className="dependency-row" key={`dependency-${index}`}>
                  <Field label={`Package ${index + 1}`}>
                    <input
                      value={dependency}
                      onChange={(event) =>
                        setMetadata((current) => ({
                          ...current,
                          dependencies: current.dependencies.map(
                            (item, itemIndex) =>
                              itemIndex === index ? event.target.value : item,
                          ),
                        }))
                      }
                      placeholder="requests"
                    />
                  </Field>
                  <button
                    className="remove-button"
                    type="button"
                    onClick={() =>
                      setMetadata((current) => ({
                        ...current,
                        dependencies: removeDependency(
                          current.dependencies,
                          index,
                        ),
                      }))
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
              <h2>MAXX Python source</h2>
              <p>Paste the primary source file for this migration.</p>
            </div>
            <span className="file-badge">main.py</span>
          </div>
          <textarea
            className="source-editor"
            value={sourceCode}
            onChange={(event) => setSourceCode(event.target.value)}
            spellCheck={false}
            aria-label="MAXX Python source code"
          />
        </section>

        {error && <div className="alert error">{error}</div>}

        <button className="submit-button" type="submit" disabled={!canSubmit || isSubmitting}>
          {isSubmitting ? "Migrating…" : "Migrate EUC"}
        </button>
      </form>

      {isSubmitting && (
        <div className="status-panel loading" role="status">
          <span className="spinner" />
          Running analysis, transformation, and validation…
        </div>
      )}

      {result && <MigrationResultView result={result} />}
    </main>
  );
}

interface FieldProps {
  label: string;
  required?: boolean;
  wide?: boolean;
  children: React.ReactNode;
}

function Field({ label, required, wide, children }: FieldProps) {
  return (
    <label className={wide ? "field wide" : "field"}>
      <span>
        {label} {required && <b>*</b>}
      </span>
      {children}
    </label>
  );
}

function MigrationResultView({ result }: { result: MigrationResult }) {
  const successful = result.status === "COMPLETED" && result.validation.valid;
  return (
    <section className={`result-card ${successful ? "success" : "failure"}`}>
      <div className="result-heading">
        <div>
          <p className="eyebrow">{successful ? "Migration completed" : "Migration failed"}</p>
          <h2>{result.generated_euc.name}</h2>
        </div>
        <span className="status-pill">{result.status}</span>
      </div>

      <p className="validation-line">
        Validation: <strong>{result.validation.valid ? "VALID" : "INVALID"}</strong>
      </p>

      <div className="result-grid">
        <ResultList title="Generated files" items={result.generated_euc.files.map((file) => file.path)} />
        <ResultList title="Validation errors" items={result.validation.errors} emptyLabel="None" />
        <ResultList
          title="Warnings"
          items={[...result.validation.warnings, ...result.generated_euc.warnings]}
          emptyLabel="None"
        />
        <ResultList
          title="Unsupported features"
          items={result.generated_euc.unsupported_features}
          emptyLabel="None"
        />
      </div>
    </section>
  );
}

function ResultList({
  title,
  items,
  emptyLabel = "None",
}: {
  title: string;
  items: string[];
  emptyLabel?: string;
}) {
  return (
    <div className="result-list">
      <h3>{title}</h3>
      {items.length > 0 ? (
        <ul>
          {items.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">{emptyLabel}</p>
      )}
    </div>
  );
}

export default App;
