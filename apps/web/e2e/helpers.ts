import { expect, type Page } from '@playwright/test';

/** Each test gets its own workspace, created the way a user creates one. */
export async function createPetstore(page: Page, name: string) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Start from the Petstore spec' }).click();
  await expect(page.getByTestId('spec-check')).toContainText('6 routes');
  await page.getByLabel('Workspace name').fill(name);
  await page.getByRole('button', { name: 'Create mock server' }).click();
  await expect(page).toHaveURL(/\/w\//);
  await expect(page.getByRole('img', { name: 'Log stream live' })).toBeVisible();
  const url = await page.getByTestId('mock-url').textContent();
  return url!;
}
