import { mkdir, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
export default async function setup() {
  const directory = resolve('../runtime/summary-coverage/raw');
  await rm(directory, { recursive: true, force: true });
  await mkdir(directory, { recursive: true });
}
