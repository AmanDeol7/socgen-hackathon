import { describe, expect, it } from "vitest";
import { parseExecutionInput } from "./executionInput";

describe("execution JSON input", () => {
  it("accepts JSON objects", () => {
    expect(parseExecutionInput('{"name":"Aman"}')).toEqual({ name: "Aman" });
  });

  it("rejects invalid JSON with an actionable message", () => {
    expect(() => parseExecutionInput("{bad json")).toThrow(
      "Enter valid JSON before submitting.",
    );
  });

  it.each(["null", "[]", '"string"', "42"])(
    "rejects valid JSON values that are not objects (%s)",
    (source) => {
      expect(() => parseExecutionInput(source)).toThrow(
        "Execution input must be a JSON object.",
      );
    },
  );
});
