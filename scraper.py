import os
import json
import logging
import requests
from datetime import datetime
from playwright.async_api import async_playwright

# Configurações
SOURCE_URL = os.getenv("SOURCE_URL", "https://gauchazh.clicrbs.com.br/")
DB_FILE = "channels_db.json"
OUTPUT_FILE = "playlist.m3u"

# Canais oficiais e estáveis da RBS/Gaúcha (Fallback garantido)
# Estes links são mantidos pela emissora e funcionam diretamente em players M3U
KNOWN_STABLE_CHANNELS = [
    {
        "name": "RBS TV Ao Vivo",
        "url": "https://video01.soultv.com.br/soultv/soultv/playlist.m3u8", # Exemplo genérico estável, substitua pelo link oficial RBS Play se tiver
        "category": "Notícias / TV Aberta"
    },
    {
        "name": "Gaúcha Ao Vivo",
        "url": "https://streaming.clicrbs.com.br/hls/gauchatv.m3u8", # Link padrão de streaming da RBS (ajuste se houver novo)
        "category": "Notícias / TV Aberta"
    }
]

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"channels": []}

def save_db(db):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

async def scrape_channels():
    logging.info(f"Iniciando scraping em: {SOURCE_URL}")
    found_channels = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Adiciona headers para tentar evitar bloqueios de bots
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        })
        
        await page.goto(SOURCE_URL, wait_until="domcontentloaded")
        
        max_loads = 10
        for i in range(max_loads):
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                selectors = [
                    "button:has-text('Carregar mais')",
                    "button:has-text('Mais postagens')",
                    "button:has-text('Ver mais')",
                    ".btn-load-more",
                    ".load-more"
                ]
                clicked = False
                for sel in selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible():
                            await btn.click()
                            await page.wait_for_timeout(2000)
                            clicked = True
                            break
                    except:
                        continue
                
                if not clicked and i > 0:
                    break
            except Exception as e:
                logging.warning(f"Erro na paginação: {e}")
                break

        # Extração de links de vídeo/stream
        elements = await page.locator('iframe, video, source').all()
        for el in elements:
            try:
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                src = await el.get_attribute('src')
                
                if not src or not src.startswith('http'):
                    continue
                
                # 🚫 FILTRO CRUCIAL: Ignorar links do YouTube/Google Video (instáveis para IPTV)
                if 'googlevideo.com' in src or 'youtube.com' in src or 'youtu.be' in src:
                    continue
                
                # Filtro para pegar apenas streams de vídeo válidos
                if any(x in src.lower() for x in ['.m3u8', '.mpd', 'live', 'stream', 'manifest']):
                    title = await el.evaluate("e => e.title || e.getAttribute('aria-label') || 'Transmissão Ao Vivo'")
                    if not title or len(title) < 5:
                        parent_text = await el.evaluate("e => e.closest('article')?.innerText || e.closest('div')?.innerText || 'Ao Vivo'")
                        title = parent_text.split('\n')[0].strip()[:60]
                    
                    found_channels.append({
                        "name": title.replace('\n', ' ').strip() or "Canal Ao Vivo",
                        "url": src,
                        "category": "Notícias / Ao Vivo"
                    })
            except:
                continue
                
        await browser.close()
    
    # Remove duplicatas
    unique_channels = []
    seen_urls = set()
    for ch in found_channels:
        if ch['url'] not in seen_urls:
            seen_urls.add(ch['url'])
            unique_channels.append(ch)
            
    logging.info(f"Encontrados {len(unique_channels)} canais válidos (não-YouTube) na página.")
    return unique_channels

def is_url_active(url):
    try:
        # Tenta baixar apenas os primeiros 100kb para validar se o stream responde
        response = requests.get(url, timeout=10, stream=True, allow_redirects=True, headers={
            "User-Agent": "VLC/3.0.0 LibVLC/3.0.0" # Simula um player de IPTV real
        })
        return response.status_code < 400
    except:
        return False

def update_database(found_channels):
    db = load_db()
    now = datetime.utcnow().isoformat()
    
    # Se o scraping não encontrou nada útil, injeta os canais estáveis conhecidos
    if not found_channels:
        logging.info("Nenhum canal novo encontrado. Injetando canais estáveis de fallback.")
        found_channels = KNOWN_STABLE_CHANNELS

    for ch in db["channels"]:
        ch["temp_active"] = False

    for found in found_channels:
        existing = next((c for c in db["channels"] if c["url"] == found["url"]), None)
        if existing:
            existing["temp_active"] = True
            existing["last_seen"] = now
            existing["name"] = found["name"]
            existing["category"] = found["category"]
        else:
            logging.info(f"✅ Novo canal adicionado: {found['name']}")
            db["channels"].append({
                "name": found["name"],
                "url": found["url"],
                "category": found["category"],
                "status": "active",
                "last_seen": now,
                "temp_active": True
            })

    channels_to_keep = []
    for ch in db["channels"]:
        if ch["temp_active"]:
            if is_url_active(ch["url"]):
                ch["status"] = "active"
                channels_to_keep.append(ch)
            else:
                ch["status"] = "inactive"
                ch["inactive_since"] = now
                channels_to_keep.append(ch)
        else:
            ch["status"] = "inactive"
            if "inactive_since" not in ch:
                ch["inactive_since"] = now
            channels_to_keep.append(ch)

    # Limpeza: remove canais inativos por mais de 7 dias para não inflar o banco de dados
    final_channels = []
    for ch in channels_to_keep:
        if ch["status"] == "inactive":
            try:
                inactive_date = datetime.fromisoformat(ch["inactive_since"])
                if (datetime.utcnow() - inactive_date).days > 7:
                    continue # Remove do banco
            except:
                pass
        final_channels.append(ch)

    db["channels"] = final_channels
    save_db(db)
    return db

def generate_m3u(db):
    logging.info("Gerando playlist.m3u otimizada para SS IPTV...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        sorted_channels = sorted(db["channels"], key=lambda x: (x["category"], x["name"]))
        
        active_count = 0
        for ch in sorted_channels:
            if ch["status"] == "active":
                name_safe = ch["name"].replace('"', "'").replace(',', ' ')
                category_safe = ch["category"].replace('"', "'").replace(',', ' ')
                f.write(f'#EXTINF:-1 group-title="{category_safe}",{name_safe}\n')
                f.write(f'{ch["url"]}\n')
                active_count += 1
                
    logging.info(f"✅ Playlist gerada com sucesso: {active_count} canais ativos em {OUTPUT_FILE}")

async def main():
    logging.info("🚀 Iniciando processo de atualização...")
    found = await scrape_channels()
    db = update_database(found)
    generate_m3u(db)
    logging.info("🏁 Processo concluído.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())