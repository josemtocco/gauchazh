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
    logging.info(f"Iniciando varredura forçada em: {SOURCE_URL}")
    found_channels = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            # Usa domcontentloaded para evitar timeout com anúncios
            await page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60000)
            
            max_loads = 15
            for i in range(max_loads):
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)

                    selectors = [
                        "button:has-text('Carregar mais')",
                        "button:has-text('Mais postagens')",
                        "button:has-text('Ver mais')",
                        ".btn-load-more",
                        ".load-more",
                        "a.load-more"
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
                    
                    if not clicked and i > 2:
                        logging.info("Fim da paginação.")
                        break
                except Exception as e:
                    logging.warning(f"Erro na paginação (ignorado): {e}")
                    break

            # Extrai TODO o HTML da página
            html_content = await page.content()
            
        except Exception as e:
            logging.error(f"Falha ao carregar a página: {e}")
            html_content = ""
            
        finally:
            await browser.close()

    if not html_content:
        logging.warning("Não foi possível obter o conteúdo da página.")
        return []

    # REGEX AGRESSIVA: Busca especificamente por googlevideo.com ou links .m3u8
    # Isso garante que os links do YouTube Live sejam capturados
    url_pattern = re.compile(r'(https?://[^\s\"\'<>]+(?:googlevideo\.com|\.m3u8|manifest)[^\s\"\'<>]*)', re.IGNORECASE)
    matches = url_pattern.findall(html_content)
    
    for url in matches:
        # Limpeza da URL (remove aspas ou vírgulas sobrando no final)
        url = url.rstrip('",\'\\)')
        
        # Tenta encontrar um título próximo a esse link no HTML para nomear o canal
        # Procura o título da matéria mais próxima
        title = "Transmissão Ao Vivo"
        try:
            # Busca simplificada: pega o título da página ou tenta achar um <h1> ou <h2> próximo
            # Como o regex pega a string crua, usamos um nome genérico com timestamp para diferenciar
            title = f"GaúchaZH Live ({len(found_channels)+1})"
        except:
            pass
            
        found_channels.append({
            "name": title,
            "url": url,
            "category": "Extraído (Google Video / M3U8)"
        })

    # Remove duplicatas exatas de URL
    unique_channels = []
    seen_urls = set()
    for ch in found_channels:
        if ch['url'] not in seen_urls:
            seen_urls.add(ch['url'])
            unique_channels.append(ch)
            
    logging.info(f"🎯 Encontrados {len(unique_channels)} links de stream (incluindo Google Video).")
    return unique_channels

def update_database(found_channels):
    db = load_db()
    now = datetime.utcnow().isoformat()

    if not found_channels:
        logging.warning("⚠️ NENHUM link foi encontrado nesta varredura.")

    # Marca todos como inativos temporariamente
    for ch in db["channels"]:
        ch["temp_active"] = False

    # Atualiza ou adiciona os novos encontrados
    for found in found_channels:
        existing = next((c for c in db["channels"] if c["url"] == found["url"]), None)
        if existing:
            existing["temp_active"] = True
            existing["last_seen"] = now
        else:
            logging.info(f"✅ Novo link adicionado: {found['url'][:60]}...")
            db["channels"].append({
                "name": found["name"],
                "url": found["url"],
                "category": found["category"],
                "status": "active",
                "last_seen": now,
                "temp_active": True
            })

    # Separa os que devem ser mantidos
    channels_to_keep = []
    for ch in db["channels"]:
        if ch["temp_active"]:
            ch["status"] = "active"
            channels_to_keep.append(ch)
        else:
            # Se não foi encontrado hoje, marca como inativo, mas mantém no histórico
            ch["status"] = "inactive"
            channels_to_keep.append(ch)

    # Limpeza: remove canais inativos há mais de 2 dias para não lotar o arquivo
    final_channels = []
    for ch in channels_to_keep:
        if ch["status"] == "inactive":
            try:
                inactive_date = datetime.fromisoformat(ch.get("inactive_since", now))
                if (datetime.utcnow() - inactive_date).days > 2:
                    continue # Remove do banco
            except:
                pass
        final_channels.append(ch)

    db["channels"] = final_channels
    save_db(db)
    return db

def generate_m3u(db):
    logging.info("Gerando playlist.m3u...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        sorted_channels = sorted(db["channels"], key=lambda x: (x["category"], x["name"]))
        
        total_count = 0
        for ch in sorted_channels:
            # Gera a lista com TODOS os canais (ativos e inativos, para você testar)
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