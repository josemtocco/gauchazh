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
        await page.goto(SOURCE_URL, wait_until="domcontentloaded")
        
        max_loads = 15 # Limite de segurança para evitar loops infinitos
        for i in range(max_loads):
            try:
                # 1. Tenta rolar a página (para sites com scroll infinito)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                # 2. Tenta clicar em botões de "Carregar mais"
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
                    logging.info("Nenhum botão de 'carregar mais' encontrado. Fim da paginação.")
                    break
            except Exception as e:
                logging.warning(f"Erro na paginação: {e}")
                break

        # Extração de links de vídeo/stream
        elements = await page.locator('iframe, video, a').all()
        for el in elements:
            try:
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                src = None
                
                if tag == 'iframe':
                    src = await el.get_attribute('src')
                elif tag == 'video':
                    src = await el.get_attribute('src')
                else:
                    href = await el.get_attribute('href')
                    if href and any(x in href.lower() for x in ['m3u8', 'live', 'stream', 'player']):
                        src = href
                
                if src and src.startswith('http'):
                    # Tenta obter um título significativo
                    title = await el.evaluate("e => e.title || e.getAttribute('aria-label') || ''")
                    if not title:
                        parent_text = await el.evaluate("e => e.closest('article')?.innerText || e.closest('div')?.innerText || 'Transmissão Ao Vivo'")
                        title = parent_text.split('\n')[0].strip()[:60]
                    
                    # Tenta inferir categoria (ajuste conforme o HTML real do site)
                    category = "Notícias / Ao Vivo" 
                    
                    found_channels.append({
                        "name": title.replace('\n', ' ').strip() or "Canal Ao Vivo",
                        "url": src,
                        "category": category
                    })
            except:
                continue
                
        await browser.close()
    
    # Remove duplicatas da mesma execução
    unique_channels = []
    seen_urls = set()
    for ch in found_channels:
        if ch['url'] not in seen_urls:
            seen_urls.add(ch['url'])
            unique_channels.append(ch)
            
    logging.info(f"Encontrados {len(unique_channels)} canais únicos na página.")
    return unique_channels

def is_url_active(url):
    try:
        # Usa GET com stream=True para ser mais compatível que HEAD com servidores de streaming
        response = requests.get(url, timeout=8, stream=True, allow_redirects=True)
        return response.status_code < 400
    except:
        return False

def update_database(found_channels):
    db = load_db()
    now = datetime.utcnow().isoformat()
    
    # Marca todos como inativos temporariamente para comparação
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
                channels_to_keep.append(ch) # Mantém no DB para histórico
        else:
            ch["status"] = "inactive"
            if "inactive_since" not in ch:
                ch["inactive_since"] = now
            channels_to_keep.append(ch)

    db["channels"] = channels_to_keep
    save_db(db)
    return db

def generate_m3u(db):
    logging.info("Gerando playlist.m3u otimizada para SS IPTV...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        
        # Ordena por categoria e depois por nome
        sorted_channels = sorted(db["channels"], key=lambda x: (x["category"], x["name"]))
        
        for ch in sorted_channels:
            if ch["status"] == "active":
                # Formatação segura para evitar quebras no SS IPTV
                name_safe = ch["name"].replace('"', "'").replace(',', ' ')
                category_safe = ch["category"].replace('"', "'").replace(',', ' ')
                f.write(f'#EXTINF:-1 group-title="{category_safe}",{name_safe}\n')
                f.write(f'{ch["url"]}\n')
                
    logging.info(f"✅ Playlist gerada com sucesso: {OUTPUT_FILE}")

async def main():
    logging.info("🚀 Iniciando processo de atualização...")
    found = await scrape_channels()
    db = update_database(found)
    generate_m3u(db)
    logging.info("🏁 Processo concluído.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())