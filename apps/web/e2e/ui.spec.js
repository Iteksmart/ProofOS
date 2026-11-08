import { test, expect } from "@playwright/test";

async function bootstrap(page, org = "E2E UI Org") {
  await page.goto("/");
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  // The signup form lives in a collapsed <details> panel on the sign-in page.
  await page.locator("summary", { hasText: "New to ProofOS?" }).click();
  await page.getByLabel("Workspace name").fill(`${org} ${unique}`);
  await page.getByLabel("Administrator email").fill(`admin-${unique}@e2e-test.dev`);
  await page.getByLabel("Administrator password").fill("At least 12 characters!");
  await page.getByRole("button", { name: "Create workspace and sign in" }).click();
  await expect(page.getByText("Device health")).toBeVisible({ timeout: 25000 });
}

async function registerDevice(page, hostname) {
  await page.getByRole("button", { name: "Devices", exact: true }).click();
  await page.getByPlaceholder("hostname", { exact: true }).fill(hostname);
  await page.getByPlaceholder("os", { exact: true }).fill("Linux");
  await page.getByPlaceholder("ip", { exact: true }).fill("10.2.2.2");
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page.getByText(hostname).first()).toBeVisible({ timeout: 15000 });
}

function trackErrors(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) {
      errors.push(`console.error: ${m.text()}`);
    }
  });
  return errors;
}

test("bad credentials do not create or enter a workspace", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("wrong@e2e-test.dev");
  await page.getByLabel("Password", { exact: true }).fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Email or password is incorrect");
  await expect(page.getByRole("button", { name: "Logout" })).toHaveCount(0);
});

const nav = (name) => page => page.getByRole("button", { name, exact: true }).click();

test("dashboard renders cleanly with no errors", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/");
  await bootstrap(page);
  await expect(page.getByText("Quick actions")).toBeVisible();
  await expect(page.getByText("Open alerts")).toBeVisible();
  await expect(page.getByText("Proof records")).toBeVisible();
  // Exec/Operations toggle exists and switches
  await page.getByRole("button", { name: "Operations" }).click();
  await page.getByRole("button", { name: "Exec" }).click();
  expect(errors).toEqual([]);
});

test("devices: register, search, open, run command", async ({ page }) => {
  const errors = trackErrors(page);
  await bootstrap(page);
  await nav("Devices")(page);
  await page.getByPlaceholder("hostname", { exact: true }).fill("ui-ws-01");
  await page.getByPlaceholder("os", { exact: true }).fill("Linux");
  await page.getByPlaceholder("ip", { exact: true }).fill("10.1.1.1");
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page.getByText("ui-ws-01").first()).toBeVisible({ timeout: 15000 });
  // close the enrollment panel so the table is the only "ui-ws-01"
  await page.getByRole("button", { name: "✕ close" }).click();
  // search
  await page.getByPlaceholder("Search hostname…").fill("ui-ws");
  await expect(page.getByText("ui-ws-01").first()).toBeVisible();
  await page.getByPlaceholder("Search hostname…").fill("");
  // open detail + run command
  await page.getByText("ui-ws-01").first().click();
  await expect(page.getByText("Device · ui-ws-01")).toBeVisible({ timeout: 10000 });
  await page.getByPlaceholder("e.g. df -h / ipconfig / show version").fill("echo hi");
  await page.getByRole("button", { name: "Run" }).click();
  expect(errors).toEqual([]);
});

test("tickets: create, comment, start", async ({ page }) => {
  const errors = trackErrors(page);
  await bootstrap(page);
  await nav("Tickets")(page);
  await page.getByPlaceholder("Title e.g. printer offline").fill("UI: printer down");
  await page.getByPlaceholder("Details").fill("needs attention");
  await page.getByRole("button", { name: "Create ticket" }).click();
  await expect(page.getByText("UI: printer down")).toBeVisible({ timeout: 15000 });
  await page.getByText("UI: printer down").first().click();
  await page.getByPlaceholder("Add a comment…").fill("looking into it");
  await page.getByRole("button", { name: "Post" }).click();
  await expect(page.getByText("looking into it")).toBeVisible({ timeout: 10000 });
  expect(errors).toEqual([]);
});

