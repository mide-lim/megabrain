import assert from "node:assert/strict";
import test from "node:test";

import { GET } from "../src/app/healthz/route";

test("health endpoint returns the deterministic healthy status", async () => {
  const response = await GET();

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "healthy" });
});
