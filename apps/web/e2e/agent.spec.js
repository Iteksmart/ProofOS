import { test, expect } from "@playwright/test";

const API = "http://127.0.0.1:8018";

test("command console streams agent output live and can cancel a running command", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const auth = await (await request.post(`${API}/v1/auth/bootstrap`, { data: { name: `Agent QA ${Date.now()}` } })).json();
  const headers = { Authorization: `Bearer ${auth.access_token}` };
  const device = await (await request.post(`${API}/v1/devices`, { headers, data: { org_id: auth.org.id, hostname: "AGENT-LIVE-01", os: "Ubuntu 24.04" } })).json();
  const agent = { "X-Agent-Token": device.device_secret };

  await page.goto("/");
  await page.evaluate((a) => { localStorage.setItem("proofos_token", a.access_token); localStorage.setItem("proofos_org", String(a.org.id)); localStorage.setItem("proofos_orgname", a.org.name); }, auth);
  await page.reload();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "Devices", exact: true }).filter({ visible: true }).first().click();
  await page.getByText("AGENT-LIVE-01").first().click();
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  const consoleBox = page.getByRole("region", { name: "Command console" });

  // Run a command; play the agent's side of the protocol.
  await consoleBox.getByLabel("Interpreter").selectOption("bash");
  await consoleBox.getByLabel("Command").fill("df -h /");
  await consoleBox.getByLabel("Command").press("Enter");
  await expect(consoleBox.getByText("waiting for agent")).toBeVisible();
  const jobs = await (await request.get(`${API}/v1/agent/jobs?device_id=${device.id}`, { headers: agent })).json();
  expect(jobs.jobs).toHaveLength(1);
  const env = jobs.jobs[0].envelope;
  expect(env.body).toBe("#proofos:shell=bash\ndf -h /");
  expect(jobs.jobs[0].signature.length).toBeGreaterThan(40);
  await request.post(`${API}/v1/agent/runs/${env.run_id}/start`, { headers: agent });
  await request.post(`${API}/v1/agent/runs/${env.run_id}/output`, { headers: agent, data: { chunk: "Filesystem  Size  Used\n" } });
  await expect(consoleBox.getByText("Filesystem  Size  Used")).toBeVisible();
  await expect(consoleBox.getByText("running")).toBeVisible();
  await request.post(`${API}/v1/scripts/runs/${env.run_id}/complete`, { headers: agent, data: { output: "Filesystem  Size  Used\n/dev/sda1  50G  20G\n", exit_code: 0 } });
  await expect(consoleBox.getByText("exit 0")).toBeVisible();
  await expect(consoleBox.getByText("/dev/sda1  50G  20G")).toBeVisible();

  // A long command can be cancelled from the console while it runs.
  await consoleBox.getByLabel("Command").fill("sleep 600");
  await consoleBox.getByRole("button", { name: "Run" }).click();
  await expect(consoleBox.getByText("waiting for agent")).toBeVisible();
  const second = (await (await request.get(`${API}/v1/agent/jobs?device_id=${device.id}`, { headers: agent })).json()).jobs[0].envelope;
  await request.post(`${API}/v1/agent/runs/${second.run_id}/start`, { headers: agent });
  const run = consoleBox.getByRole("article", { name: `Run ${second.run_id}` });
  await expect(run.getByText("running")).toBeVisible();
  await run.getByRole("button", { name: "Cancel" }).click();
  await expect(run.getByText("cancelling")).toBeVisible();
  const told = await (await request.post(`${API}/v1/agent/runs/${second.run_id}/output`, { headers: agent, data: { chunk: "." } })).json();
  expect(told.cancel).toBe(true);
  await request.post(`${API}/v1/scripts/runs/${second.run_id}/complete`, { headers: agent, data: { output: ".\n[cancelled by operator]\n", exit_code: 130 } });
  await expect(run.getByText("cancelled", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
