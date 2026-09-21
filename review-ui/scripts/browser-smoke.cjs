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
    await page.getByText('Duplicated footage').first().waitFor()
    assert.ok(await page.getByLabel(/Duplicate timeline for/).count() > 0)
    assert.ok(await page.getByRole('button', { name: /Duplicate segment/ }).count() > 0)
    assert.ok(await page.getByRole('button', { name: 'Open in folder' }).count() > 0)
    assert.ok(await page.getByRole('button', { name: 'Move…' }).count() > 0)
    const firstDuplicateSegment = page.getByRole('button', { name: /Duplicate segment/ }).first()
    await firstDuplicateSegment.focus()
    assert.equal(await firstDuplicateSegment.evaluate((element) => document.activeElement === element), true)
    await page.waitForTimeout(750)

    const initialSession = await page.evaluate(async () => {
      const response = await fetch('/api/session')
      if (!response.ok) throw new Error(`Session request failed with ${response.status}`)
      return response.json()
    })
    let activeGroupCount = initialSession.summary.groupCount
    assert.equal(await page.getByText(`${activeGroupCount.toLocaleString()} shown`, { exact: true }).count(), 1)
    assert.equal(await page.getByText(`0 / ${activeGroupCount.toLocaleString()} sets`, { exact: true }).count(), 1)
    assert.equal(
      await page.getByText(initialSession.summary.fileCount.toLocaleString(), { exact: true }).count(),
      1,
    )
    assert.equal(
      await page.getByText(
        `${initialSession.summary.filteredShortFileCount.toLocaleString()} clips under 10 sec hidden`,
        { exact: true },
      ).count(),
      1,
    )

    await page.getByRole('button', { name: 'Settings' }).click()
    const settingsDialog = page.getByRole('dialog', { name: 'Detection and safety settings' })
    await settingsDialog.getByLabel('Minimum duplicated timeline').waitFor()
    assert.equal(await settingsDialog.getByLabel('Watermark and re-encode tolerance').inputValue(), '20')
    assert.equal(await settingsDialog.getByLabel('Deletion safety coverage').inputValue(), '95')
    assert.match(await settingsDialog.innerText(), /matched timeline coverage, not pixel similarity/i)
    await page.screenshot({ path: path.join(outputDirectory, 'settings-desktop.png'), fullPage: false })
    await page.setViewportSize({ width: 390, height: 844 })
    assert.equal(await settingsDialog.evaluate((element) => element.scrollWidth <= element.clientWidth), true)
    await page.screenshot({ path: path.join(outputDirectory, 'settings-mobile.png'), fullPage: false })
    await page.setViewportSize({ width: 1440, height: 1000 })

    const duplicateThreshold = settingsDialog.getByLabel('Minimum duplicated timeline')
    const applyReviewSettings = settingsDialog.getByRole('button', { name: 'Apply to review' })
    await duplicateThreshold.fill('95')
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/settings') && response.status() === 200),
      applyReviewSettings.click(),
    ])
    assert.equal(await duplicateThreshold.inputValue(), '95')
    await duplicateThreshold.fill('0')
    const [resetResponse] = await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/settings') && response.status() === 200),
      applyReviewSettings.click(),
    ])
    activeGroupCount = (await resetResponse.json()).summary.groupCount
    await page.getByText(`0 / ${activeGroupCount.toLocaleString()} sets`, { exact: true }).waitFor()
    await settingsDialog.getByRole('button', { name: 'Close', exact: true }).last().click()

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
    await page.getByText(`1 / ${activeGroupCount.toLocaleString()} sets`, { exact: true }).waitFor()

    const setFilters = page.getByRole('group', { name: 'Filter sets' })
    const setNavigation = page.getByRole('navigation', { name: 'Duplicate set navigation' })
    const reviewWorkspace = page.locator('main#review-workspace')
    await setFilters.getByRole('button', { name: 'all', exact: true }).click()
    await setNavigation.getByRole('button', { name: 'Next' }).click()
    await reviewWorkspace.getByText('Set 2', { exact: true }).waitFor()
    await setFilters.getByRole('button', { name: 'decided', exact: true }).click()
    assert.equal(await setNavigation.getByRole('button', { name: 'Previous' }).isDisabled(), true)
    assert.equal(await setNavigation.getByRole('button', { name: 'Next' }).isDisabled(), true)
    await setFilters.getByRole('button', { name: 'To review', exact: true }).click()
    await reviewWorkspace.getByText('Set 1', { exact: true }).waitFor()
    await setNavigation.getByRole('button', { name: 'Next' }).click()
    await reviewWorkspace.getByText('Set 3', { exact: true }).waitFor()

    await page.getByRole('button', { name: 'Apply reviewed' }).click()
    const applyDialog = page.getByRole('dialog', { name: 'Quarantine reviewed removals?' })
    await applyDialog.getByText(/Unreviewed sets stay untouched/i).waitFor()
    await applyDialog.getByText(/removed from the active plan and review queue/i).waitFor()
    await applyDialog.getByRole('button', { name: 'Cancel' }).click()
    await page.getByRole('button', { name: 'Undo' }).click()
    await page.getByText(`0 / ${activeGroupCount.toLocaleString()} sets`, { exact: true }).waitFor()

    await bulkRegion.getByRole('button', { name: 'Keep all' }).click()
    await page.getByText(`1 / ${activeGroupCount.toLocaleString()} sets`, { exact: true }).waitFor()
    await page.getByRole('button', { name: 'Undo' }).click()
    await page.getByText(`0 / ${activeGroupCount.toLocaleString()} sets`, { exact: true }).waitFor()

    await page.getByRole('button', { name: 'Save plan' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('heading', { name: 'Save this review plan?' }).waitFor()
    assert.match(
      await dialog.innerText(),
      new RegExp(`${activeGroupCount.toLocaleString()} unreviewed sets will keep every file`, 'i'),
    )
    await dialog.getByRole('button', { name: 'Continue reviewing' }).click()

    const groupSearch = page.getByRole('searchbox', { name: 'Search duplicate sets' })
    await groupSearch.fill('this-file-does-not-exist')
    await page.getByText('No sets match this filter.').waitFor()
    await groupSearch.fill('')

    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.waitForTimeout(750)
    await page.screenshot({ path: path.join(outputDirectory, 'review-mobile.png'), fullPage: false })
    await page.getByText('Duplicated footage').first().scrollIntoViewIfNeeded()
    await page.waitForTimeout(250)
    await page.screenshot({ path: path.join(outputDirectory, 'review-mobile-timeline.png'), fullPage: false })

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
