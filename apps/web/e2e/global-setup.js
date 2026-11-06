import { unlink } from "node:fs/promises";

export default async function globalSetup() {
  // Clean the SQLite test DB for a fresh run.
  try {
    await unlink("../services/api/e2e.db");
  } catch {
    /* not present */
  }
}
