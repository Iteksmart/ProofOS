import { test, expect } from "@playwright/test";
import { resolve } from "node:path";

test("inventory, webhooks, reports and responsive layouts work together", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const workspace = await request.post("http://127.0.0.1:8018/v1/auth/bootstrap", { data: { name: `Operations QA ${Date.now()}` } });
  expect(workspace.ok()).toBeTruthy();
  const auth = await workspace.json();
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const orgId = auth.org.id;
  for (const title of ["Replace endpoint certificate", "Review workstation performance", "Verify backup completion"]) {
    const ticket = await request.post("http://127.0.0.1:8018/v1/tickets", { headers, data: { org_id: orgId, title, priority: "normal" } });
    expect(ticket.ok()).toBeTruthy();
  }
  const created = await request.post("http://127.0.0.1:8018/v1/devices", { headers, data: { org_id: orgId, hostname: "QA-WS-001", os: "Windows 11", ip: "10.0.0.20" } });
  const device = await created.json();
  const inventory = await request.post(`http://127.0.0.1:8018/v1/devices/${device.id}/inventory`, { headers: { "X-Agent-Token": device.device_secret }, data: {
    os: "Windows 11 Enterprise", hardware: { manufacturer: "Lenovo", model: "ThinkStation P3", processor: "Intel Core", logical_cores: 16, physical_cores: 8, memory_bytes: 34359738368 },
    disks: [{ device: "C:", mountpoint: "C:/", filesystem: "NTFS", total_bytes: 1024000000000, free_bytes: 450000000000 }],
    networks: [{ name: "Ethernet", address: "10.0.0.20", family: "IPv4" }],
    software: [{ name: "Microsoft Edge", version: "130.0", publisher: "Microsoft" }, { name: "7-Zip", version: "24.09", publisher: "Igor Pavlov" }], software_status: "complete",
  } });
  expect(inventory.ok()).toBeTruthy();
  await page.goto("/");
  await page.evaluate((auth) => { localStorage.setItem("proofos_token", auth.access_token); localStorage.setItem("proofos_org", String(auth.org.id)); localStorage.setItem("proofos_orgname", auth.org.name); localStorage.setItem("proofos_theme", "light"); }, auth);
  await page.reload();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const nav = (name) => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first();
  await page.screenshot({ path: resolve("../../proofos-overview-redesign.png"), fullPage: true });
  await page.getByRole("button", { name: "Search workspace", exact: true }).click();
  await page.getByLabel("Search pages and workspace records").fill("QA-WS");
  await expect(page.getByRole("dialog", { name: "Search workspace" }).getByText("QA-WS-001", { exact: true })).toBeVisible();
  await page.getByLabel("Search pages and workspace records").press("Enter");
  await expect(page.getByRole("tab", { name: "Activity", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No executions yet" })).toBeVisible();
  await nav("Inventory").click();
  await expect(page.getByRole("heading", { name: "Know every endpoint." })).toBeVisible();
  await expect(page.getByText("ThinkStation P3", { exact: false })).toBeVisible();
  await page.screenshot({ path: resolve("../../proofos-inventory-upgrade.png"), fullPage: true });
  await page.getByRole("button", { name: "Software intelligence", exact: true }).click();
  await expect(page.getByText("Microsoft Edge", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Endpoints", exact: true }).click();
  await page.getByRole("button", { name: "Inspect →" }).click();
  await page.getByRole("tab", { name: "Inventory", exact: true }).click();
  await expect(page.getByText("Microsoft Edge", { exact: true })).toBeVisible();
  await page.getByLabel("Search installed software").fill("7-Zip");
  await expect(page.getByText("Microsoft Edge", { exact: true })).not.toBeVisible();
  await nav("AI Copilot").click();
  await page.getByLabel("Investigation endpoint").selectOption(String(device.id));
  await page.getByRole("button", { name: "Prepare approval", exact: true }).click();
  await expect(page.getByText(/prepared. Review the exact command/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Review approvals →" })).toBeVisible();
  await page.screenshot({ path: resolve("../../proofos-ai-investigation.png"), fullPage: true });
  await nav("Integrations").click();
  await page.getByLabel("Connection name").fill("QA metrics source");
  await page.getByRole("button", { name: "Create connection", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Configure your source" })).toBeVisible();
  await page.getByRole("button", { name: "Send labeled test event" }).click();
  await expect(page.getByText("Delivery received", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss credential" }).click();
  await page.screenshot({ path: resolve("../../proofos-integrations-upgrade.png"), fullPage: true });
  await nav("Reports").click();
  await expect(page.getByRole("heading", { name: "See what needs attention." })).toBeVisible();
  await expect(page.getByText("Generated", { exact: false })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "↓ Devices", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("proofos-devices.csv");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve("../../proofos-reports-upgrade.png"), fullPage: true });
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.screenshot({ path: resolve("../../proofos-reports-dark.png"), fullPage: true });
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "See what needs attention." })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve("../../proofos-reports-mobile.png"), fullPage: true });
  expect(errors).toEqual([]);
});
