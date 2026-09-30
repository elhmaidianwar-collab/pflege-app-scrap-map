import sys
import os
import re
import json
import asyncio
import urllib.parse
from urllib.parse import urljoin
from io import BytesIO

from starlette.applications import Starlette
from starlette.responses import JSONResponse, HTMLResponse, Response
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
import uvicorn
import requests
import pandas as pd
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

IGNORE_DOMAINS = [
    'google.com', 'gstatic.com', 'fontawesome.com', 'defiant.com', 
    'sentry.io', 'wixpress.com', 'wordpress.org', 'schema.org', 
    'cloudflare.com', 'w3.org', 'doubleclick.net'
]

def clean_email(email_str):
    if not email_str:
        return None
    email = email_str.strip().strip('.').lower()
    if any(email.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif', '.css', '.js']):
        return None
    for domain in IGNORE_DOMAINS:
        if domain in email:
            return None
    return email

# Real Google Maps Scraper using Async Playwright with any custom query/country/radius
async def search_google_maps(query, city, country="Deutschland", radius="", max_scrolls=6):
    parts = [query, city]
    if radius:
        parts.append(radius)
    if country:
        parts.append(country)
    full_query = " ".join([p for p in parts if p]).strip()
    search_url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(full_query)}?hl=de"
    
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale='de-DE',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        try:
            print(f"[*] Navigating to Google Maps: {search_url}")
            await page.goto(search_url, wait_until='domcontentloaded', timeout=25000)
            await page.wait_for_timeout(2500)
            
            # Consent popup
            try:
                consent = page.locator('button:has-text("Alle akzeptieren"), button:has-text("Ich stimme zu"), form[action*="consent"] button')
                if await consent.count() > 0:
                    await consent.first.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass
                
            feed = page.locator('div[role="feed"]')
            
            # Scroll feed to load items
            if await feed.count() > 0:
                for _ in range(max_scrolls):
                    await feed.evaluate('el => el.scrollBy(0, 1500)')
                    await page.wait_for_timeout(700)
            else:
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
                
            links = page.locator('div[role="feed"] a[href*="/maps/place/"]')
            total = await links.count()
            print(f"[+] Found {total} raw place links in Google Maps")
            
            for i in range(total):
                link = links.nth(i)
                name = (await link.get_attribute('aria-label')) or ''
                href = (await link.get_attribute('href')) or ''
                
                if not name or name in [r['name'] for r in results]:
                    continue
                    
                parent = link.locator('xpath=ancestor::div[contains(@class, "Nv2PK")]')
                website = ''
                phone = ''
                address = ''
                
                if await parent.count() > 0:
                    web_el = parent.locator('a[data-value="Website"], a[aria-label*="Website"]')
                    if await web_el.count() > 0:
                        website = (await web_el.first.get_attribute('href')) or ''
                        
                    raw_text = await parent.inner_text()
                    lines = raw_text.split('\n')
                    for l in lines:
                        clean_l = l.strip()
                        if any(c.isdigit() for c in clean_l) and ('02' in clean_l or '01' in clean_l or '+49' in clean_l or '/' in clean_l):
                            match_phone = re.search(r'(\+49[\d\s/-]+|0[\d\s/-]{7,})', clean_l)
                            if match_phone:
                                phone = match_phone.group(0).strip()
                            else:
                                phone = clean_l
                        elif 'str' in clean_l.lower() or 'weg' in clean_l.lower() or 'platz' in clean_l.lower() or city.lower() in clean_l.lower():
                            if not address and len(clean_l) > 4:
                                address = clean_l
                                
                results.append({
                    'id': len(results) + 1,
                    'name': name,
                    'website': website,
                    'phone': phone or 'غير متوفر',
                    'address': address or city,
                    'email': 'قيد الاستخراج...'
                })
        except Exception as e:
            print("[-] Error during Google Maps scraping:", e)
        finally:
            await browser.close()
            
    return results

