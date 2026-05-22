# Design: Buscador de Imóveis de Leilão + Calculadora

**Data:** 2026-05-22  
**Projeto:** leilao-imoveis  
**Status:** Aprovado

---

## Objetivo

Ferramenta automatizada que busca diariamente apartamentos de leilão na Caixa Econômica Federal para São Carlos - SP com valor até R$ 120.000, publica os resultados em uma página web estática via GitHub Pages, e permite calcular a viabilidade financeira de cada imóvel diretamente na página.

---

## Arquitetura Geral

```
GitHub Actions (cron: todo dia 8h BRT)
        │
        ▼
  scraper.py
  ├── POST para API interna da Caixa
  │     municipio=São Carlos, UF=SP
  │     tipo_imovel=Apartamento
  │     modalidade=qualquer leilão
  │     valor_maximo=120000
  │
  ├── Extrai: endereço, valor, área, modalidade, foto, link
  │
  └── Gera resultado.html (página com cards + calculadora)
        │
        ▼
  git commit resultado.html
        │
        ▼
  GitHub Pages → URL fixa pública
  https://<usuario>.github.io/leilao-imoveis/
```

---

## Estrutura de Arquivos

```
leilao-imoveis/
├── scraper.py                    # script principal
├── requirements.txt              # requests, beautifulsoup4
├── resultado.html                # gerado automaticamente
└── .github/
    └── workflows/
        └── busca-diaria.yml      # cron job GitHub Actions
```

---

## Componente 1: scraper.py

### Fonte de dados
Requisição HTTP direta à API interna da Caixa (sem cookies de consentimento):

```
POST https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_c.asp
```

Parâmetros de filtro:
- `municipio` = São Carlos
- `UF` = SP
- `tipo_imovel` = Apartamento
- `tipo_oferta` = todos os tipos de leilão
- `valor_ate` = 120000

### Dados extraídos por imóvel
- Endereço completo
- Valor de arrematação (R$)
- Área útil (m²)
- Modalidade (1º Leilão, 2º Leilão, etc.)
- URL da foto (se disponível)
- Link direto para a página do imóvel na Caixa

### Comportamento
- Se não encontrar imóveis: exibe mensagem informativa na página
- Se a API falhar: commit não é feito, página anterior permanece

---

## Componente 2: resultado.html

Página HTML estática gerada pelo scraper a cada execução.

### Cabeçalho
- Data e hora da última atualização
- Total de imóveis encontrados
- Filtros aplicados (São Carlos - SP | Apartamento | até R$ 120.000)

### Cards de imóveis
Um card por imóvel encontrado:

```
┌──────────────────────────────────────────┐
│ [Foto]   Rua X, 123 - Bairro, São Carlos │
│          R$ 85.000 | 52 m²               │
│          Modalidade: 2º Leilão           │
│          [Ver na Caixa →] [Calcular ▶]   │
└──────────────────────────────────────────┘
```

### Calculadora (modal por card)
Ao clicar em "Calcular", abre um painel/modal com o valor de arrematação pré-preenchido. O usuário preenche os demais campos e o resultado é calculado no navegador (JavaScript puro, sem servidor).

---

## Componente 3: Calculadora financeira

Baseada nas planilhas do curso "Vivendo de Leilão" (Priscila Perini).

### Modo: Pagamento à Vista

**Entradas:**
| Campo | Default | Observação |
|---|---|---|
| Valor da Arrematação | pré-preenchido | vem do card |
| Valor de Venda estimado | — | usuário preenche |
| Comissão do Leiloeiro | 5% | editável |
| ITBI | — | editável (verificar alíquota de São Carlos) |
| Registro | — | valor fixo |
| Advogado (desocupação) | — | opcional |
| Reforma | — | |
| Outros | — | |
| Prazo de Venda (meses) | — | |
| IPTU Mensal | — | |
| Condomínio Mensal | — | |
| Comissão do Corretor | 6% | editável |
| IR Ganho de Capital | 15% | fixo por lei |

**Saídas:**
- Total de Custos (R$)
- Valor Real de Venda (descontado corretor e IR)
- **Lucro (R$) e % sobre o investimento**
- Indicador visual: verde (lucro) / vermelho (prejuízo)

### Modo: Financiado (PRICE ou SAC)

Campos adicionais:
| Campo | Observação |
|---|---|
| % de Entrada | ex: 20% |
| % Financiado | automático (1 - entrada) |
| Taxa de Juros Anual | ex: 8,99% |
| Prazo do Financiamento (meses) | máx 420 |
| Tabela | PRICE ou SAC |

Cálculo do saldo devedor no prazo de venda usando PRICE (prestação fixa) ou SAC (amortização constante).

**Saídas adicionais:**
- Total a pagar do financiamento até a venda
- Saldo devedor no momento da venda
- Valor Real de Venda (abatido corretor, IR, saldo devedor)
- **Lucro (R$) e %**

---

## Componente 4: GitHub Actions (busca-diaria.yml)

```yaml
schedule:
  - cron: '0 11 * * *'   # 8h BRT = 11h UTC

steps:
  - Checkout do repositório
  - Setup Python 3.11
  - pip install requirements.txt
  - python scraper.py
  - git config + git add resultado.html
  - git commit (somente se houve mudança)
  - git push
```

GitHub Pages serve o `resultado.html` automaticamente via branch `main`.

---

## Configuração única (feita uma vez pelo usuário)

1. Criar repositório `leilao-imoveis` no GitHub
2. Ativar GitHub Pages → Source: branch `main`, pasta `/` (root)
3. Em Settings → Actions → General: marcar "Allow GitHub Actions to create and approve pull requests" + permissão de escrita
4. Pronto — link fica em `https://<usuario>.github.io/leilao-imoveis/`

---

## Tecnologias

| Componente | Tecnologia |
|---|---|
| Linguagem | Python 3.11 |
| Scraping | `requests` + `BeautifulSoup4` |
| Calculadora | JavaScript puro (sem dependências) |
| Agendamento | GitHub Actions (cron) |
| Saída | HTML estático com CSS inline |
| Publicação | GitHub Pages |
| Custo | R$ 0,00 |

---

## Fora de escopo

- Notificações por e-mail/WhatsApp/Telegram
- Banco de dados ou histórico de preços
- Outros municípios ou tipos de imóvel (extensível depois)
- App mobile
