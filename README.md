# Convest · Monitor de ETFs & Setores

Sistema **gratuito** de monitoramento de preço, volume e momentum do universo UCITS/ETFs,
com histórico próprio e atualização diária automática. Dados EOD (fim de dia) do
**Yahoo Finance** — sem custo, com delay mínimo de 1 dia útil. Não requer o EODHD pago.

O painel segue a identidade da **Convest** (azul-marinho `#243548`, dourado `#BEB081`).

---

## O que o sistema entrega

- **Aba "Resumo do dia"**: rotação setorial (mais fortes/fracos em 3m), cruzamentos de médias
  MM50×MM200 (golden/death), destaques da semana (maiores altas e quedas), fluxo anômalo
  (top-10 picos de volume) e um **heatmap do dia** — os 15 maiores ETFs de cada setor em tiles
  coloridos pela variação do fechamento (escala −3% a +3%, com legenda).
- **Aba "Ativos"**: tabela filtrável e ordenável com todo o universo de ETFs.
- **Abas "Setores", "Regiões" e "Classes de Ativo"**: agregados de desempenho, com colunas ordenáveis.
- **Modal de detalhes** (clique em qualquer ativo/ticker): preço e retornos, um **mini-gráfico de
  preço de 12 meses**, tendência/técnicos (MM50/200, cruzamento, RSI, momentum), risco e liquidez,
  ficha do fundo (ISIN, TER, patrimônio, domicílio, distribuição, réplica) e a **composição top-10
  posições + alocação setorial**.
- **Sinais de momentum por ativo**: retornos 1s/1m/3m/6m/YTD/1a, MM50/MM200 e cruzamentos,
  RSI(14), volatilidade anualizada, tendência de volume (vs média 20d), distância da máxima de
  52 semanas e percentil de força relativa.
- **Histórico próprio** (`data/prices.csv.gz`): preços acumulados a cada rodada — a base cresce sozinha.
- **Atualização automática** todo dia útil (dados) e semanal (composição) via GitHub Actions,
  sem depender do seu computador ligado.

---

## Arquitetura

```
convest-etf-monitor/
├── data/
│   ├── universe.csv         # os ~3.461 ETFs (extraídos do seu HTML do JustETF)
│   ├── symbol_map.csv        # ISIN -> símbolo Yahoo (gerado, cache incremental)
│   └── prices.csv.gz         # histórico de preços (gerado, cresce a cada dia)
├── scripts/
│   ├── requirements.txt
│   ├── indicators.py         # cálculo dos indicadores + detecção de série defasada
│   ├── resolve_symbols.py    # mapeia ISIN/ticker -> símbolo do Yahoo (com validação)
│   ├── update_data.py        # pipeline diário -> latest.json + sparklines.json
│   ├── fetch_holdings.py     # composição (top-10 + setores) -> holdings.json (semanal)
│   └── make_preview.py       # gera o PREVIEW.html offline a partir do dashboard atual
├── docs/
│   ├── index.html            # o dashboard (servido pelo GitHub Pages)
│   └── data/
│       ├── latest.json       # dados do painel (gerado, diário)
│       ├── sparklines.json   # séries de preço 12m p/ o gráfico do modal (gerado, diário)
│       └── holdings.json     # composição dos ETFs p/ o modal (gerado, semanal)
├── PREVIEW.html              # prévia offline (amostra) — abre com duplo-clique
└── .github/workflows/
    ├── update.yml            # agenda diária (dados + indicadores + sparklines)
    └── holdings.yml          # agenda semanal (composição dos ETFs)
```

Fluxo diário: `resolve_symbols.py` descobre o símbolo Yahoo de cada ISIN (Xetra `.DE` como padrão,
com fallback de outras bolsas e busca por ISIN, rejeitando séries defasadas) → `update_data.py`
baixa os preços, exclui séries "mortas", calcula os indicadores e grava `latest.json` +
`sparklines.json` + atualiza o histórico → o dashboard lê esses arquivos.
Fluxo semanal: `fetch_holdings.py` coleta a composição de cada ETF e grava `holdings.json`,
carregado sob demanda pelo modal de detalhes.

---

## Setup na nuvem — 100% gratuito (recomendado)

