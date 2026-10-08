import { afterEach, describe, expect, it, vi } from "vitest";
import {
  approveEuc,
  getEuc,
  getEucs,
  rejectEuc,
  submitEucForCertification,
  updateEuc,
} from "./api";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("certification and EUC API contracts", () => {
  it("loads certification state and owner metadata for EUC lists", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response([
          {
            name: "demo",
            image: "demo",
            version: "latest",
            status: "REGISTERED",
            owners: ["owner@example.com"],
            certification_status: "PENDING_APPROVAL",
            approved_by: null,
            approved_at: null,
            rejected_by: null,
            rejected_at: null,
            rejection_reason: null,
            github_repo: null,
            github_url: null,
            github_commit_sha: null,
          },
        ]),
      ),
    );

    await expect(getEucs()).resolves.toMatchObject([
      {
        name: "demo",
        owners: ["owner@example.com"],
        certification_status: "PENDING_APPROVAL",
      },
    ]);
  });

  it("submits using the backend certification submit endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        euc_name: "demo",
        owners: ["owner@example.com"],
        certification_status: "PENDING_APPROVAL",
        approved_by: null,
        approved_at: null,
        rejected_by: null,
        rejected_at: null,
        rejection_reason: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await submitEucForCertification("demo");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/eucs/demo/certification/submit",
      { method: "POST" },
    );
  });

  it("sends the approving owner's email to the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        euc_name: "demo",
        owners: ["owner@example.com"],
        certification_status: "CERTIFIED",
        approved_by: "owner@example.com",
        approved_at: "2026-10-09T00:00:00+00:00",
        rejected_by: null,
        rejected_at: null,
        rejection_reason: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await approveEuc("demo", "owner@example.com");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/eucs/demo/certification/approve",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner_email: "owner@example.com" }),
      },
    );
  });

  it("sends rejection reason and exposes backend authorization errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({ detail: "Only an owner listed for this EUC may approve or reject it." }, 403),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      rejectEuc("demo", "intruder@example.com", "Reason"),
    ).rejects.toThrow("HTTP 403. Only an owner listed");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/eucs/demo/certification/reject",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner_email: "intruder@example.com",
          reason: "Reason",
        }),
      },
    );
  });

  it("loads full EUC details including generated files", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          name: "demo",
          image: "demo",
          version: "latest",
          status: "REGISTERED",
          owners: ["owner@example.com"],
          certification_status: "CERTIFIED",
          approved_by: "owner@example.com",
          approved_at: "2026-10-09T00:00:00+00:00",
          rejected_by: null,
          rejected_at: null,
          rejection_reason: null,
          github_repo: "org/demo",
          github_url: "https://github.com/org/demo",
          github_commit_sha: "abc123",
          files: [{ path: "src/main.py", content: "def run(): pass\n" }],
        }),
      ),
    );

    await expect(getEuc("demo")).resolves.toMatchObject({
      certification_status: "CERTIFIED",
      approved_by: "owner@example.com",
      github_url: "https://github.com/org/demo",
      files: [{ path: "src/main.py" }],
    });
  });

  it("updates editable business files through the EUC PUT endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        euc_name: "demo",
        certification_status: "PENDING_APPROVAL",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      updateEuc("demo", [
        { path: "src/main.py", content: "def run(data, context): return data\n" },
      ]),
    ).resolves.toEqual({
      euc_name: "demo",
      certification_status: "PENDING_APPROVAL",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/eucs/demo",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          files: [
            {
              path: "src/main.py",
              content: "def run(data, context): return data\n",
            },
          ],
        }),
      },
    );
  });
});
