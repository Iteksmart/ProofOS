import { test, expect } from "@playwright/test";

const API = "http://127.0.0.1:8018";

test("customers, billing, thresholds, patch policies and the ticket assistant", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  const auth = await (await request.post(`${API}/v1/auth/bootstrap`, { data: { name: `Parity QA ${Date.now()}` } })).json();
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const orgId = auth.org.id;
  const device = await (await request.post(`${API}/v1/devices`, { headers, data: { org_id: orgId, hostname: "PARITY-WS-01", os: "Windows 11", device_type: "workstation" } })).json();
  await request.post(`${API}/v1/patches`, { headers, data: { org_id: orgId, device_id: device.id, name: "Security update (KB5099999)", severity: "critical", category: "security" } });

  await page.goto("/");
  await page.evaluate((a) => { localStorage.setItem("proofos_token", a.access_token); localStorage.setItem("proofos_org", String(a.org.id)); localStorage.setItem("proofos_orgname", a.org.name); }, auth);
  await page.reload();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const nav = (name) => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first().click();

  // Customers: create, contract, assign the endpoint.
  await nav("Customers");
  await expect(page.getByRole("heading", { name: "Every client, in one place." })).toBeVisible();
  await page.getByLabel("Company name").fill("Parity Industries");
  await page.getByRole("button", { name: "Add customer" }).click();
  const detail = page.getByRole("region", { name: "Customer Parity Industries" });
  await expect(detail).toBeVisible();
  await detail.getByLabel("Billing model").selectOption("hourly");
  await detail.getByLabel("Hourly rate").fill("100");
  await detail.getByRole("button", { name: "Save contract" }).click();
  await expect(detail.getByText("Hourly · $100.00/h")).toBeVisible();
  await detail.getByLabel("Assign an endpoint").selectOption({ label: "PARITY-WS-01" });
  await detail.getByRole("button", { name: "Assign" }).click();
  await expect(detail.getByRole("button", { name: "PARITY-WS-01" })).toBeVisible();

  // A ticket on the endpoint inherits the customer; 90 billable minutes are logged.
  const ticket = await (await request.post(`${API}/v1/tickets`, { headers, data: { org_id: orgId, title: "Parity laptop will not boot", device_id: device.id } })).json();
  expect(ticket.customer_id).toBeTruthy();
  await request.post(`${API}/v1/time`, { headers, data: { org_id: orgId, ticket_id: ticket.id, minutes: 90, billable: true } });

  // Billing: preview, issue, verified invoice.
  await nav("Billing");
  await expect(page.getByRole("heading", { name: "Bill from the work you can prove." })).toBeVisible();
  const card = page.locator(".billing-card", { hasText: "Parity Industries" });
  await expect(card.getByText("$150.00").first()).toBeVisible();
  await card.getByRole("button", { name: "Issue invoice" }).click();
  await expect(page.getByText("Invoice #", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Matches signed record")).toBeVisible();

  // Monitor: recommended thresholds.
  await nav("Monitor");
  const thresholds = page.getByRole("region", { name: "Alert thresholds" });
  await thresholds.getByRole("button", { name: "Apply recommended" }).click();
  await expect(thresholds.getByText("CPU ≥ 90%")).toBeVisible();
  await expect(thresholds.getByText("Disk ≥ 90%")).toBeVisible();

  // Patches: create a policy that is always open, preview it, run it.
  await nav("Patches");
  await page.getByRole("button", { name: "New policy" }).click();
  await page.getByLabel("Policy name").fill("Parity always-on");
  for (const day of ["Sat", "Sun"]) await page.getByRole("button", { name: day, exact: true }).click();
  await page.getByLabel("From").selectOption("0");
  await page.getByLabel("Until").selectOption("0");
  await page.getByRole("button", { name: "Save policy" }).click();
  const row = page.locator(".policy-row", { hasText: "Parity always-on" });
  await expect(row.getByText("Window open")).toBeVisible();
  await row.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText("1 patch on 1 endpoint would deploy now")).toBeVisible();
  await row.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByText("Queued 1 deployment covering 1 patches.")).toBeVisible();

  // Tickets: AI assistant (rule-based in the test stack) and "use as comment".
  await nav("Tickets");
  await page.getByText("Parity laptop will not boot").first().click();
  const assist = page.getByRole("region", { name: "AI ticket assistant" });
  await assist.getByRole("button", { name: "Summarise and suggest" }).click();
  await expect(assist.getByText("PARITY-WS-01", { exact: false }).first()).toBeVisible();
  await assist.getByRole("button", { name: "Use as comment" }).click();
  await expect(page.getByPlaceholder("Add a comment…")).toHaveValue(/Parity laptop will not boot/);

  expect(errors).toEqual([]);
});