def scrape_email_from_website_sync(website_url):
    if not website_url:
        return 'لا يوجد موقع مسجل'
    if not website_url.startswith('http'):
        website_url = 'https://' + website_url
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }
    
    found_emails = set()
    try:
        res = requests.get(website_url, headers=headers, timeout=5, verify=False)
        emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', res.text)
        for e in emails:
            ce = clean_email(e)
            if ce:
                found_emails.add(ce)
                
        if not found_emails:
            for sub in ['/impressum', '/kontakt', '/kontakt.html', '/impressum.html', '/karriere', '/jobs']:
                try:
                    sub_url = urljoin(website_url, sub)
                    sub_res = requests.get(sub_url, headers=headers, timeout=4, verify=False)
                    if sub_res.status_code == 200:
                        sub_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', sub_res.text)
                        for e in sub_emails:
                            ce = clean_email(e)
                            if ce:
                                found_emails.add(ce)
                        if found_emails:
                            break
                except:
                    pass
    except Exception:
        return 'تعذر فتح الموقع'
        
    if not found_emails:
        return 'غير متوفر بالموقع'
        
    sorted_emails = sorted(list(found_emails), key=lambda x: (
        0 if any(k in x for k in ['bewerbung', 'karriere', 'jobs', 'personal']) else
        1 if any(k in x for k in ['info', 'kontakt', 'leitung']) else 2
    ))
    return sorted_emails[0]

# --- API Endpoints ---

async def handle_scan(request):
    try:
        data = await request.json()
        query = data.get('query', 'Pflegedienst')
        city = data.get('city', 'Köln')
        country = data.get('country', 'Deutschland')
        radius = data.get('radius', '')
        print(f"[*] API Scan: '{query}' in '{city}', '{country}' (radius: '{radius}')")
        places = await search_google_maps(query, city, country, radius, max_scrolls=6)
        print(f"[+] Total Google Maps places found: {len(places)}")
        return JSONResponse({'places': places, 'count': len(places)})
    except Exception as e:
        print("[-] API Scan Error:", e)
        return JSONResponse({'error': str(e), 'places': []}, status_code=500)

async def handle_extract(request):
    try:
        data = await request.json()
        places = data.get('places', [])
        limit = int(data.get('limit', len(places)))
        target_places = places[:limit]
        
        print(f"[*] Extracting emails for {len(target_places)} places...")
        loop = asyncio.get_event_loop()
        for idx, p in enumerate(target_places):
            site = p.get('website', '')
            email = await loop.run_in_executor(None, scrape_email_from_website_sync, site)
            p['email'] = email
            print(f"[{idx+1}/{len(target_places)}] {p['name']} -> {email}")
            
        return JSONResponse({'places': target_places})
    except Exception as e:
        print("[-] API Extract Error:", e)
        return JSONResponse({'error': str(e), 'places': []}, status_code=500)

async def handle_export(request):
    try:
        data = await request.json()
        places = data.get('places', [])
        city = data.get('city', 'Pflege')
        
        rows = []
        for p in places:
            rows.append({
                'اسم المنشأة': p.get('name', ''),
                'البريد الإلكتروني (E-Mail)': p.get('email', ''),
                'رقم الهاتف (Telefon)': p.get('phone', ''),
                'الموقع الإلكتروني (Website)': p.get('website', ''),
                'العنوان (Adresse)': p.get('address', '')
            })
            
        df = pd.DataFrame(rows)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Pflege_Bewerbungen')
        output.seek(0)
        
        headers = {
            'Content-Disposition': f'attachment; filename="Bewerbung_Pflege_{city}.xlsx"'
        }
        return Response(
            content=output.getvalue(),
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers=headers
        )
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

async def handle_home(request):
    html_file = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    return HTMLResponse(content)

async def handle_manifest(request):
    manifest_file = os.path.join(os.path.dirname(__file__), 'manifest.json')
    if os.path.exists(manifest_file):
        with open(manifest_file, 'r', encoding='utf-8') as f:
            content = f.read()
        return Response(content, media_type='application/manifest+json')
    return Response("{}", media_type='application/json')

routes = [
    Route('/', handle_home, methods=['GET']),
    Route('/manifest.json', handle_manifest, methods=['GET']),
    Route('/api/scan', handle_scan, methods=['POST']),
    Route('/api/extract', handle_extract, methods=['POST']),
    Route('/api/export', handle_export, methods=['POST']),
]

middleware = [
    Middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
]

app = Starlette(routes=routes, middleware=middleware)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    print(f"\n🚀 الخادم يعمل على المنفذ: {port}")
    uvicorn.run(app, host='0.0.0.0', port=port)



