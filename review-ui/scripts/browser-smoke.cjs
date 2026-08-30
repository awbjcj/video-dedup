const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

async function main() {
  const url = process.argv[2]
  const outputDirectory = process.argv[3] || path.join(process.cwd(), '.tmp-browser-output')
  if (!url) throw new Error('Usage: node scripts/browser-smoke.cjs URL [OUTPUT_DIRECTORY]')
  fs.mkdirSync(outputDirectory, { recursive: true })

  const executablePath =
    process.env.PLAYWRIGHT_CHROME_PATH ||
    (process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' : undefined)
  const browser = await chromium.launch({ headless: true, executablePath })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const consoleProblems = []
  const failedResponses = []
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      consoleProblems.push({ type: message.type(), text: message.text() })
    }
  })
  page.on('pageerror', (error) => consoleProblems.push({ type: 'pageerror', text: error.message }))
  page.on('response', (response) => {
    if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() })
  })

  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120_000 })
    assert.equal(response.status(), 200)
    await page.getByRole('heading', { name: 'Video Dedup Review' }).waitFor({ timeout: 120_000 })
    await page.getByRole('heading', { name: /Compare .* related videos/ }).waitFor()
    await page.waitForTimeout(750)

    assert.equal(await page.getByText('421 shown', { exact: true }).count(), 1)
    assert.equal(await page.getByText('0 / 421 sets', { exact: true }).count(), 1)
    assert.equal(await page.getByText('1,810', { exact: true }).count(), 1)
    const buttonCount = await page.getByRole('button').count()
    const namedButtonCount = await page.getByRole('button', { name: /.+/ }).count()
    const checkboxCount = await page.getByRole('checkbox').count()
    const namedCheckboxCount = await page.getByRole('checkbox', { name: /.+/ }).count()
    assert.equal(namedButtonCount, buttonCount)
    assert.equal(namedCheckboxCount, checkboxCount)

    await page.screenshot({ path: path.join(outputDirectory, 'review-desktop.png'), fullPage: false })

    await page.getByRole('checkbox', { name: 'Select set 2 for bulk actions' }).click()
    const bulkRegion = page.getByRole('region', { name: 'Bulk actions' })
    await bulkRegion.getByRole('button', { name: 'Apply recommendation' }).click()
    await page.getByText('1 / 421 sets', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Undo' }).click()
    await page.getByText('0 / 421 sets', { exact: true }).waitFor()

    await bulkRegion.getByRole('button', { name: 'Keep all' }).click()
    await page.getByText('1 / 421 sets', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Undo' }).click()
    await page.getByText('0 / 421 sets', { exact: true }).waitFor()

    await page.getByRole('button', { name: 'Save plan' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('heading', { name: 'Save this review plan?' }).waitFor()
    assert.match(await dialog.innerText(), /421 unreviewed sets will keep every file/i)
    await dialog.getByRole('button', { name: 'Continue reviewing' }).click()

    const groupSearch = page.getByRole('searchbox', { name: 'Search duplicate sets' })
    await groupSearch.fill('this-file-does-not-exist')
    await page.getByText('No sets match this filter.').waitFor()
    await groupSearch.fill('')

    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.waitForTimeout(750)
    await page.screenshot({ path: path.join(outputDirectory, 'review-mobile.png'), fullPage: false })

    const accessibilityMetrics = await page.evaluate(() => {
      const title = document.querySelector('h1')
      const titleStyle = title ? getComputedStyle(title) : null
      const titleLineHeight = titleStyle ? Number.parseFloat(titleStyle.lineHeight) : 0
      const titleLineCount = title && titleLineHeight
        ? Math.round(title.getBoundingClientRect().height / titleLineHeight)
        : 0
      return {
        rootFontSize: Number.parseFloat(getComputedStyle(document.documentElement).fontSize),
        viewportWidth: document.documentElement.clientWidth,
        contentWidth: document.documentElement.scrollWidth,
        titleLineCount,
      }
    })
    assert.ok(accessibilityMetrics.rootFontSize >= 17, 'Root font size should be at least 17px')
    assert.equal(accessibilityMetrics.contentWidth, accessibilityMetrics.viewportWidth)
    assert.equal(accessibilityMetrics.titleLineCount, 1)

    const headings = await page.locator('h1, h2, h3').allTextContents()
    const metrics = await page.evaluate(() => {
      const navigation = performance.getEntriesByType('navigation')[0]
      return navigation
        ? {
            domContentLoadedMs: Math.round(navigation.domContentLoadedEventEnd),
            loadMs: Math.round(navigation.loadEventEnd),
          }
        : null
    })
    assert.deepEqual(consoleProblems, [])
    assert.deepEqual(failedResponses, [])
    console.log(JSON.stringify({ ok: true, headings, metrics, accessibilityMetrics, buttonCount, checkboxCount }, null, 2))
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
