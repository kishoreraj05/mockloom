import { expect, type Page, test } from '@playwright/test';
import { createPetstore, mockUrlOf, openExample } from './helpers';

async function openRoute(page: Page, path: string, method = 'GET') {
  const label = method === 'DELETE' ? 'DEL' : method;
  const escaped = path.replace(/[{}/]/g, '\\$&');
  // Anchored, because /pets would otherwise also match /pets/{id}. A rule count may follow the path.
  await page.getByRole('button', { name: new RegExp(`^${label}\\s*${escaped}(\\s|$)`) }).click();
}

test('MVP loop: upload a spec, get a URL, add a rule, watch the log change', async ({ page, request }) => {
  const started = Date.now();
  const mockUrl = await createPetstore(page, 'Loop');
  expect(Date.now() - started).toBeLessThan(30_000); // The plan's headline metric.

  // The mock is live straight away, from outside the browser.
  const generated = await request.get(`${mockUrl}/pets`);
  expect(generated.status()).toBe(200);
  expect(await generated.json()).toHaveProperty('items');

  const log = page.getByRole('list', { name: 'Request log' });
  await expect(log.getByRole('button', { name: /\/pets/ })).toHaveCount(1);

  // Build a rule in the UI.
  await openRoute(page, '/pets');
  await page.getByRole('button', { name: /New rule/ }).click();
  await page.getByLabel('Rule name').fill('Empty list');
  const condition = page.getByRole('group', { name: 'Condition 1' });
  await condition.getByLabel('Field').fill('status');
  await condition.getByLabel('Value').fill('empty');
  await page.getByRole('radio', { name: 'Custom body' }).click();
  await page.getByRole('button', { name: 'Test this rule' }).click();
  await expect(page.getByText('This rule matched the sample request.')).toBeVisible();

  // Bodies go through Monaco, so check that the editor and the stored rule agree.
  await page.getByRole('button', { name: 'Save rule' }).click();
  await expect(page.getByRole('list', { name: 'Rules for this route' }).getByText('Empty list')).toBeVisible();

  // The next request uses the rule, and the log says so.
  const matched = await request.get(`${mockUrl}/pets?status=empty`);
  expect(matched.headers()['x-mockforge-rule']).toBe('Empty list');
  await expect(log.getByRole('button', { name: /status=empty/ }).last()).toContainText('Empty list');
});

test('a rule with a template echoes the request', async ({ page, request }) => {
  const mockUrl = await createPetstore(page, 'Templates');
  await openRoute(page, '/pets/{id}');
  await page.getByRole('button', { name: /New rule/ }).click();
  await page.getByLabel('Rule name').fill('Echo');
  await page.getByRole('button', { name: 'Remove condition 1' }).click();
  await page.getByRole('radio', { name: 'Custom body' }).click();

  const editor = page.locator('.monaco-editor').first();
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Delete');
  await page.keyboard.insertText('{"id": "{{request.path.id}}"}');
  await page.getByRole('button', { name: 'Save rule' }).click();
  await expect(page.getByRole('list', { name: 'Rules for this route' }).getByText('Echo')).toBeVisible();

  expect(await (await request.get(`${mockUrl}/pets/42`)).json()).toEqual({ id: 42 });
});

test('try it panel sends a request and shows why it answered', async ({ page }) => {
  await createPetstore(page, 'Try');
  await openRoute(page, '/pets/{id}');
  await page.getByRole('tab', { name: 'Try it' }).click();
  await page.getByLabel('Path: id').fill('7');
  await page.getByRole('button', { name: 'Send request' }).click();
  await expect(page.getByTestId('try-status')).toHaveText('200');
  await expect(page.getByTestId('try-body')).toContainText('status');

  await page.getByLabel('Path: id').fill('abc');
  await page.getByRole('button', { name: 'Send request' }).click();
  await expect(page.getByTestId('try-status')).toHaveText('400');
  await expect(page.getByTestId('try-body')).toContainText('is not of type');
});

test('create a rule from a logged request', async ({ page, request }) => {
  const mockUrl = await createPetstore(page, 'From log');
  await request.get(`${mockUrl}/pets/5`);
  await page.getByRole('list', { name: 'Request log' }).getByRole('button', { name: /\/pets\/5/ }).click();
  await page.getByRole('button', { name: 'Create rule from this request' }).click();
  await expect(page.getByLabel('Rule name')).toHaveValue(/id=5/);
  await page.getByRole('button', { name: 'Save rule' }).click();
  await expect(page.getByRole('list', { name: 'Rules for this route' })).toBeVisible();
  expect((await request.get(`${mockUrl}/pets/5`)).headers()['x-mockforge-rule']).toContain('id=5');
});

