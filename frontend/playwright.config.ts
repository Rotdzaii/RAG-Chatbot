import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'chat-progress.spec.ts',
  outputDir: process.env.CHAT_REVIEW_DIR ? `${process.env.CHAT_REVIEW_DIR}/test-results` : '../data/chat-progress-review/test-results',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5178', browserName: 'chromium', channel: 'msedge',
    viewport: { width: 1440, height: 1000 }, timezoneId: 'Asia/Bangkok',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5178 --strictPort',
    url: 'http://127.0.0.1:5178',
    reuseExistingServer: false,
    env: {
      VITE_API_BASE_URL: 'http://127.0.0.1:48080',
      VITE_SUPABASE_URL: 'http://127.0.0.1:48081',
      VITE_SUPABASE_PUBLISHABLE_KEY: 'fixture-publishable-key',
    },
  },
})
