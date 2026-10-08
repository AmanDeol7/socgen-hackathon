export interface SecretReference {
  name: string;
  vault: string;
  key: string;
}

export interface EucMetadata {
  name: string;
  description: string | null;
  python_version: string;
  owner_team: string;
  support_team: string;
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

const API_URL = "http://localhost:8000/api/migrations";

export async function migrateEuc(input: MigrationInput): Promise<MigrationResult> {
  let response: Response;
  try {
    response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch {
    throw new Error("Unable to reach the migration service. Is the backend running?");
  }

  if (!response.ok) {
    throw new Error(`Migration request failed with HTTP ${response.status}.`);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The migration service returned an invalid response.");
  }

  if (!isMigrationResult(payload)) {
    throw new Error("The migration service returned an unexpected response.");
  }
  return payload;
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

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
