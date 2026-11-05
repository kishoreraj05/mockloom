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

  // A reload starts from the newest 1,000 rows; the rest are a click away.
  await page.getByLabel('Filter requests').fill('');
  await page.waitForTimeout(1000); // Let the batched writer reach the database.
  await page.reload();
  await expect(page.getByText('1000', { exact: true })).toBeVisible({ timeout: 15_000 });
  const scroller = page.getByTestId('log-rows');
  await scroller.evaluate((element) => element.scrollTo(0, 0));
  await page.getByRole('button', { name: 'Load older requests' }).click();
  await expect(page.getByText('2000', { exact: true })).toBeVisible({ timeout: 15_000 });
});
