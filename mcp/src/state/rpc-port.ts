import fs from 'fs';
import path from 'path';
import os from 'os';

export function getRpcUrl(): string | undefined {
  if (process.env.DAINEXUS_RPC_URL) {
    return process.env.DAINEXUS_RPC_URL;
  }
  try {
    const portFile = path.join(os.homedir(), '.dainexus-console', 'rpc-port.txt');
    if (fs.existsSync(portFile)) {
      const port = fs.readFileSync(portFile, 'utf8').trim();
      if (port) {
        return `ws://127.0.0.1:${port}`;
      }
    }
  } catch (e) {}
  return undefined;
}
