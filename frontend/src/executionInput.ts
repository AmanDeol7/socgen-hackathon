export function parseExecutionInput(source: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(source) as unknown;
  } catch {
    throw new Error("Enter valid JSON before submitting.");
  }
  if (!isJsonObject(parsed)) {
    throw new Error("Execution input must be a JSON object.");
  }
  return parsed;
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
