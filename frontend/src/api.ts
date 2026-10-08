export interface SecretReference {
  name: string;
  vault: string;
  key: string;
}

export interface EucMetadata {
  name: string;
  description: string | null;
  python_version: string;
  owners: string[];
  support_team: string | null;
  schedule: string | null;
  sharepoint_url: string | null;
  secret_references: SecretReference[];
  dependencies: string[];
}

export interface MigrationInput {
  metadata: EucMetadata;
  source_code: string;
  source_filename: string;
}

export type EucCreationInput = MigrationInput;

export interface GeneratedFile {
  path: string;
  content: string;
}

export interface GeneratedEuc {
  name: string;
  files: GeneratedFile[];
  warnings: string[];
  unsupported_features: string[];
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export type MigrationStatus =
  | "ANALYZING"
  | "TRANSFORMING"
  | "VALIDATING"
  | "COMPLETED"
  | "FAILED";

export interface MigrationResult {
  status: MigrationStatus;
  generated_euc: GeneratedEuc;
  validation: ValidationResult;
}

export interface EucSummary {
  name: string;
  image: string;
  version: string;
  status: "REGISTERED" | "ARTIFACT_PRESENT";
  owners: string[];
  certification_status: CertificationStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  github_repo: string | null;
  github_url: string | null;
  github_commit_sha: string | null;
}

export type CertificationStatus =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "CERTIFIED"
  | "REJECTED";

export interface EucDetails extends EucSummary {
  files: GeneratedFile[];
}

export interface CertificationResponse {
  euc_name: string;
  owners: string[];
  certification_status: CertificationStatus;
  approved_by: string | null;
  approved_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
}

export type ExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "TIMED_OUT";

export interface ExecutionRecord {
  execution_id: string;
  euc_name: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  stdout: string;
  stderr: string;
}

export interface GitHubSaveResponse {
  euc_name: string;
  github_repo: string;
  github_url: string;
  github_commit_sha: string;
}

export interface EucEditResponse {
  euc_name: string;
  certification_status: CertificationStatus;
}

const API_BASE = "http://localhost:8000/api";

export async function migrateEuc(input: MigrationInput): Promise<MigrationResult> {
  const payload = await request("/migrations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  if (!isMigrationResult(payload)) {
    throw new Error("The migration service returned an unexpected response.");
  }
  return payload;
}

export async function createEuc(
  input: EucCreationInput,
): Promise<MigrationResult> {
  const payload = await request("/eucs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!isMigrationResult(payload)) {
    throw new Error("The EUC service returned an unexpected creation response.");
  }
  return payload;
}

export async function getEucs(): Promise<EucSummary[]> {
  const payload = await request("/eucs");
  if (
    !Array.isArray(payload) ||
    !payload.every(isEucSummary)
  ) {
    throw new Error("The EUC service returned an unexpected list response.");
  }
  return payload.map((item) => ({
    ...item,
    owners: item.owners ?? [],
    certification_status: item.certification_status ?? "DRAFT",
    approved_by: nullableString(item.approved_by),
    approved_at: nullableString(item.approved_at),
    rejected_by: nullableString(item.rejected_by),
    rejected_at: nullableString(item.rejected_at),
    rejection_reason: nullableString(item.rejection_reason),
  }));
}

export async function saveEucToGitHub(
  eucName: string,
): Promise<GitHubSaveResponse> {
  const payload = await request(
    `/eucs/${encodeURIComponent(eucName)}/github`,
    { method: "POST" },
  );
  if (
    !isRecord(payload) ||
    typeof payload.euc_name !== "string" ||
    typeof payload.github_repo !== "string" ||
    typeof payload.github_url !== "string" ||
    typeof payload.github_commit_sha !== "string"
  ) {
    throw new Error("The GitHub service returned an unexpected response.");
  }
  return {
    euc_name: payload.euc_name,
    github_repo: payload.github_repo,
    github_url: payload.github_url,
    github_commit_sha: payload.github_commit_sha,
  };
}

export async function submitEucForCertification(
  eucName: string,
): Promise<CertificationResponse> {
  return certificationRequest(
    `/eucs/${encodeURIComponent(eucName)}/certification/submit`,
  );
}

export async function approveEuc(
  eucName: string,
  ownerEmail: string,
): Promise<CertificationResponse> {
  return certificationRequest(
    `/eucs/${encodeURIComponent(eucName)}/certification/approve`,
    { owner_email: ownerEmail },
  );
}

export async function rejectEuc(
  eucName: string,
  ownerEmail: string,
  reason: string,
): Promise<CertificationResponse> {
  return certificationRequest(
    `/eucs/${encodeURIComponent(eucName)}/certification/reject`,
    { owner_email: ownerEmail, reason: reason || null },
  );
}

async function certificationRequest(
  path: string,
  body?: { owner_email: string; reason?: string | null },
): Promise<CertificationResponse> {
  const payload = await request(path, {
    method: "POST",
    ...(body
      ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
  if (!isCertificationResponse(payload)) {
    throw new Error("The certification service returned an unexpected response.");
  }
  return payload;
}

export async function getEuc(name: string): Promise<EucDetails> {
  const payload = await request(`/eucs/${encodeURIComponent(name)}`);
  if (
    !isRecord(payload) ||
    typeof payload.name !== "string" ||
    typeof payload.image !== "string" ||
    typeof payload.version !== "string" ||
    (payload.status !== "REGISTERED" && payload.status !== "ARTIFACT_PRESENT") ||
    !Array.isArray(payload.files) ||
    !payload.files.every(isGeneratedFile)
  ) {
    throw new Error("The EUC service returned unexpected details.");
  }
  return {
    name: payload.name,
    image: payload.image,
    version: payload.version,
    status: payload.status,
    owners: isStringArray(payload.owners) ? payload.owners : [],
    certification_status: isCertificationStatus(payload.certification_status)
      ? payload.certification_status
      : "DRAFT",
    approved_by: nullableString(payload.approved_by),
    approved_at: nullableString(payload.approved_at),
    rejected_by: nullableString(payload.rejected_by),
    rejected_at: nullableString(payload.rejected_at),
    rejection_reason: nullableString(payload.rejection_reason),
    github_repo: typeof payload.github_repo === "string" ? payload.github_repo : null,
    github_url: typeof payload.github_url === "string" ? payload.github_url : null,
    github_commit_sha:
      typeof payload.github_commit_sha === "string"
        ? payload.github_commit_sha
        : null,
    files: payload.files,
  };
}

export async function updateEuc(
  eucName: string,
  files: GeneratedFile[],
): Promise<EucEditResponse> {
  const payload = await request(`/eucs/${encodeURIComponent(eucName)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files }),
  });
  if (
    !isRecord(payload) ||
    payload.euc_name !== eucName ||
    !isCertificationStatus(payload.certification_status)
  ) {
    throw new Error("The EUC service returned an unexpected edit response.");
  }
  return {
    euc_name: payload.euc_name,
    certification_status: payload.certification_status,
  };
}

export async function executeEuc(
  eucName: string,
  input: Record<string, unknown>,
): Promise<ExecutionRecord> {
  const payload = await request("/executions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ euc_name: eucName, input }),
  });
  if (!isExecutionRecord(payload)) {
    throw new Error("The execution service returned an unexpected response.");
  }
  return payload;
}

export async function getExecutions(): Promise<ExecutionRecord[]> {
  const payload = await request("/executions");
  if (!Array.isArray(payload) || !payload.every(isExecutionRecord)) {
    throw new Error("The execution service returned an unexpected history response.");
  }
  return payload;
}

export async function getExecution(
  executionId: string,
): Promise<ExecutionRecord> {
  const payload = await request(`/executions/${encodeURIComponent(executionId)}`);
  if (!isExecutionRecord(payload)) {
    throw new Error("The execution service returned unexpected details.");
  }
  return payload;
}

async function request(path: string, options?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new Error("Unable to reach the EUC Platform backend. Is it running?");
  }

  if (!response.ok) {
    let detail = "";
    try {
      const errorPayload: unknown = await response.json();
      if (isRecord(errorPayload) && typeof errorPayload.detail === "string") {
        detail = ` ${errorPayload.detail}`;
      }
    } catch {
      // Keep the HTTP error even when the server response is not JSON.
    }
    throw new Error(`Request failed with HTTP ${response.status}.${detail}`);
  }

  try {
    return await response.json();
  } catch {
    throw new Error("The EUC Platform backend returned an invalid response.");
  }
}

function isMigrationResult(value: unknown): value is MigrationResult {
  if (!isRecord(value)) return false;
  const result = value;
  if (
    result.status !== "ANALYZING" &&
    result.status !== "TRANSFORMING" &&
    result.status !== "VALIDATING" &&
    result.status !== "COMPLETED" &&
    result.status !== "FAILED"
  ) {
    return false;
  }
  if (!isRecord(result.generated_euc) || !isRecord(result.validation)) {
    return false;
  }
  const generated = result.generated_euc;
  const validation = result.validation;
  return (
    typeof generated.name === "string" &&
    Array.isArray(generated.files) &&
    generated.files.every(
      (file) =>
        isRecord(file) &&
        typeof file.path === "string" &&
        typeof file.content === "string",
    ) &&
    isStringArray(generated.warnings) &&
    isStringArray(generated.unsupported_features) &&
    typeof validation.valid === "boolean" &&
    isStringArray(validation.errors) &&
    isStringArray(validation.warnings)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isEucSummary(value: unknown): value is EucSummary {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.image === "string" &&
    typeof value.version === "string" &&
    (value.status === "REGISTERED" || value.status === "ARTIFACT_PRESENT") &&
    (value.owners === undefined || isStringArray(value.owners)) &&
    (value.certification_status === undefined ||
      isCertificationStatus(value.certification_status)) &&
    (typeof value.github_repo === "string" || value.github_repo === null) &&
    (typeof value.github_url === "string" || value.github_url === null) &&
    (typeof value.github_commit_sha === "string" ||
      value.github_commit_sha === null)
  );
}

function isCertificationStatus(value: unknown): value is CertificationStatus {
  return ["DRAFT", "PENDING_APPROVAL", "CERTIFIED", "REJECTED"].includes(
    String(value),
  );
}

function isCertificationResponse(
  value: unknown,
): value is CertificationResponse {
  return (
    isRecord(value) &&
    typeof value.euc_name === "string" &&
    isStringArray(value.owners) &&
    isCertificationStatus(value.certification_status) &&
    (typeof value.approved_by === "string" || value.approved_by === null) &&
    (typeof value.approved_at === "string" || value.approved_at === null) &&
    (typeof value.rejected_by === "string" || value.rejected_by === null) &&
    (typeof value.rejected_at === "string" || value.rejected_at === null) &&
    (typeof value.rejection_reason === "string" ||
      value.rejection_reason === null)
  );
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isGeneratedFile(value: unknown): value is GeneratedFile {
  return (
    isRecord(value) &&
    typeof value.path === "string" &&
    typeof value.content === "string"
  );
}

function isExecutionRecord(value: unknown): value is ExecutionRecord {
  return (
    isRecord(value) &&
    typeof value.execution_id === "string" &&
    typeof value.euc_name === "string" &&
    ["PENDING", "RUNNING", "COMPLETED", "FAILED", "TIMED_OUT"].includes(
      String(value.status),
    ) &&
    typeof value.started_at === "string" &&
    (typeof value.completed_at === "string" || value.completed_at === null) &&
    (typeof value.duration_ms === "number" || value.duration_ms === null) &&
    (typeof value.exit_code === "number" || value.exit_code === null) &&
    typeof value.stdout === "string" &&
    typeof value.stderr === "string"
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
