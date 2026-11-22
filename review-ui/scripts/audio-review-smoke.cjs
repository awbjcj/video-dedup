// UI regression only: every audio endpoint is mocked; never makes a paid request.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

async function main() {
  const url = process.argv[2]
  if (!url) throw new Error('Usage: node scripts/audio-review-smoke.cjs URL [SCREENSHOT_DIR]')
  const output = process.argv[3] || '.tmp-audio-smoke'
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROME_PATH })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
    const problems = []
    let uploads = 0
    const pendingSaved = []
    const budget = { remaining_micros: 29_999_700, spent_micros: 300, reserved_micros: 0, threshold: 'ok' }
    page.on('pageerror', (error) => problems.push(error.message))
    await page.route('**/api/audio-review**', async (route) => {
      const request = route.request()
      if (request.url().endsWith('/availability')) {
        await route.fulfill({ json: { enabled: true, budget, maxClipPairs: 12 } })
      } else if (request.url().endsWith('/saved')) {
        await new Promise((resolve) => pendingSaved.push(resolve))
        await route.fulfill({ json: { result: null } })
      } else {
        const payload = request.postDataJSON()
        assert.equal(payload.confirmUpload, true)
        assert.equal(typeof payload.groupKey, 'string')
        assert.equal(request.headers()['x-video-dedup-review'], '1')
        uploads += 1
        await route.fulfill({ json: {
          budget, partial: false,
          notice: 'Audio evidence is advisory. Speech similarity does not prove whole-video or soundtrack equivalence.',
          evidence: [{ aId: 0, bId: 1, aName: 'Original interview.mp4', bName: 'Translated interview.mp4',
            aStartSeconds: 2, bStartSeconds: 14, durationSeconds: 12, status: 'different_language',
            reason: 'Detected speech languages differ; inspect both tracks.',
            aTranscript: { text: 'This is the original interview recording.', languages: ['en'], cached: true, accounting: 'settled' },
            bTranscript: { text: '这是翻译版本，保留音轨差异供人工检查。', languages: ['zh'], cached: false, accounting: 'held' },
          }],
        } })
      }
    })
    await page.goto(url, { waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: /Compare .* related videos/ }).waitFor()
    const choicesBefore = await page.getByRole('checkbox', { checked: true }).count()
    await page.getByText('Optional audio difference review', { exact: true }).click()
    const send = page.getByRole('button', { name: 'Send matched audio for review' })
    await send.waitFor()
    assert.equal(uploads, 0)
    await send.click()
    await page.getByText('Different speech languages', { exact: true }).waitFor()
    assert.equal(uploads, 1)
    // A slow initial cache response must not erase a newly completed review.
    pendingSaved.forEach((resolve) => resolve())
    await page.waitForLoadState('networkidle')
    await page.getByText('Different speech languages', { exact: true }).waitFor()
    assert.equal(await page.getByRole('checkbox', { checked: true }).count(), choicesBefore)
    assert.match(await page.getByRole('region', { name: 'Audio difference review' }).innerText(), /billing pending/)
    await page.screenshot({ path: path.join(output, 'audio-review-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.screenshot({ path: path.join(output, 'audio-review-mobile.png'), fullPage: true })
    assert.deepEqual(problems, [])
    console.log('Audio UI passed: explicit consent, paired evidence, unchanged keepers, pending billing, desktop/mobile.')
  } finally {
    await browser.close()
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1 })
