import { describe, expect, it } from "vitest";
import {
  addDependency,
  addSecretReference,
  buildMigrationInput,
  removeDependency,
  removeSecretReference,
} from "./migrationForm";
import { EucMetadata } from "./api";

const metadata: EucMetadata = {
  name: "demo",
  description: null,
  python_version: "3.12",
  owners: ["owner@example.com"],
  support_team: "Platform",
  schedule: null,
  sharepoint_url: null,
  secret_references: [],
  dependencies: [],
};

describe("migration form collections", () => {
  it("adds and removes secret references", () => {
    const withReference = addSecretReference(metadata.secret_references);
    expect(withReference).toEqual([{ name: "", vault: "", key: "" }]);
    expect(removeSecretReference(withReference, 0)).toEqual([]);
  });

  it("adds and removes dependencies", () => {
    const withDependencies = addDependency(metadata.dependencies);
    expect(withDependencies).toEqual([""]);
    expect(removeDependency(["requests", "pandas"], 0)).toEqual(["pandas"]);
  });

  it("builds the exact backend payload with empty arrays", () => {
    const input = buildMigrationInput(
      {
        ...metadata,
        secret_references: [{ name: "client_id", vault: "secrets", key: "id" }],
        dependencies: ["requests", "pandas"],
      },
      "def run(json_input):\n    return json_input\n",
    );

    expect(input.metadata.secret_references).toEqual([
      { name: "client_id", vault: "secrets", key: "id" },
    ]);
    expect(input.metadata.dependencies).toEqual(["requests", "pandas"]);
    expect(
      buildMigrationInput({ ...metadata, secret_references: [], dependencies: [] }, "")
        .metadata,
    ).toMatchObject({ secret_references: [], dependencies: [] });
  });
});
