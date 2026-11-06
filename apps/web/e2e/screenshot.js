import { chromium } from "@playwright/test";

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://localhost:5173/");
  await page.getByLabel("Org name").fill("Screenshot Org");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByText("Device health").waitFor({ timeout: 20000 });

  await page.screenshot({ path: "e2e/screens/dashboard-dark.png", fullPage: true });

  await page.getByRole("button", { name: /Light/ }).click();
  await page.screenshot({ path: "e2e/screens/dashboard-light.png", fullPage: true });

  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await page.screenshot({ path: "e2e/screens/analytics.png", fullPage: true });

  await page.getByRole("button", { name: "Devices", exact: true }).click();
  await page.screenshot({ path: "e2e/screens/devices.png", fullPage: true });

  await browser.close();
})();