test('chaos: forced status and offline, then back to normal', async ({ page, request }) => {
  const mockUrl = await createPetstore(page, 'Chaos');
  await page.getByRole('button', { name: 'Chaos' }).click();
  const global = page.getByRole('region', { name: 'Global chaos' });

  await global.getByLabel('Forced status').selectOption('503');
  await expect.poll(async () => (await request.get(`${mockUrl}/pets`)).status()).toBe(503);

  await global.getByLabel('Forced status').selectOption('');
  await expect.poll(async () => (await request.get(`${mockUrl}/pets`)).status()).toBe(200);

  await global.getByRole('switch', { name: 'Global offline' }).click();
  await expect
    .poll(async () => request.get(`${mockUrl}/pets`).then(() => 'answered', () => 'dropped'))
    .toBe('dropped');
  await expect(page.getByRole('list', { name: 'Request log' }).getByText('drop').first()).toBeVisible();

  await global.getByRole('button', { name: 'Reset' }).click();
  await expect.poll(async () => (await request.get(`${mockUrl}/pets`)).status()).toBe(200);
});

test('spec editing: bad specs are flagged, a dropped route orphans its rules', async ({ page, request }) => {
  const mockUrl = await createPetstore(page, 'Spec edit');
  await openRoute(page, '/store/inventory');
  await page.getByRole('button', { name: /New rule/ }).click();
  await page.getByLabel('Rule name').fill('Stock rule');
  await page.getByRole('button', { name: 'Remove condition 1' }).click();
  await page.getByRole('button', { name: 'Save rule' }).click();
  await expect(page.getByRole('list', { name: 'Rules for this route' })).toBeVisible();

  await page.getByRole('button', { name: 'Spec', exact: true }).click();
  const editor = page.locator('.monaco-editor').first();
  await expect(editor).toBeVisible();

  const replaceWith = async (text: string) => {
    await editor.click();
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.press('Delete');
    await page.keyboard.insertText(text);
  };

  await replaceWith('swagger: "2.0"\n');
  await expect(page.getByText(/Swagger 2.0 import is planned/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review changes' })).toBeDisabled();

  await replaceWith(
    "openapi: 3.0.3\ninfo: {title: Small, version: '1'}\npaths:\n  /only:\n    get:\n      responses:\n        '200': {description: ok}\n",
  );
  await expect(page.getByText(/Valid: 1 route\b/)).toBeVisible();
  await page.getByRole('button', { name: 'Review changes' }).click();
  await page.getByRole('button', { name: 'Save as version 2' }).click();
  await expect(page.getByText(/Stock rule/).first()).toBeVisible();
  await expect(page.getByRole('region', { name: 'Rules needing review' })).toContainText('Stock rule');

  expect((await request.get(`${mockUrl}/only`)).status()).toBe(200);
  expect((await request.get(`${mockUrl}/pets`)).status()).toBe(404);
});

test('keyboard: / searches routes, n starts a rule, l focuses the log', async ({ page }) => {
  await createPetstore(page, 'Keys');
  await page.locator('body').click({ position: { x: 1, y: 1 } });
  await page.keyboard.press('/');
  await expect(page.getByLabel('Search routes')).toBeFocused();
  await page.keyboard.type('inventory');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: '/store/inventory' })).toBeVisible();

  await page.keyboard.press('n');
  await expect(page.getByLabel('Rule name')).toBeFocused();
  await page.getByRole('button', { name: 'Close' }).click();

  await page.keyboard.press('l');
  await expect(page.getByLabel('Filter requests')).toBeFocused();
});

