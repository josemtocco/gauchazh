import os
import json
import logging
import re
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
    logging.info(f"Iniciando varredura profunda em: {SOURCE_URL}")
    found_channels = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Aguarda a rede ficar ociosa para garantir que todos os scripts carregaram
        await page.goto(SOURCE_URL, wait_until="networkidle")
        
        max_loads = 10
        for i in range(max_loads):
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

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
                    logging.info("Fim da paginação (nenhum botão de carregar mais encontrado).")
                    break
            except Exception as e:
                logging.warning(f"Erro na paginação: {e}")
                break

        # Extrai TODO o HTML da página após carregar tudo
        html_content = await page.content()
        await browser.close()

    # Regex robusto para encontrar URLs de streaming no meio do código JavaScript/HTML
    url_pattern = re.compile(r'(https?://[^\s\"\'<>]+(?:\.m3u8|\.mpd|manifest)[^\s\"\'<>]*)', re.IGNORECASE)
    matches = url_pattern.findall(html_content)
    
    for url in matches:
        # Limpeza básica da URL
        url = url.rstrip('",\'\\')
        
        # Mantemos o filtro de YouTube/GoogleVideo pois esses links expiram em minutos e são inúteis para IPTV
        if 'googlevideo.com' in url or 'youtube.com' in url or 'youtu.be' in url:
            continue 
            
        found_channels.append({
            "name": f"Stream Extraído ({len(found_channels)+1})",
            "url": url,
            "category": "Extraído do Site"
        })

    # Remove duplicatas
    unique_channels = []
    seen_urls = set()
    for ch in found_channels:
        if ch['url'] not in seen_urls:
            seen_urls.add(ch['url'])
            unique_channels.append(ch)
            
    logging.info(f"Encontrados {len(unique_channels)} links de stream únicos no código da página.")
    return unique_channels

def update_database(found_channels):
    db = load_db()
    now = datetime.utcnow().isoformat()

    if not found_channels:
        logging.warning("⚠️ NENHUM link de stream (.m3u8/.mpd) foi encontrado no site.")
        logging.warning("⚠️ LEMBRETE: gauchazh.clicrbs.com.br é um portal de notícias, não um diretório de IPTV.")
        logging.warning("💡 DICA: Altere a variável SOURCE_URL nas configurações do repositório para um site que realmente liste canais.")

    for ch in db["channels"]:
        ch["temp_active"] = False

    for found in found_channels:
        existing = next((c for c in db["channels"] if c["url"] == found["url"]), None)
        if existing:
            existing["temp_active"] = True
            existing["last_seen"] = now
        else:
            logging.info(f"✅ Novo link adicionado: {found['url']}")
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
            ch["status"] = "active"
            channels_to_keep.append(ch)
        else:
            # Mantém canais não encontrados hoje como inativos, mas não os deleta
            ch["status"] = "inactive"
            channels_to_keep.append(ch)

    db["channels"] = channels_to_keep
    save_db(db)
    return db

def generate_m3u(db):
    logging.info("Gerando playlist.m3u...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        sorted_channels = sorted(db["channels"], key=lambda x: (x["category"], x["name"]))
        
        total_count = 0
        for ch in sorted_channels:
            # Inclui todos os canais encontrados para teste manual no SS IPTV
            name_safe = ch["name"].replace('"', "'").replace(',', ' ')
            category_safe = ch["category"].replace('"', "'").replace(',', ' ')
            status_tag = " [OFF]" if ch["status"] == "inactive" else ""
            
            f.write(f'#EXTINF:-1 group-title="{category_safe}",{name_safe}{status_tag}\n')
            f.write(f'{ch["url"]}\n')
            total_count += 1
                
    logging.info(f"✅ Playlist gerada com sucesso: {total_count} itens em {OUTPUT_FILE}")

async def main():
    logging.info("🚀 Iniciando processo de atualização...")
    found = await scrape_channels()
    db = update_database(found)
    generate_m3u(db)
    logging.info("🏁 Processo concluído.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())