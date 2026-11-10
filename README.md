# Gerador de Playlist M3U para SS IPTV

Este projeto automatiza a coleta, validação e geração de uma lista M3U otimizada para o **SS IPTV**.

## 🔄 Funcionalidades
- **Atualização Automática**: Executa a cada 6 horas via GitHub Actions.
- **Gestão Inteligente de Estado**: 
  - ✅ Adiciona novos canais encontrados.
  - ✅ Mantém canais ativos.
  - ❌ Marca como inativos e remove da playlist final canais que pararam de responder.
- **Otimizado para SS IPTV**: Usa a tag `group-title` para separação por categorias.
- **Navegação Dinâmica**: Utiliza Playwright para rolar a página e clicar em botões "Carregar mais" ou "Mais postagens".

## ⚠️ Nota sobre a Fonte
A URL padrão (`gauchazh.clicrbs.com.br`) é um portal de notícias. O script buscará por players de vídeo ao vivo incorporados (ex: RBS TV). Para usar com diretórios reais de IPTV, altere a variável `SOURCE_URL` nas configurações do repositório.

## 🚀 Como Usar
1. Faça um **Fork** ou crie um novo repositório com estes arquivos.
2. Vá em **Settings > Actions > General** e certifique-se de que "Read and write permissions" estão habilitadas para os workflows.
3. (Opcional) Vá em **Settings > Secrets and variables > Actions** e crie um novo segredo:
   - Nome: `SOURCE_URL`
   - Valor: `https://site-desejado.com/canais`
4. Vá na aba **Actions**, selecione "Atualizar Playlist M3U" e clique em **Run workflow** para testar manualmente.
5. Após a execução, o arquivo `playlist.m3u` será gerado/atualizado na raiz do repositório. Use o "Raw link" desse arquivo no seu SS IPTV.