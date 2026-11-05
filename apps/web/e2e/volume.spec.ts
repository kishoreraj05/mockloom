import { expect, test } from '@playwright/test';
import { createPetstore } from './helpers';

// A trace of 10,000 requests is too big for Playwright to save.
test.use({ trace: 'off' });

test('the log holds 10,000 rows with only a screenful in the DOM', async ({ page }) => {
  test.setTimeout(120_000);
  const mockUrl = await createPetstore(page, 'Big log');
  await page.evaluate(async (url) => {
    let next = 0;
    const worker = async () => {
      while (next < 10_000) {
        await fetch(`${url}/pets/${next++}`);
      }
    };
    await Promise.all(Array.from({ length: 24 }, worker));
  }, mockUrl);
  const count = page.getByText('10000', { exact: true });
  await expect(count).toBeVisible({ timeout: 30_000 });

  const list = page.getByRole('list', { name: 'Request log' });
  expect(await list.getByRole('button').count()).toBeLessThan(80);

  // Filtering 10,000 rows has to feel instant.
  const started = Date.now();
  await page.getByLabel('Filter requests').fill('/pets/9999');
  await expect(list.getByRole('button')).toHaveCount(1);
  expect(Date.now() - started).toBeLessThan(1000);
});
