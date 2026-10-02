const assert = require('node:assert/strict')
const { spawn } = require('node:child_process')
const { once } = require('node:events')
const { chromium } = require('playwright')
const path = require('node:path')
const script = `
import sys, threading, time
from pathlib import Path
sys.path.insert(0, 'tests')
from test_web_operations import WebOperationTests
import video_dedup as vd
fixture = WebOperationTests()
fixture.setUp()
(fixture.root / 'empty').mkdir()
(fixture.root / 'valid').mkdir()
vd.subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=32x32:r=1', '-t', '12', '-c:v', 'mpeg4', str(fixture.root / 'valid' / 'sample.mp4')], check=True)
move = vd.shutil.move
def slow_move(a, b):
    time.sleep(2)
    return move(a, b)
vd.shutil.move = slow_move
class Handler(vd.make_web_review_handler(fixture.state, Path('review-ui/bundle.html').read_bytes())):
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
    server.shutdown()
    server.server_close()
    fixture.doCleanups()
`
async function main() {
  const server = spawn('python', ['-u', '-c', script], { cwd: path.resolve(__dirname, '../..'), stdio: ['pipe', 'pipe', 'inherit'] })
  let url
  let browser
  try {
    const [data] = await once(server.stdout, 'data')
    url = `http://127.0.0.1:${String(data).trim()}`
    browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' })
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(url)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const settings = page.getByRole('dialog')
    const roots = await settings.getByLabel('Folder paths').inputValue()
    assert.ok(roots.length)
    assert.equal(await settings.getByRole('button', { name: 'Rescan with all settings' }).isEnabled(), true)
    await settings.getByLabel('Folder paths').fill('')
    assert.equal(await settings.getByRole('button', { name: 'Rescan with all settings' }).isDisabled(), true)
    await settings.getByLabel('Folder paths').fill(roots)
    await settings.getByRole('button', { name: 'Close', exact: true }).first().click()
    await page.getByRole('button', { name: 'Keep only this' }).first().click()
    await page.getByRole('button', { name: 'Apply reviewed', exact: true }).click()
    let dialog = page.getByRole('dialog')
    await dialog.getByLabel('Permanently delete — cannot be undone').check()
    const deletion = dialog.getByRole('button', { name: 'Permanently delete reviewed files' })
    assert.equal(await deletion.isDisabled(), true)
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE')
    assert.equal(await deletion.isEnabled(), true)
    await page.setViewportSize({ width: 390, height: 844 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await deletion.click()
    await page.getByText(/1 files deleted; 0 refused/).first().waitFor()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.getByRole('button', { name: 'Keep only this' }).first().click()
    await page.getByRole('button', { name: 'Apply reviewed', exact: true }).click()
    dialog = page.getByRole('dialog')
    assert.equal(await dialog.getByLabel('Quarantine — move files for recovery').isChecked(), true)
    await dialog.getByRole('button', { name: 'Quarantine reviewed sets' }).click()
    await page.getByRole('progressbar', { name: 'File removal progress' }).first().waitFor()
    await page.getByText(/1 files quarantined; 0 refused/).first().waitFor()
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await page.getByLabel('Folder paths').fill(path.join(roots, 'empty'))
    await page.getByRole('button', { name: 'Rescan with all settings' }).click()
    await page.getByText(/No supported video files found/).first().waitFor()
    await page.getByLabel('Folder paths').fill(path.join(roots, 'valid'))
    await page.getByRole('button', { name: 'Rescan with all settings' }).click()
    await page.getByText('Rescan complete. Review data has been refreshed.').first().waitFor({ timeout: 30000 }).catch(async error => { console.error(await page.evaluate(() => fetch('/api/rescan-status').then(r => r.json()))); throw error })
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
    await page.getByRole('heading', { name: 'No matches meet these settings' }).waitFor()
    await page.reload()
    await page.getByText('Rescan complete. Review data has been refreshed.').first().waitFor()
    assert.deepEqual(errors, [])
    console.log('Browser operations passed: folders, confirmation, permanent deletion, quarantine progress, mobile overflow, default reset, scan failure recovery, real scan, reload.')
  } finally {
    if (browser) await browser.close()
    if (url) await fetch(url + '/test-stop')
    await once(server, 'exit')
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
