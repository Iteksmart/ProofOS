import { test, expect } from "@playwright/test";

async function bootstrap(page, org = "E2E Org") {
  await page.goto("/");
  await page.getByLabel("Org name").fill(org);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Dashboard loads after bootstrap (default view "Overview").
  await expect(page.getByText("Device health")).toBeVisible({ timeout: 25000 });
}

test("bootstrap and render the one-pane dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "ProofOS" }).first()).toBeVisible();
  await bootstrap(page);
  await expect(page.getByText("Device health")).toBeVisible();
  await expect(page.getByText("Quick actions")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run audit" })).toBeVisible();
});

test("create a device and a ticket", async ({ page }) => {
  await bootstrap(page);

  await page.getByRole("button", { name: "Devices", exact: true }).click();
  await page.getByPlaceholder("hostname", { exact: true }).fill("e2e-ws-01");
  await page.getByPlaceholder("os", { exact: true }).fill("Linux");
  await page.getByPlaceholder("ip", { exact: true }).fill("10.0.0.11");
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page.getByText("e2e-ws-01")).toBeVisible({ timeout: 15000 });

  await page.getByRole("button", { name: "Tickets", exact: true }).click();
  await page.getByPlaceholder("Title e.g. printer offline").fill("E2E: server down");
  await page.getByRole("button", { name: "Create ticket" }).click();
  await expect(page.getByText("E2E: server down")).toBeVisible({ timeout: 15000 });
});

test("navigate every primary view", async ({ page }) => {
  await bootstrap(page);
  const views = [
    "Analytics", "Devices", "Tickets", "Monitor", "Scripts", "Automations",
    "Proof", "AI Copilot", "Admin", "CMDB", "Knowledge", "Vault", "Changes",
    "Time", "VMs", "Patches", "iTechSmart", "Audit", "Onboarding", "Consulting",
  ];
  for (const v of views) {
    await page.getByRole("button", { name: v, exact: true }).click();
    await expect(page.locator("main")).toBeVisible();
    await page.waitForTimeout(250);
  }
});
