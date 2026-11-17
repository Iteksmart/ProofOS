import { test, expect } from "@playwright/test";

const API = "http://127.0.0.1:8018";

test("customer portal, customer-visible replies, SLOs, vulnerabilities and anchors", async ({ page, request, browser }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  const auth = await (await request.post(`${API}/v1/auth/bootstrap`, { data: { name: `Assurance QA ${Date.now()}` } })).json();
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const orgId = auth.org.id;
  const customer = await (await request.post(`${API}/v1/customers`, { headers, data: { name: "Portal Holdings" } })).json();
  const ticket = await (await request.post(`${API}/v1/tickets`, { headers, data: { org_id: orgId, title: "Email not syncing", customer_id: customer.id } })).json();
  await request.post(`${API}/v1/tickets/${ticket.id}/comments`, { headers, data: { body: "Internal: check the mailbox quota" } });

  await page.goto("/");
  await page.evaluate((a) => { localStorage.setItem("proofos_token", a.access_token); localStorage.setItem("proofos_org", String(a.org.id)); localStorage.setItem("proofos_orgname", a.org.name); }, auth);
  await page.reload();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const nav = (name) => page.getByRole("button", { name, exact: true }).filter({ visible: true }).first().click();

  // Staff create a portal link from the customer record.
  await nav("Customers");
  await page.getByRole("row").filter({ hasText: "Portal Holdings" }).getByRole("button", { name: "Open →" }).click();
  const detail = page.getByRole("region", { name: "Customer Portal Holdings" });
  await detail.getByLabel("Contact email").fill("it-lead@portal-holdings.com");
  await detail.getByRole("button", { name: "Create link" }).click();
  const link = await detail.getByLabel("Portal link").inputValue();
  expect(link).toContain("/portal#");
  await expect(detail.getByText("it-lead@portal-holdings.com").first()).toBeVisible();

  // The customer sees their ticket without the internal note, replies and opens a new ticket.
  const customerPage = await browser.newPage();
  customerPage.on("pageerror", (error) => errors.push(`portal: ${error.message}`));
  await customerPage.goto(link.replace(/^https?:\/\/[^/]+/, "http://127.0.0.1:5184"));
  await expect(customerPage.getByRole("heading", { name: "Portal Holdings" })).toBeVisible();
  expect(customerPage.url()).not.toContain("#");
  await customerPage.getByRole("button", { name: /Email not syncing/ }).click();
  const thread = customerPage.getByRole("region", { name: "Ticket conversation" });
  await expect(thread.getByText("Internal: check the mailbox quota")).toHaveCount(0);
  await thread.getByLabel("Reply").fill("It started after the password change.");
  await thread.getByRole("button", { name: "Send reply" }).click();
  await expect(thread.getByText("It started after the password change.")).toBeVisible();
  await customerPage.getByLabel("Subject").fill("New starter needs a laptop");
  await customerPage.getByRole("button", { name: "Submit ticket" }).click();
  await expect(customerPage.getByRole("heading", { name: /New starter needs a laptop/ })).toBeVisible();
  await customerPage.close();

  // A technician's customer-visible reply is labelled as such.
  await nav("Tickets");
  await page.getByRole("button", { name: "Email not syncing" }).click();
  await expect(page.getByText("It started after the password change.")).toBeVisible();
  await page.getByPlaceholder("Add a comment…").fill("Resetting your mail profile now.");
  await page.getByLabel(/Reply to customer/).check();
  await page.getByRole("button", { name: "Post" }).click();
  await expect(page.getByText("visible to customer").last()).toBeVisible();

  // SLOs and the other new surfaces render.
  await nav("Telemetry");
  const slos = page.getByRole("region", { name: "Service level objectives" });
  await slos.getByLabel("Service").fill("checkout-api");
  await slos.getByRole("button", { name: "Save objective" }).click();
  await expect(slos.getByRole("row").filter({ hasText: "checkout-api" })).toContainText("insufficient data");
  await nav("Vulnerabilities");
  await expect(page.getByRole("heading", { name: "Know which endpoints are exploitable." })).toBeVisible();
  await expect(page.getByText("No open findings")).toBeVisible();
  await nav("Proof");
  await expect(page.getByRole("region", { name: "Independent timestamps" })).toBeVisible();
  expect(errors).toEqual([]);
});
