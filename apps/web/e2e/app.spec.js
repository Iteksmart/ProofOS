import { test, expect } from "@playwright/test";

async function bootstrap(page, org = "E2E Org") {
  await page.goto("/");
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  // The signup form lives in a collapsed <details> panel on the sign-in page.
  await page.locator("summary", { hasText: "New to ProofOS?" }).click();
  await page.getByLabel("Workspace name").fill(`${org} ${unique}`);
  await page.getByLabel("Administrator email").fill(`admin-${unique}@e2e-test.dev`);
  await page.getByLabel("Administrator password").fill("At least 12 characters!");
  await page.getByRole("button", { name: "Create workspace and sign in" }).click();
  // Dashboard loads after the explicit first-run workspace setup.
  await expect(page.getByText("Device health")).toBeVisible({ timeout: 25000 });
}

test("bootstrap and render the one-pane dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "ProofOS" }).first()).toBeVisible();
  await bootstrap(page);
  await expect(page.getByText("Device health")).toBeVisible();
  await expect(page.getByText("Quick actions")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run audit" }).first()).toBeVisible();
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
