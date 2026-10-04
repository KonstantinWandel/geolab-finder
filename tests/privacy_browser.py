"""Playwright smoke test against staged builds; uses fixtures, never real visitor telemetry.

Run with a Python environment containing Playwright and Chromium. Serve the two dist directories
on localhost:18991/18992. Screenshots are written to the supplied temporary output directory.
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT = Path(sys.argv[1])
OUTPUT.mkdir(parents=True, exist_ok=True)
ROWS = [{'item_id': f'soep/pgen/item{i}', 'variable_name': f'pgtest{i}', 'label': f'Employment measure {i}',
         'rich_description': 'Monthly individual employment measure in the longitudinal panel.',
         'score': .85, 'dataset': 'pgen', 'source_key': 'soep', 'source_label': 'SOEP',
         'source_url': 'https://paneldata.org/', 'available_years_text': '2000-2024'} for i in range(3)]
RESULT = {'query_id': 'b' * 16, 'feedback_token': 'test-token', 'recommended_variables': ROWS}
OPTIONS = {'sources': [{'value': 'soep', 'label': 'SOEP'}], 'datasets': [], 'themes': [],
           'spatial_levels': [], 'nuts_levels': [], 'sample_groups': [], 'year_min': 2000, 'year_max': 2024}


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for mode, port in [('soep', 18991), ('inkar', 18992)]:
            for width, height in [(1440, 960), (390, 844)]:
                context = await browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
                page = await context.new_page()
                errors, events = [], []
                page.on('pageerror', lambda e: errors.append(str(e)))
                async def api(route):
                    path = route.request.url
                    if path.endswith('/soep/advice'):
                        await route.fulfill(json=RESULT)
                    elif path.endswith('/soep/filter-options') or '/soep/filter-options?' in path:
                        await route.fulfill(json=OPTIONS)
                    elif path.endswith('/soep/facet-counts'):
                        await route.fulfill(json={})
                    else:
                        events.append({'path': path, 'body': route.request.post_data_json})
                        await route.fulfill(status=204)
                await page.route('**/api/**', api)
                await page.goto(f'http://127.0.0.1:{port}/')
                await page.get_by_role('heading', name='Your privacy choices').wait_for()
                assert await page.locator('.privacy-options input:checked').count() == 0
                await page.screenshot(path=str(OUTPUT / f'{mode}-{width}-choices.png'), full_page=True)
                await page.get_by_role('button', name='Decline both', exact=True).click()
                await page.locator('textarea').fill('employment')
                await page.get_by_role('button', name='Ask', exact=True).click()
                await page.locator('.result-item').first.wait_for()
                await page.wait_for_timeout(150)
                keys = await page.evaluate('Object.keys(localStorage)')
                assert f'geolab_history_{mode}' not in keys and f'geolab_visitor_{mode}' not in keys
                assert not any('/analytics/event' in event['path'] for event in events)
                await page.get_by_role('button', name='Useful for this search', exact=True).first.click()
                await page.get_by_text('Feedback saved', exact=True).wait_for()
                assert events[-1]['body']['item_id'] == ROWS[0]['item_id']
                assert 'visitor_id' not in events[-1]['body']
                await page.locator('.result-select').first.check()
                csv_button = page.get_by_role('button', name='CSV', exact=True)
                async with page.expect_download() as download:
                    await csv_button.click()
                csv = await download.value
                csv_path = await csv.path()
                assert 'pgtest0' in Path(csv_path).read_text(encoding='utf-8-sig')
                assert 'pgtest1' not in Path(csv_path).read_text(encoding='utf-8-sig')
                await page.screenshot(path=str(OUTPUT / f'{mode}-{width}-results.png'), full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                await page.get_by_role('button', name='Privacy settings', exact=True).click()
                await page.get_by_role('button', name='Allow both', exact=True).click()
                await page.wait_for_timeout(150)
                assert await page.evaluate(f'!!localStorage.getItem("geolab_history_{mode}")')
                assert await page.evaluate(f'!!localStorage.getItem("geolab_visitor_{mode}")')
                await page.reload()
                await page.locator('.result-item').first.wait_for()
                await page.get_by_role('button', name='Privacy settings', exact=True).click()
                await page.get_by_role('button', name='Decline both', exact=True).click()
                await page.wait_for_timeout(150)
                assert await page.evaluate(f'localStorage.getItem("geolab_history_{mode}") === null')
                assert await page.evaluate(f'localStorage.getItem("geolab_visitor_{mode}") === null')
                assert any('/analytics/withdraw' in event['path'] for event in events)
                assert await page.locator('.result-item').count() == 3
                # An old grant must not survive a storage-quota failure during withdrawal.
                await page.get_by_role('button', name='Privacy settings', exact=True).click()
                await page.get_by_role('button', name='Allow both', exact=True).click()
                await page.wait_for_timeout(150)
                old_id = await page.evaluate(f'JSON.parse(localStorage.getItem("geolab_visitor_{mode}")).id')
                await page.evaluate('Storage.prototype.setItem = function() { throw new Error("quota") }')
                await page.get_by_role('button', name='Privacy settings', exact=True).click()
                await page.get_by_role('button', name='Decline both', exact=True).click()
                await page.get_by_text('Your browser blocked saving these choices.', exact=False).wait_for()
                await page.wait_for_timeout(150)
                assert await page.evaluate(f'localStorage.getItem("geolab_visitor_{mode}") === null')
                assert events[-1]['path'].endswith('/analytics/withdraw') and events[-1]['body']['visitor_id'] == old_id
                assert not errors, errors
                print(json.dumps({'mode': mode, 'width': width, 'status': 'passed'}), flush=True)
                await context.close()
        await browser.close()


asyncio.run(run())
