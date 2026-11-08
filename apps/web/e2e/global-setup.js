import { unlink } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

export default async function globalSetup() {
  // Clean the SQLite test DB for a fresh run.
  try {
    await unlink(resolve(dirname(fileURLToPath(import.meta.url)), "../../services/api/e2e.db"));
  } catch {
    /* not present */
  }
}
