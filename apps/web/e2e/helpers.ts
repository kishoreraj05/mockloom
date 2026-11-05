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
  return mockUrlOf(page);
}

/** Waits for the URL, because the header is empty until the workspace has loaded. */
export async function mockUrlOf(page: Page): Promise<string> {
  const header = page.getByTestId('mock-url');
  await expect(header).toHaveText(/^http/);
  return (await header.textContent())!;
}

/** Opens an example from the home page, whether or not an earlier test already created it. */
export async function openExample(page: Page, name: string): Promise<void> {
  await page.goto('/');
  await page
    .getByRole('button', { name: `Open the ${name} example` })
    .or(page.getByRole('link', { name: `Open your ${name} workspace` }))
    .click();
  await expect(page).toHaveURL(/\/w\//);
}
