import { EucMetadata, MigrationInput, SecretReference } from "./api";

export const emptySecretReference = (): SecretReference => ({
  name: "",
  vault: "",
  key: "",
});

export function addSecretReference(
  references: SecretReference[],
): SecretReference[] {
  return [...references, emptySecretReference()];
}

export function removeSecretReference(
  references: SecretReference[],
  index: number,
): SecretReference[] {
  return references.filter((_, referenceIndex) => referenceIndex !== index);
}

export function addDependency(dependencies: string[]): string[] {
  return [...dependencies, ""];
}

export function removeDependency(
  dependencies: string[],
  index: number,
): string[] {
  return dependencies.filter((_, dependencyIndex) => dependencyIndex !== index);
}

export function buildMigrationInput(
  metadata: EucMetadata,
  sourceCode: string,
): MigrationInput {
  return {
    metadata: {
      ...metadata,
      secret_references: metadata.secret_references ?? [],
      dependencies: metadata.dependencies ?? [],
    },
    source_code: sourceCode,
    source_filename: "main.py",
  };
}
