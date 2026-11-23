import { defineConfig } from '@playwright/test';

const port = 4322;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: 'tests',
  use: {
    baseURL,
    launchOptions: { executablePath: process.env.PARALLAX_BROWSER },
  },
  webServer: {
    command: `node ./node_modules/astro/bin/astro.mjs preview --host 127.0.0.1 --port ${port} --ignore-lock`,
    url: baseURL + '/parallax-nba/',
    reuseExistingServer: false,
  },
});
