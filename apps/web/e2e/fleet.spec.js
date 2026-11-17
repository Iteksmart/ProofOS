import { test, expect } from "@playwright/test";

const API = "http://127.0.0.1:8018";

test("describe endpoints in plain English, then act on them in bulk", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const auth = await (await request.post(`${API}/v1/auth/bootstrap`, { data: { name: `Fleet QA ${Date.now()}` } })).json();
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const orgId = auth.org.id;
  for (const [hostname, os] of [["FLEET-SRV-01", "Windows Server 2022"], ["FLEET-SRV-02", "Windows Server 2022"], ["FLEET-WS-01", "Ubuntu 24.04"]]) {
    const r = await request.post(`${API}/v1/devices`, { headers, data: { org_id: orgId, hostname, os, device_type: hostname.includes("SRV") ? "server" : "workstation" } });
    expect(r.ok()).toBeTruthy();
  }

  await page.goto("/");
  await page.evaluate((a) => { localStorage.setItem("proofos_token", a.access_token); localStorage.setItem("proofos_org", String(a.org.id)); localStorage.setItem("proofos_orgname", a.org.name); }, auth);
  await page.reload();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Devices", exact: true }).filter({ visible: true }).first().click();

  await page.getByLabel("Describe the endpoints you want").fill("windows servers and gizmos");
  await page.getByRole("button", { name: "Find" }).click();
  const understood = page.locator(".fleet-understood");
  await expect(understood).toContainText("Showing 2 endpoints where");
  await expect(understood).toContainText("OS: windows");
  await expect(understood).toContainText("Not understood: gizmos");
  await expect(page.getByRole("row", { name: /FLEET-WS-01/ })).toHaveCount(0);

  await page.getByLabel("Select all shown endpoints").check();
  const bar = page.getByRole("region", { name: "Bulk actions" });
  await expect(bar).toContainText("2 selected");
  await bar.getByLabel("Ticket title for selected endpoints").fill("Apply baseline hardening");
  await bar.getByRole("button", { name: "Create tickets" }).click();
  await expect(page.getByText("Tickets created: 2 of 2 endpoints.")).toBeVisible();

  const tickets = await (await request.get(`${API}/v1/tickets?org_id=${orgId}`, { headers })).json();
  expect(tickets.map((t) => t.title).sort()).toEqual(["FLEET-SRV-01: Apply baseline hardening", "FLEET-SRV-02: Apply baseline hardening"]);

  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("row", { name: /FLEET-WS-01/ })).toBeVisible();
  expect(errors).toEqual([]);
});
