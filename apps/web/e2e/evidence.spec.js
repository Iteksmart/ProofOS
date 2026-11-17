import { test, expect } from "@playwright/test";

const API = "http://127.0.0.1:8018";
const TRACE = "0af7651916cd43dd8448eb211c80319c";

const resource = (name) => ({ attributes: [{ key: "service.name", value: { stringValue: name } }] });
const span = (id, parent, name, failed = false) => ({
  traceId: TRACE, spanId: id, parentSpanId: parent, name,
  startTimeUnixNano: "1794000000000000000", endTimeUnixNano: "1794000000300000000",
  status: failed ? { code: 2, message: "upstream timeout" } : { code: 1 },
});

test("topology, telemetry and privileged access work end to end", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  const workspace = await request.post(`${API}/v1/auth/bootstrap`, { data: { name: `Evidence QA ${Date.now()}` } });
  expect(workspace.ok()).toBeTruthy();
  const auth = await workspace.json();
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const orgId = auth.org.id;
  const device = await (await request.post(`${API}/v1/devices`, { headers, data: { org_id: orgId, hostname: "EVIDENCE-DB-01", os: "Linux" } })).json();

  // Telemetry arrives through an OpenTelemetry connection; traces build the service map.
  const connection = await (await request.post(`${API}/v1/integrations/connections?org_id=${orgId}`, { headers, data: { name: "QA collector", provider: "otlp" } })).json();
  const ingest = { "X-Integration-Token": connection.token };
  const traces = await request.post(`${API}${connection.webhook_path}/v1/traces`, { headers: ingest, data: { resourceSpans: [
    { resource: resource("storefront"), scopeSpans: [{ spans: [span("aaaaaaaaaaaaaaa1", "", "GET /cart")] }] },
    { resource: resource("orders"), scopeSpans: [{ spans: [span("aaaaaaaaaaaaaaa2", "aaaaaaaaaaaaaaa1", "create order", true)] }] },
  ] } });
  expect(traces.status()).toBe(202);
  const logs = await request.post(`${API}${connection.webhook_path}/v1/logs`, { headers: ingest, data: { resourceLogs: [
    { resource: resource("orders"), scopeLogs: [{ logRecords: [{ severityText: "ERROR", traceId: TRACE, spanId: "aaaaaaaaaaaaaaa2", body: { stringValue: "order failed password=supersecretvalue" } }] }] },
  ] } });
  expect(logs.status()).toBe(202);

  await page.goto("/");
  await page.evaluate((a) => { localStorage.setItem("proofos_token", a.access_token); localStorage.setItem("proofos_org", String(a.org.id)); localStorage.setItem("proofos_orgname", a.org.name); }, auth);
  await page.reload();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const nav = (name) => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first();

  // Topology: observed dependency, health from evidence, declared service, impact.
  await nav("Topology").click();
  await expect(page.getByRole("heading", { name: "See what depends on what." })).toBeVisible();
  await expect(page.getByRole("button", { name: "orders, down" })).toBeVisible();
  await page.getByLabel("Service name").fill("orders-db");
  await page.getByLabel("Runs on endpoint").selectOption({ label: "EVIDENCE-DB-01" });
  await page.getByRole("button", { name: "Add service" }).click();
  await expect(page.getByRole("button", { name: /^orders-db,/ })).toBeVisible();
  const dependencyForm = page.locator("form", { hasText: "Declare a dependency" });
  await dependencyForm.locator("select").first().selectOption({ label: "orders" });
  await dependencyForm.locator("select").last().selectOption({ label: "orders-db" });
  await page.getByRole("button", { name: "Add dependency" }).click();
  await page.getByRole("button", { name: /^orders-db,/ }).click();
  const detail = page.locator(".topo-detail");
  await expect(detail.getByRole("button", { name: "orders", exact: true })).toBeVisible();
  await expect(detail.getByRole("button", { name: "storefront", exact: true })).toBeVisible();
  await expect(detail.getByRole("button", { name: /Open endpoint EVIDENCE-DB-01/ })).toBeVisible();

  // Telemetry: redacted log, error filter, trace waterfall.
  await nav("Telemetry").click();
  await expect(page.getByRole("heading", { name: "Follow a request end to end." })).toBeVisible();
  await page.getByRole("group", { name: "Telemetry filter" }).getByRole("button", { name: "Errors" }).click();
  await expect(page.getByText("[redacted:generic_secret]")).toBeVisible();
  await expect(page.getByText("supersecretvalue")).toHaveCount(0);
  await page.getByRole("button", { name: "View trace" }).first().click();
  const trace = page.getByRole("region", { name: "Trace detail" });
  await expect(trace.getByText("2 spans · 2 services")).toBeVisible();
  await trace.getByRole("button", { name: "Close trace" }).click();

  // Privileged access: a request is recorded as pending and cannot be self-approved.
  await nav("Access").click();
  await expect(page.getByRole("heading", { name: "Access that expires on its own." })).toBeVisible();
  await page.locator("form.access-form select").nth(1).selectOption({ label: "EVIDENCE-DB-01" });
  await page.getByLabel("Exact command").fill("systemctl status postgresql");
  await page.getByLabel("Reason").fill("Investigating failed orders INC-2231");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("status")).toContainText("grants nothing until");
  await expect(page.getByText("systemctl status postgresql")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeDisabled();
  await page.getByRole("button", { name: "Deny" }).click();
  await expect(page.getByText("denied", { exact: true })).toBeVisible();

  expect(errors).toEqual([]);
  expect(device.id).toBeGreaterThan(0);
});