Requer uma conta no GitHub (grátis). Tempo estimado: ~10 minutos.

1. **Crie um repositório** no GitHub (pode ser privado) e suba esta pasta.
   Pelo terminal, dentro de `convest-etf-monitor/`:
   ```bash
   git init
   git add .
   git commit -m "Monitor de ETFs Convest"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/convest-etf-monitor.git
   git push -u origin main
   ```
   *(Se preferir sem terminal: no GitHub, "Add file → Upload files" e arraste a pasta.)*

2. **Ative o GitHub Pages**: repositório → **Settings → Pages** →
   em *Source* selecione **Deploy from a branch**, *Branch* = `main`, pasta = **/docs** → Save.
   Em ~1 minuto o painel fica no ar em `https://SEU_USUARIO.github.io/convest-etf-monitor/`.

3. **Ative os Actions**: aba **Actions** → habilite os workflows.
   Em **Settings → Actions → General → Workflow permissions**, marque
   **Read and write permissions** (para o bot poder salvar os dados).

4. **Primeira carga**: aba **Actions → "Atualizar dados dos ETFs" → Run workflow**.
   A primeira execução resolve os símbolos e baixa 2 anos de histórico (pode levar ~20–40 min).
   Depois disso, roda sozinho todo dia útil às ~03:30 (horário de Brasília).

5. **Composição** (opcional, mas recomendado): aba **Actions → "Atualizar composição dos ETFs" →
   Run workflow**. Popula o `holdings.json` (top-10 posições + setores). Roda sozinho toda semana.
   Enquanto não rodar, o modal mostra tudo, menos a parte de composição.

Pronto. O painel se atualiza sozinho e o histórico se acumula no próprio repositório.

---

## Uso local (opcional, para testar ou rodar manualmente)

```bash
cd convest-etf-monitor
pip install -r scripts/requirements.txt

# 1) resolver os símbolos (rode uma vez; é incremental/retomável)
python scripts/resolve_symbols.py            # ou: python scripts/resolve_symbols.py 100  (limite p/ teste)

# 2) baixar dados e gerar o painel (gera latest.json + sparklines.json)
python scripts/update_data.py                 # ou: python scripts/update_data.py 100

# 3) (opcional) coletar a composição dos ETFs (gera holdings.json)
python scripts/fetch_holdings.py              # ou: python scripts/fetch_holdings.py 100

# 4) abrir o dashboard
python -m http.server -d docs 8000            # acesse http://localhost:8000
```

> Observação: abrir `docs/index.html` direto pelo `file://` não carrega os dados
> por restrição de segurança do navegador. Use o servidor local acima (ou o GitHub Pages).
> Para uma espiada rápida sem servidor, abra o **`PREVIEW.html`** (duplo-clique): é uma
> versão autocontida com uma amostra de dados embutida. Para regerá-lo com a versão mais
> recente do painel e dos dados, rode `python scripts/make_preview.py`.

---

## Notas técnicas e limitações

- **Fonte gratuita**: o Yahoo Finance cobre a grande maioria dos ETFs listados na Xetra e nas
  principais bolsas europeias. Fundos cuja série vem "defasada" (preço travado, sem histórico real)
  são detectados, excluídos do painel e re-resolvidos automaticamente em outra bolsa na próxima
  rodada; os sem cobertura em lugar nenhum ficam como `no_data` em `symbol_map.csv`.
- **Composição**: puxada do Yahoo (`funds_data`). Disponível para a maioria dos ETFs de ações;
  comum não existir para renda fixa — nesses casos o modal mostra "composição indisponível".
- **Delay**: dados de fim de dia (EOD). O último dado disponível é sempre o do pregão anterior — atende ao requisito de "no mínimo 1 dia de delay".
- **Custo**: zero. GitHub Actions (2.000 min/mês grátis em repositório privado; ilimitado em público)
  e GitHub Pages são gratuitos. Nenhuma API paga é usada.
- **Ajuste da janela de histórico**: a variável de ambiente `HISTORY_PERIOD` (padrão `2y`) controla
  quanto se baixa por rodada. O histórico persistido cresce além disso a cada execução.
- **Uso**: ferramenta de monitoramento e apoio à decisão. Não constitui recomendação de compra/venda.