test("monitor + scripts + automations", async ({ page }) => {
  const errors = trackErrors(page);
  await bootstrap(page);
  await registerDevice(page, "monitor-ws-01");
  await nav("Monitor")(page);
  await page.getByLabel("Device").selectOption({ index: 1 });
  await page.getByPlaceholder("10.0.0.1:443").fill("10.1.1.1:80");
  await page.getByRole("button", { name: "Add check" }).click();
  await expect(page.getByText("10.1.1.1:80")).toBeVisible({ timeout: 10000 });

  await nav("Scripts")(page);
  await page.getByPlaceholder("name e.g. disk-check").fill("ui-script");
  await page.getByPlaceholder("body e.g. echo ok").fill("echo ok");
  await page.getByRole("button", { name: "Create script" }).click();
  await expect(page.getByText("ui-script")).toBeVisible({ timeout: 10000 });

  await nav("Automations")(page);
  await page.getByPlaceholder("name").fill("ui-auto");
  await page.getByRole("button", { name: "Create rule" }).click();
  await expect(page.getByText("ui-auto")).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: "Simulate" }).click();
  expect(errors).toEqual([]);
});

test("AI copilot + admin (user, push)", async ({ page }) => {
  const errors = trackErrors(page);
  await bootstrap(page);
  await nav("AI Copilot")(page);
  await page.getByPlaceholder("e.g. offline devices").fill("offline devices");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText(/engine:/)).toBeVisible({ timeout: 15000 });

  await nav("Admin")(page);
  const newUserEmail = `engineer-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@e2e-test.dev`;
  await page.getByPlaceholder("email").fill(newUserEmail);
  await page.getByPlaceholder("password (min 8)").fill("password123");
  await page.getByRole("button", { name: "Add user" }).click();
  await expect(page.getByText(newUserEmail)).toBeVisible({ timeout: 10000 });
  expect(errors).toEqual([]);
});

test("CMDB + knowledge + vault + changes + time", async ({ page }) => {
  const errors = trackErrors(page);
  await bootstrap(page);
  await nav("CMDB")(page);
  await page.getByPlaceholder("name").fill("core-switch");
  await page.getByRole("button", { name: "Add CI" }).click();
  await expect(page.getByText("core-switch")).toBeVisible({ timeout: 10000 });

  await nav("Knowledge")(page);
  await page.getByPlaceholder("title", { exact: true }).fill("How to reset VPN");
  await page.getByRole("button", { name: "Add article" }).click();
  await expect(page.getByText("How to reset VPN")).toBeVisible({ timeout: 10000 });

  await nav("Vault")(page);
  await page.getByPlaceholder("name").fill("db-pass");
  await page.getByPlaceholder("value").fill("s3cret");
  await page.getByPlaceholder("category").fill("database");
  await page.getByRole("button", { name: "Store secret" }).click();
  await expect(page.getByText("db-pass")).toBeVisible({ timeout: 10000 });

  await nav("Changes")(page);
  await page.getByPlaceholder("title").fill("upgrade db");
  await page.getByRole("button", { name: "Create change" }).click();
  await expect(page.getByText("upgrade db")).toBeVisible({ timeout: 10000 });

  await nav("Time")(page);
  await page.getByLabel("Minutes").fill("90");
  await page.getByLabel("Notes").fill("onboarding time entry");
  await page.getByRole("button", { name: "Log time" }).click();
  // Scope to <main> to avoid matching the "Onboarding" nav links (desktop + mobile).
  await expect(page.locator("main").getByText("onboarding time entry")).toBeVisible({ timeout: 10000 });
  expect(errors).toEqual([]);
});

test("VMs + patches + onboarding + consulting + audit", async ({ page }) => {
  const errors = trackErrors(page);
  await bootstrap(page);
  await registerDevice(page, "vm-host-01");
  await nav("VMs")(page);
  await page.getByPlaceholder("VM name").fill("dc-01");
  await page.locator("select").first().selectOption({ index: 1 });
  await page.getByRole("button", { name: "Register VM" }).click();
  await expect(page.getByText("dc-01").first()).toBeVisible({ timeout: 10000 });

  await nav("Patches")(page);
  await page.getByPlaceholder("name e.g. openssl").fill("openssl");
  await page.locator("select").first().selectOption({ index: 1 });
  await page.getByRole("button", { name: "Register patch" }).click();
  await expect(page.getByText("openssl").first()).toBeVisible({ timeout: 10000 });

  await nav("Onboarding")(page);
  await page.getByRole("button", { name: "Init checklist" }).click();
  await expect(page.getByRole("heading", { name: "Client onboarding" })).toBeVisible({ timeout: 10000 });

  await nav("Consulting")(page);
  await page.getByLabel("Name", { exact: true }).fill("net-migration");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByText("net-migration").first()).toBeVisible({ timeout: 10000 });

  await nav("Audit")(page);
  await page.getByRole("button", { name: "Run audit" }).first().click();
  await expect(page.getByText(/score|findings/i)).toBeVisible({ timeout: 15000 });
  expect(errors).toEqual([]);
});
