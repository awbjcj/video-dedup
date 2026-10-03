const assert = require('node:assert/strict')
const { spawn } = require('node:child_process')
const { once } = require('node:events')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const script = `
import sys, threading
from pathlib import Path
sys.path.insert(0, 'tests')
from test_web_operations import WebOperationTests
import video_dedup as vd
fixture = WebOperationTests()
fixture.setUp()
state = fixture.overlapping_state()
class Handler(vd.make_web_review_handler(state, Path('review-ui/bundle.html').read_bytes())):
    def do_GET(self):
        if self.path == '/test-stop':
            self._send_json({'ok': True})
            threading.Thread(target=server.shutdown, daemon=True).start()
        else:
            super().do_GET()
server = vd.http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
print(server.server_address[1], flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    fixture.doCleanups()
`

async function checkRemoval(browser, permanent) {
  const server = spawn('python', ['-u', '-c', script], {
    cwd: path.resolve(__dirname, '../..'), stdio: ['pipe', 'pipe', 'inherit'],
  })
  const exited = once(server, 'exit')
  let url
  let page
  try {
    const [data] = await once(server.stdout, 'data')
    url = `http://127.0.0.1:${String(data).trim()}`
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(url)
    const before = await (await fetch(url + '/api/session')).json()
    assert.deepEqual(before.groups.map(group => group.files.map(file => file.id)), [[0, 1, 2], [0, 1, 3], [4, 5]])
    const removed = before.groups[0].files.find(file => file.id === 0)
    await page.getByRole('checkbox', { name: 'Select set 1 for bulk actions', exact: true }).check()
    assert.equal(await page.getByRole('checkbox', { name: 'Select set 2 for bulk actions', exact: true }).isChecked(), false, 'Bulk selection must not turn shared-file updates into reviews of other sets')
    await page.getByRole('button', { name: 'Keep all', exact: true }).click()
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await page.getByText('This set needs review', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Undo', exact: true }).click()
    await page.getByRole('button', { name: 'Previous', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Select set 1 for bulk actions', exact: true }).uncheck()
    await page.locator('#keep-file-0').uncheck()
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    assert.equal(await page.locator('#keep-file-0').isChecked(), false, 'Shared file must already be marked for quarantine in the unreviewed set')
    assert.equal(await page.locator('#keep-file-3').isChecked(), true)
    await page.getByText('This set needs review', { exact: true }).waitFor()
    await page.locator('#keep-file-0').check()
    await page.getByRole('button', { name: 'all', exact: true }).click()
    await page.getByRole('button', { name: /^Set 1\b/ }).click()
    assert.equal(await page.locator('#keep-file-0').isChecked(), true, 'Keeping a shared file must update its original set')
    await page.getByRole('button', { name: 'Undo', exact: true }).click()
    assert.equal(await page.locator('#keep-file-0').isChecked(), false)
    await page.getByRole('button', { name: /^Set 2\b/ }).click()
    assert.equal(await page.locator('#keep-file-0').isChecked(), false)
    await page.getByText('This set needs review', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Save plan', exact: true }).click()
    const saveDialog = page.getByRole('dialog')
    await saveDialog.getByLabel('Plan name').fill('Shared selections')
    await saveDialog.getByRole('button', { name: 'Save plan safely' }).click()
    await saveDialog.waitFor({ state: 'hidden' })
    await page.reload()
    await page.getByText('This set needs review', { exact: true }).waitFor()
    assert.equal(await page.locator('#keep-file-0').isChecked(), false, 'Saved shared selections must survive reload in unreviewed sets')
    await page.getByRole('button', { name: 'Apply reviewed', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByText(/Keep and quarantine choices stay in sync across sets/).waitFor()
    if (permanent) {
      await dialog.getByLabel('Permanently delete — cannot be undone').check()
      await dialog.getByLabel('Type DELETE to confirm').fill('DELETE')
    }
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/apply-reviewed') && response.request().method() === 'POST')
    await dialog.getByRole('button', { name: permanent ? 'Permanently delete reviewed files' : 'Quarantine reviewed sets' }).click()
    const response = await responsePromise
    assert.equal(response.status(), 200)
    const result = await response.json()
    assert.equal(result.appliedFileCount, 1)
    assert.equal(result.failedFileCount, 0)
    assert.deepEqual(result.session.groups.map(group => group.files.map(file => file.id)), [[1, 3], [4, 5]])
    assert.deepEqual(result.session.initialDecisions, [])
    assert.equal(fs.existsSync(removed.path), false)
    for (const group of before.groups) {
      for (const file of group.files.filter(file => file.id !== 0)) assert.equal(fs.existsSync(file.path), true)
    }
    if (!permanent) assert.equal(fs.readdirSync(result.quarantinePath).length, 1)
    await page.getByRole('heading', { name: 'Compare 2 related videos' }).waitFor()
    assert.equal(await page.getByRole('heading', { name: removed.name, exact: true }).count(), 0)
    await page.reload()
    await page.getByRole('heading', { name: 'Compare 2 related videos' }).waitFor()
    assert.equal(await page.locator('#keep-file-0').count(), 0)
    assert.deepEqual(errors, [])
  } finally {
    if (page) await page.close()
    if (url) await fetch(url + '/test-stop')
    else server.kill()
    await exited
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' })
  try {
    await checkRemoval(browser, false)
    await checkRemoval(browser, true)
    console.log('Shared removal browser regression passed: immediate cross-set selection, keep reversal, undo, saved selections after reload, quarantine, permanent deletion, and all-set cleanup.')
  } finally {
    await browser.close()
  }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
