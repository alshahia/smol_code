import { test, expect } from '@playwright/test';

// Loopback smoke for Phase 3 PREWORK + v1.9.x FE wire-up.
// The assertions verify that Vite serves the SPA shell and the root
// React container mounts. Header/Main + dashboard assertions require
// a backend on 127.0.0.1:7860 to be reachable so App.tsx renders past
// the error screen; those are tolerated with `test.skip` so the
// suite stays green without a backend.

test('app shell loads with a populated #root', async ({ page }) => {
  const response = await page.goto('/');
  expect(response?.ok()).toBeTruthy();
  await expect(page.locator('#root')).not.toBeEmpty();
  await expect(page).toHaveTitle(/smolcode/i);
});

test('Ctrl+Enter is dispatched without throwing', async ({ page }) => {
  await page.goto('/');
  // Ctrl+Enter (or Cmd+Enter on Mac) triggers the keyboard router's
  // submit handler. The handler is a best-effort DOM click on the
  // composer submit button; with no backend the test only verifies
  // that the dispatch does not crash the app.
  await page.keyboard.press('Control+Enter');
  await expect(page.locator('#root')).not.toBeEmpty();
});

test('Dashboard button is reachable when a backend is up', async ({ page }) => {
  await page.goto('/');
  const dashBtn = page.getByRole('button', { name: /dashboard/i }).first();
  if (await dashBtn.isVisible().catch(() => false)) {
    await dashBtn.click();
    await expect(page.getByRole('dialog', { name: /dashboard/i }).first()).toBeVisible({ timeout: 5000 });
  } else {
    test.skip(true, 'App shell did not render header (no backend on 7860)');
  }
});