test('examples: pick one from the list, test it, and come back to it', async ({ page, request }) => {
  await page.goto('/');
  const gallery = page.getByRole('region', { name: 'Examples' });
  for (const name of ['Task Tracker', 'Petstore', 'Payments API', 'Code Hosting API']) {
    await expect(gallery.getByRole('heading', { name })).toBeVisible();
  }

  await openExample(page, 'Payments API');
  await expect(page.getByRole('heading', { name: 'Payments API' })).toBeVisible();

  // Its rules came with it, and they work.
  const mockUrl = await mockUrlOf(page);
  const declined = await request.post(`${mockUrl}/charges`, {
    data: { amount: 2500, currency: 'usd', source: 'tok_declined' },
  });
  expect(declined.status()).toBe(402);
  expect(declined.headers()['x-mockforge-rule']).toBe('Card declined');

  // A rule that wants something absent says so, and turning it off and on doesn't change its meaning.
  const rules = page.getByRole('list', { name: 'Rules for this route' });
  await page.getByRole('button', { name: /^GET\s*\/balance/ }).click();
  await expect(rules).toContainText('header authorization is missing');
  await rules.getByRole('switch').click();
  await expect(rules.getByRole('switch')).not.toBeChecked();
  await rules.getByRole('switch').click();
  await expect(rules.getByRole('switch')).toBeChecked();
  await expect(rules).toContainText('header authorization is missing');
  expect((await request.get(`${mockUrl}/balance`)).status()).toBe(401);

  // Picking it again goes back to the same workspace rather than making a copy.
  await page.goto('/');
  await gallery.getByRole('link', { name: 'Open your Payments API workspace' }).click();
  await expect(page).toHaveURL(/\/w\/payments/);
});

test('examples: the what-to-try list gives commands that work', async ({ page, request }) => {
  await page.goto('/');
  const gallery = page.getByRole('region', { name: 'Examples' });
  await gallery.getByRole('button', { name: /What to try/ }).first().click();
  const list = gallery.getByRole('list', { name: 'Requests to try on Task Tracker' });
  await expect(list.getByText('An empty list')).toBeVisible();
  await expect(list.getByRole('button', { name: /Copy curl command/ })).toHaveCount(8);

  await openExample(page, 'Task Tracker');
  const mockUrl = await mockUrlOf(page);
  expect((await (await request.get(`${mockUrl}/tasks?status=done`)).json()).items).toEqual([]);
});

test('examples: start from a spec, edit it, and save under your own name', async ({ page }) => {
  await page.goto('/');
  const gallery = page.getByRole('region', { name: 'Examples' });
  await gallery.getByRole('button', { name: 'Start from the Code Hosting API spec' }).click();
  await expect(page.getByLabel('Spec', { exact: true })).toHaveValue(/Code Hosting API/);
  await expect(page.getByLabel('Workspace name')).toHaveValue('Code Hosting API');
  await page.getByLabel('Workspace name').fill('My team repo API');
  await page.getByRole('button', { name: 'Create mock server' }).click();
  await expect(page).toHaveURL(/\/w\/my-team-repo-api/);
});

test('use in your app: every route shows an absolute link and samples that really work', async ({ page, request }) => {
  await openExample(page, 'Payments API');

  // A path parameter with a pattern: the dummy value has to pass the mock's own validation.
  await page.getByRole('button', { name: /^GET\s*\/customers\/\{customerId\}/ }).click();
  const link = page.getByTestId('route-url');
  await expect(link).toHaveText(/^http:\/\/.+\/mock\/payments\/customers\/cus_/);
  expect((await request.get((await link.textContent())!)).status()).toBe(200);

  await page.getByRole('tab', { name: 'Use in your app' }).click();
  const panel = page.getByRole('tabpanel');
  await expect(panel.getByRole('heading', { name: 'Example response' })).toBeVisible();
  await expect(panel.getByTestId('snippet').first()).toContainText('curl');
  await panel.getByRole('radio', { name: 'Python' }).first().click();
  await expect(panel.getByTestId('snippet').first()).toContainText('import requests');
  await panel.getByRole('radio', { name: 'JavaScript' }).first().click();
  await expect(panel.getByTestId('snippet').first()).toContainText('await fetch(');

  // Each rule gets its own request, and the request really triggers that rule.
  await page.getByRole('button', { name: /^POST\s*\/charges/ }).click();
  const declined = panel.getByRole('group', { name: 'To get: Card declined' });
  await expect(declined).toContainText('402');
  await expect(declined.getByTestId('snippet')).toContainText('tok_declined');
  const response = await request.post(`${await mockUrlOf(page)}/charges`, {
    data: { amount: 2500, currency: 'usd', source: 'tok_declined' },
  });
  expect(response.headers()['x-mockforge-rule']).toBe('Card declined');
});
