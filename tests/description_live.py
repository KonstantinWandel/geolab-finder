"""Inspect official source sections on the live SOEP finder at desktop/mobile widths."""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = 'https://soep-faiss.geolab.soz.uni-bielefeld.de'
OUTPUT = Path(sys.argv[1])
OUTPUT.mkdir(parents=True, exist_ok=True)


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for width, height in [(1440, 960), (390, 844)]:
            context = await browser.new_context(viewport={'width': width, 'height': height})
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto(BASE)
            await page.get_by_role('button', name='Decline all', exact=True).click()
            for code, section in [('pglabnet', 'Official note'), ('pgisced11', 'Official note'),
                                  ('plh0182', 'Question wording')]:
                await page.locator('textarea').fill(code)
                async with page.expect_response(lambda r: r.url.endswith('/api/soep/advice')) as response:
                    await page.get_by_role('button', name='Ask', exact=True).click()
                payload = await (await response.value).json()
                source = next(row for row in payload['recommended_variables'] if row['variable_name'] == code)
                assert '\n' in source['description_original'], (width, code, 'lost original line breaks')
                row = page.locator('.result-item').filter(has=page.locator('.result-code', has_text=code)).last
                await row.get_by_role('button', name='Show full description', exact=True).click()
                await row.get_by_role('heading', name=section, exact=True).wait_for()
                await row.locator('.source-description summary').click()
                assert source['description_original'] == await row.locator('.source-description p').text_content()
                await row.locator('.source-description summary').click()
                await row.evaluate('(el) => el.scrollIntoView({block: "start"})')
                await page.screenshot(path=str(OUTPUT / f'description-{code}-{width}.png'))
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                print(json.dumps({'width': width, 'code': code, 'section': section, 'status': 'passed'}), flush=True)
            assert not errors, errors
            await context.close()
        await browser.close()


asyncio.run(run())
