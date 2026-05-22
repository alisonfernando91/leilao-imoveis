# Leilão Imóveis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Script Python que busca diariamente apartamentos de leilão na Caixa para São Carlos-SP (até R$120k), gera uma página HTML com cards dos imóveis e calculadora financeira embutida, publicada automaticamente via GitHub Pages.

**Architecture:** `scraper.py` faz POST à API da Caixa, parseia HTML com BeautifulSoup, gera `resultado.html` com CSS e JavaScript inline. GitHub Actions executa o scraper num cron diário às 8h BRT, faz commit do HTML atualizado, e o GitHub Pages serve o arquivo em URL fixa.

**Tech Stack:** Python 3.11, requests, beautifulsoup4, JavaScript puro, HTML/CSS inline, GitHub Actions, GitHub Pages

---

## Mapa de Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `scraper.py` | fetch API Caixa + parse resposta + gera resultado.html |
| `requirements.txt` | dependências Python |
| `tests/test_scraper.py` | testes unitários |
| `.github/workflows/busca-diaria.yml` | cron job GitHub Actions |
| `resultado.html` | saída gerada automaticamente (não editar manualmente) |
| `.gitignore` | ignora arquivos temporários |

---

## Task 1: Setup do projeto

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `tests/__init__.py`

- [ ] **Step 1: Criar requirements.txt**

```
requests==2.31.0
beautifulsoup4==4.12.3
pytest==8.2.0
```

- [ ] **Step 2: Criar .gitignore**

```
__pycache__/
*.pyc
.env
venv/
.venv/
```

- [ ] **Step 3: Criar tests/__init__.py (arquivo vazio)**

Criar arquivo vazio em `tests/__init__.py`.

- [ ] **Step 4: Instalar dependências**

```bash
pip install -r requirements.txt
```

Expected: instalação sem erros.

- [ ] **Step 5: Inicializar git e fazer primeiro commit**

```bash
git init
git add requirements.txt .gitignore tests/__init__.py
git commit -m "feat: setup inicial do projeto"
```

---

## Task 2: Descoberta dos parâmetros reais da API da Caixa

**Files:**
- Create (temporário): `discover_api.py`

O site da Caixa usa um formulário HTML clássico. Precisamos inspecionar os nomes reais dos campos antes de implementar o scraper, pois eles mudam sem aviso.

- [ ] **Step 1: Criar discover_api.py**

```python
import requests
from bs4 import BeautifulSoup

URL = "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp?sltTipoBusca=imoveis"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

resp = requests.get(URL, headers=HEADERS, timeout=30)
resp.encoding = 'utf-8'
soup = BeautifulSoup(resp.text, 'html.parser')

print("=== FORM ===")
form = soup.find('form')
if form:
    print(f"action : {form.get('action')}")
    print(f"method : {form.get('method')}")

print("\n=== TODOS OS CAMPOS ===")
for tag in soup.find_all(['input', 'select', 'textarea']):
    name = tag.get('name', '-')
    kind = tag.get('type', tag.name)
    val  = tag.get('value', '')
    print(f"  {kind:12s}  name={name:35s}  value={val}")

print("\n=== OPTIONS DOS SELECTS ===")
for sel in soup.find_all('select'):
    print(f"\n  SELECT name={sel.get('name')}")
    for opt in sel.find_all('option'):
        print(f"    value={opt.get('value',''):15s}  text={opt.text.strip()}")
```

- [ ] **Step 2: Executar e anotar os parâmetros reais**

```bash
python discover_api.py
```

Anotar obrigatoriamente:
1. O valor de `action` do form (endpoint real do POST)
2. Nome do campo de estado e valor para "SP"
3. Nome do campo de cidade/município e valor para "São Carlos"
4. Nome do campo de tipo de imóvel e valor para "Apartamento"
5. Nome do campo de tipo de oferta (leilão) — se vazio = todos
6. Nome do campo de valor máximo

Esses valores serão usados em `build_params()` na Task 3.

- [ ] **Step 3: Deletar discover_api.py**

```bash
del discover_api.py
```

- [ ] **Step 4: Commit registrando os parâmetros no message**

```bash
git commit --allow-empty -m "chore: parâmetros API Caixa — action=[X] estado=[X] cidade=[X] tipo=[X] valorMax=[X]"
```

Substituir os `[X]` pelos valores reais encontrados.

---

## Task 3: Scraper core — fetch e parse

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Criar tests/test_scraper.py com os testes**

```python
import sys
sys.path.insert(0, '.')
from scraper import build_params, parse_valor, parse_properties


def test_build_params_estado_sp():
    p = build_params()
    assert any(v == 'SP' for v in p.values()), "Faltou UF=SP"


def test_build_params_valor_max():
    p = build_params()
    assert any('120000' in str(v) for v in p.values()), "Faltou valor_max=120000"


def test_parse_valor_formato_brasileiro():
    assert parse_valor('R$ 85.000,00') == 85000.0


def test_parse_valor_sem_rs():
    assert parse_valor('120.000,00') == 120000.0


def test_parse_valor_string_vazia():
    assert parse_valor('') == 0.0


def test_parse_valor_invalido():
    assert parse_valor('N/D') == 0.0


def test_parse_properties_html_vazio_retorna_lista_vazia():
    assert parse_properties('<html><body></body></html>') == []


def test_parse_properties_retorna_lista():
    result = parse_properties('<html><body></body></html>')
    assert isinstance(result, list)
```

- [ ] **Step 2: Rodar testes para confirmar que falham (módulo não existe)**

```bash
pytest tests/test_scraper.py -v
```

Expected: `ModuleNotFoundError` ou todos FAIL.

- [ ] **Step 3: Criar scraper.py com build_params, parse_valor, parse_properties**

> **ATENÇÃO:** Substituir os nomes dos campos (`sltEstado`, `sltCidade`, etc.) e a URL do POST pelos valores reais descobertos na Task 2. Os placeholders abaixo são os mais comuns no site da Caixa — podem ou não estar corretos.

```python
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Substituir pela URL real do POST (form action descoberto na Task 2)
CAIXA_API_URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_c.asp"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp",
}


def build_params():
    # AJUSTAR com os nomes e valores reais descobertos na Task 2
    return {
        "sltEstado": "SP",
        "sltCidade": "São Carlos",   # verificar nome exato do campo e valor
        "sltTipoImovel": "AP",        # verificar valor para Apartamento
        "sltTipoOferta": "",          # vazio = todos os tipos de leilão
        "sltValorMin": "",
        "sltValorMax": "120000",
        "hdnComanda": "Lista",
        "hdnTipoBusca": "imoveis",
    }


def parse_valor(valor_str):
    """Converte 'R$ 85.000,00' -> 85000.0"""
    cleaned = (
        str(valor_str)
        .replace("R$", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_properties(html):
    """
    Extrai lista de imóveis do HTML retornado pela API.

    IMPORTANTE: Os seletores CSS abaixo são placeholders.
    Após a primeira execução real (Task 3, Step 6), inspecionar o HTML
    retornado e ajustar os seletores para corresponder à estrutura real.
    """
    soup = BeautifulSoup(html, "html.parser")
    properties = []

    # Ajustar este seletor conforme estrutura real do HTML da Caixa
    items = soup.select(".item-imovel, tr.imovel, .resultado-imovel")

    for item in items:
        endereco_tag = item.select_one(
            ".endereco-imovel, .descricao, td[data-label='Endereço']"
        )
        valor_tag = item.select_one(
            ".valor-imovel, .preco, td[data-label='Valor']"
        )
        area_tag = item.select_one(".area-imovel, td[data-label='Área']")
        modalidade_tag = item.select_one(
            ".modalidade, td[data-label='Modalidade']"
        )
        img_tag = item.select_one("img")
        link_tag = item.select_one("a[href]")

        properties.append({
            "endereco": endereco_tag.get_text(strip=True) if endereco_tag else "",
            "valor": parse_valor(valor_tag.get_text() if valor_tag else "0"),
            "area": area_tag.get_text(strip=True) if area_tag else "",
            "modalidade": modalidade_tag.get_text(strip=True) if modalidade_tag else "",
            "foto": img_tag["src"] if img_tag and img_tag.get("src") else "",
            "link": link_tag["href"] if link_tag else "#",
        })

    return properties


def fetch_properties():
    params = build_params()
    response = requests.post(CAIXA_API_URL, data=params, headers=HEADERS, timeout=30)
    response.encoding = "utf-8"
    response.raise_for_status()
    return response.text
```

- [ ] **Step 4: Rodar testes para confirmar que passam**

```bash
pytest tests/test_scraper.py -v
```

Expected: todos PASS (exceto testes que dependem de estrutura HTML real — esses passam porque `parse_properties` com HTML vazio retorna `[]`).

- [ ] **Step 5: Testar fetch_properties manualmente (requer internet)**

```bash
python -c "
from scraper import fetch_properties
html = fetch_properties()
print('Chars recebidos:', len(html))
print(html[:3000])
"
```

Expected: HTML com lista de imóveis ou mensagem de "nenhum encontrado".

- [ ] **Step 6: Ajustar seletores CSS e URL conforme HTML real**

Inspecionar o HTML retornado no Step 5. Identificar:
- O seletor dos containers de imóveis (ex: `table tr`, `.resultado`, etc.)
- Os seletores de endereço, valor, área, modalidade, foto, link

Atualizar `parse_properties()` com os seletores corretos. Testar:

```bash
python -c "
from scraper import fetch_properties, parse_properties
html = fetch_properties()
props = parse_properties(html)
print(f'{len(props)} imóveis encontrados')
for p in props[:3]:
    print(p)
"
```

Expected: lista com dicts populados (não todos vazios).

- [ ] **Step 7: Commit**

```bash
git add scraper.py tests/test_scraper.py
git commit -m "feat: scraper core — fetch e parse da API Caixa"
```

---

## Task 4: Gerador HTML — CSS, JavaScript e cards

**Files:**
- Modify: `scraper.py` (adicionar CSS, JS, generate_card, generate_html)
- Modify: `tests/test_scraper.py` (adicionar testes de generate_html)

- [ ] **Step 1: Adicionar testes de generate_html em tests/test_scraper.py**

Adicionar ao final do arquivo:

```python
from scraper import generate_html


def test_generate_html_contem_timestamp():
    html = generate_html([], "22/05/2026 às 08:00")
    assert "22/05/2026" in html


def test_generate_html_sem_imoveis_mostra_aviso():
    html = generate_html([], "22/05/2026 às 08:00")
    assert "nenhum" in html.lower() or "encontrado" in html.lower()


def test_generate_html_com_imovel_mostra_card():
    props = [{
        "endereco": "Rua Exemplo, 123 - Centro",
        "valor": 85000.0,
        "area": "52 m²",
        "modalidade": "2º Leilão",
        "foto": "",
        "link": "https://example.com",
    }]
    html = generate_html(props, "22/05/2026 às 08:00")
    assert "Rua Exemplo, 123" in html
    assert "85.000" in html
    assert "2º Leilão" in html
    assert "https://example.com" in html


def test_generate_html_mostra_contagem():
    props = [
        {"endereco": "A", "valor": 80000, "area": "40", "modalidade": "1º Leilão", "foto": "", "link": "#"},
        {"endereco": "B", "valor": 90000, "area": "50", "modalidade": "2º Leilão", "foto": "", "link": "#"},
    ]
    html = generate_html(props, "22/05/2026 às 08:00")
    assert "2" in html
```

- [ ] **Step 2: Rodar novos testes para confirmar que falham**

```bash
pytest tests/test_scraper.py::test_generate_html_contem_timestamp -v
```

Expected: `ImportError` (generate_html não existe ainda).

- [ ] **Step 3: Adicionar CSS e JS como constantes no scraper.py**

Adicionar logo após os imports, antes de `CAIXA_API_URL`:

```python
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, sans-serif; background: #f4f4f4; color: #333; }
header { background: #003087; color: white; padding: 20px; text-align: center; }
header h1 { font-size: 1.4rem; }
.meta { font-size: 0.85rem; opacity: 0.85; margin-top: 6px; }
main { max-width: 960px; margin: 24px auto; padding: 0 16px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.card { background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); overflow: hidden; }
.card-foto { width: 100%; height: 160px; object-fit: cover; display: block; }
.card-foto-vazia { width: 100%; height: 160px; background: #ddd; display: flex; align-items: center; justify-content: center; color: #888; font-size: 0.85rem; }
.card-info { padding: 12px; }
.card-endereco { font-size: 0.9rem; margin-bottom: 6px; }
.card-valor { font-size: 1.25rem; font-weight: bold; color: #003087; margin-bottom: 4px; }
.card-detalhes { font-size: 0.8rem; color: #666; margin-bottom: 12px; }
.card-actions { display: flex; gap: 8px; }
.btn-ver, .btn-calcular { flex: 1; padding: 8px; border-radius: 4px; font-size: 0.85rem; text-align: center; cursor: pointer; border: none; }
.btn-ver { background: #003087; color: white; text-decoration: none; display: block; }
.btn-calcular { background: #f0a500; color: #333; font-weight: bold; }
.btn-ver:hover { background: #00256b; }
.btn-calcular:hover { background: #d4920a; }
.sem-imoveis { text-align: center; padding: 40px; color: #666; font-size: 1rem; }
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 100; overflow-y: auto; padding: 20px; }
.modal-overlay.ativo { display: flex; align-items: flex-start; justify-content: center; }
.modal { background: white; border-radius: 8px; padding: 24px; width: 100%; max-width: 560px; margin: auto; }
.modal h2 { font-size: 1.1rem; margin-bottom: 16px; color: #003087; }
.modal-tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tab-btn { flex: 1; padding: 8px; border: 2px solid #003087; background: white; color: #003087; border-radius: 4px; cursor: pointer; font-weight: bold; }
.tab-btn.ativo { background: #003087; color: white; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 0.8rem; color: #555; margin-bottom: 4px; }
.form-group input, .form-group select { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.resultado { margin-top: 16px; padding: 16px; border-radius: 6px; background: #f9f9f9; border: 2px solid #ddd; }
.resultado.lucro { background: #e8f5e9; border-color: #4caf50; }
.resultado.prejuizo { background: #ffebee; border-color: #f44336; }
.resultado h3 { font-size: 0.95rem; margin-bottom: 8px; }
.resultado-linha { display: flex; justify-content: space-between; font-size: 0.85rem; padding: 3px 0; }
.resultado-destaque { font-size: 1.1rem; font-weight: bold; margin-top: 8px; padding-top: 8px; border-top: 1px solid #ccc; }
.btn-fechar { float: right; background: none; border: none; font-size: 1.2rem; cursor: pointer; color: #666; }
"""

JS = """
let modoAtual = 'avista';

function setTab(modo, btn) {
  modoAtual = modo;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('ativo'));
  btn.classList.add('ativo');
  document.getElementById('campos-financiado').style.display = modo === 'financiado' ? 'block' : 'none';
  calcular();
}

function abrirCalculadora(valorArrematacao) {
  document.getElementById('f-arrematacao').value = valorArrematacao;
  document.getElementById('modal-overlay').classList.add('ativo');
  calcular();
}

function fecharCalculadora() {
  document.getElementById('modal-overlay').classList.remove('ativo');
}

function fecharSeOverlay(e) {
  if (e.target === document.getElementById('modal-overlay')) fecharCalculadora();
}

function n(id) { return parseFloat(document.getElementById(id).value) || 0; }

function fmtBRL(v) {
  return 'R$ ' + Math.abs(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function fmtPct(v) { return (v * 100).toFixed(2) + '%'; }

/* PRICE: retorna prestação mensal fixa */
function pmtPrice(pv, nMeses, i) {
  if (nMeses <= 0 || i <= 0) return 0;
  return pv * i * Math.pow(1 + i, nMeses) / (Math.pow(1 + i, nMeses) - 1);
}

/* PRICE: saldo devedor após k pagamentos */
function saldoPrice(pv, k, nMeses, i) {
  if (nMeses <= 0 || i <= 0) return pv;
  const pmt = pmtPrice(pv, nMeses, i);
  return pv * Math.pow(1 + i, k) - pmt * (Math.pow(1 + i, k) - 1) / i;
}

/* SAC: total pago e saldo devedor após k meses */
function calcSAC(pv, k, nMeses, i) {
  if (nMeses <= 0) return { totalPago: 0, saldo: pv };
  const amort = pv / nMeses;
  let saldo = pv, totalPago = 0;
  for (let m = 1; m <= k; m++) {
    totalPago += amort + saldo * i;
    saldo -= amort;
  }
  return { totalPago, saldo: Math.max(0, saldo) };
}

function calcular() {
  const arr        = n('f-arrematacao');
  const venda      = n('f-venda');
  const prazo      = n('f-prazo');
  const pctCorretor = n('f-corretor') / 100;

  const comissaoLeiloeiro = arr * (n('f-leiloeiro') / 100);
  const itbi              = arr * (n('f-itbi') / 100);
  const registro          = n('f-registro');
  const advogado          = n('f-advogado');
  const reforma           = n('f-reforma');
  const outros            = n('f-outros');
  const iptuTotal         = n('f-iptu') * prazo;
  const condTotal         = n('f-cond') * prazo;

  let totalCustos, saldoDevedor = 0, totalPagoFin = 0, entrada = 0;

  if (modoAtual === 'avista') {
    totalCustos = arr + comissaoLeiloeiro + itbi + registro + advogado + reforma + outros + iptuTotal + condTotal;

  } else {
    entrada          = arr * (n('f-entrada') / 100);
    const financiado = arr - entrada;
    const i          = Math.pow(1 + n('f-taxa') / 100, 1 / 12) - 1;
    const nFin       = n('f-prazo-fin');
    const tabela     = document.getElementById('f-tabela').value;

    if (tabela === 'PRICE') {
      const pmt    = pmtPrice(financiado, nFin, i);
      totalPagoFin = pmt * prazo;
      saldoDevedor = saldoPrice(financiado, prazo, nFin, i);
    } else {
      const sac    = calcSAC(financiado, prazo, nFin, i);
      totalPagoFin = sac.totalPago;
      saldoDevedor = sac.saldo;
    }

    totalCustos = entrada + comissaoLeiloeiro + itbi + registro + advogado + reforma + outros + iptuTotal + condTotal + totalPagoFin;
  }

  /* Ganho bruto = Venda - tudo que foi gasto - o que ainda se deve */
  const ganhoBruto     = venda - totalCustos - saldoDevedor;
  const ir             = Math.max(0, ganhoBruto * 0.15);
  const comissaoCorretor = venda * pctCorretor;
  const valorRealVenda = venda - comissaoCorretor - ir - saldoDevedor;
  const lucroReais     = valorRealVenda - totalCustos;
  const base           = modoAtual === 'avista' ? totalCustos : (totalCustos + saldoDevedor);
  const lucroPercent   = base > 0 ? lucroReais / base : 0;

  const div = document.getElementById('resultado');
  div.style.display = 'block';
  div.className = 'resultado ' + (lucroReais >= 0 ? 'lucro' : 'prejuizo');

  let linhas = `
    <div class="resultado-linha"><span>Total de Custos</span><span>${fmtBRL(totalCustos)}</span></div>
    <div class="resultado-linha"><span>Comissão Corretor</span><span>${fmtBRL(comissaoCorretor)}</span></div>
    <div class="resultado-linha"><span>IR Ganho de Capital (15%)</span><span>${fmtBRL(ir)}</span></div>`;

  if (modoAtual === 'financiado') {
    linhas += `
    <div class="resultado-linha"><span>Entrada paga</span><span>${fmtBRL(entrada)}</span></div>
    <div class="resultado-linha"><span>Pago no financ. até a venda</span><span>${fmtBRL(totalPagoFin)}</span></div>
    <div class="resultado-linha"><span>Saldo devedor na venda</span><span>${fmtBRL(saldoDevedor)}</span></div>`;
  }

  linhas += `
    <div class="resultado-linha"><span>Valor Real de Venda</span><span>${fmtBRL(valorRealVenda)}</span></div>
    <div class="resultado-destaque resultado-linha">
      <span>Lucro ${lucroReais >= 0 ? '✅' : '❌'}</span>
      <span>${fmtBRL(lucroReais)} (${fmtPct(lucroPercent)})</span>
    </div>`;

  div.innerHTML = '<h3>Resultado</h3>' + linhas;
}
"""
```

- [ ] **Step 4: Adicionar fmt_valor, generate_card e generate_html ao scraper.py**

Adicionar após `fetch_properties()`:

```python
def fmt_valor(valor):
    """85000.0 -> 'R$ 85.000'"""
    return f"R$ {valor:,.0f}".replace(",", ".")


def generate_card(prop):
    foto_html = (
        f'<img src="{prop["foto"]}" alt="Foto do imóvel" class="card-foto">'
        if prop["foto"]
        else '<div class="card-foto-vazia">Sem foto</div>'
    )
    return f"""
    <div class="card">
      <div class="card-foto-wrap">{foto_html}</div>
      <div class="card-info">
        <p class="card-endereco">{prop["endereco"]}</p>
        <p class="card-valor">{fmt_valor(prop["valor"])}</p>
        <p class="card-detalhes">{prop["area"]} &nbsp;|&nbsp; {prop["modalidade"]}</p>
        <div class="card-actions">
          <a href="{prop["link"]}" target="_blank" class="btn-ver">Ver na Caixa →</a>
          <button class="btn-calcular" onclick="abrirCalculadora({prop['valor']:.2f})">Calcular ▶</button>
        </div>
      </div>
    </div>"""


def generate_html(properties, timestamp):
    total = len(properties)
    cards_html = (
        "".join(generate_card(p) for p in properties)
        if properties
        else '<p class="sem-imoveis">Nenhum apartamento encontrado em São Carlos abaixo de R$ 120.000.</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Leilão Imóveis — São Carlos</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <h1>Apartamentos de Leilão — São Carlos - SP</h1>
    <p class="meta">Atualizado em {timestamp} &nbsp;|&nbsp; {total} imóvel(is) encontrado(s) &nbsp;|&nbsp; Até R$ 120.000</p>
  </header>
  <main>
    <div class="cards">{cards_html}</div>
  </main>

  <div class="modal-overlay" id="modal-overlay" onclick="fecharSeOverlay(event)">
    <div class="modal">
      <button class="btn-fechar" onclick="fecharCalculadora()">✕</button>
      <h2>Calculadora de Viabilidade</h2>
      <div class="modal-tabs">
        <button class="tab-btn ativo" onclick="setTab('avista', this)">À Vista</button>
        <button class="tab-btn" onclick="setTab('financiado', this)">Financiado</button>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>Valor da Arrematação (R$)</label>
          <input type="number" id="f-arrematacao" value="0" oninput="calcular()">
        </div>
        <div class="form-group">
          <label>Valor de Venda Estimado (R$)</label>
          <input type="number" id="f-venda" value="0" oninput="calcular()">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Comissão Leiloeiro (%)</label>
          <input type="number" id="f-leiloeiro" value="5" step="0.1" oninput="calcular()">
        </div>
        <div class="form-group">
          <label>ITBI (%)</label>
          <input type="number" id="f-itbi" value="2" step="0.1" oninput="calcular()">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Registro (R$)</label>
          <input type="number" id="f-registro" value="0" oninput="calcular()">
        </div>
        <div class="form-group">
          <label>Advogado Desocupação (R$)</label>
          <input type="number" id="f-advogado" value="0" oninput="calcular()">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Reforma (R$)</label>
          <input type="number" id="f-reforma" value="0" oninput="calcular()">
        </div>
        <div class="form-group">
          <label>Outros (R$)</label>
          <input type="number" id="f-outros" value="0" oninput="calcular()">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Prazo até Venda (meses)</label>
          <input type="number" id="f-prazo" value="0" oninput="calcular()">
        </div>
        <div class="form-group">
          <label>IPTU Mensal (R$)</label>
          <input type="number" id="f-iptu" value="0" oninput="calcular()">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Condomínio Mensal (R$)</label>
          <input type="number" id="f-cond" value="0" oninput="calcular()">
        </div>
        <div class="form-group">
          <label>Comissão Corretor (%)</label>
          <input type="number" id="f-corretor" value="6" step="0.1" oninput="calcular()">
        </div>
      </div>

      <div id="campos-financiado" style="display:none">
        <hr style="margin:12px 0;border-color:#eee">
        <p style="font-size:0.8rem;color:#555;margin-bottom:8px;">Estrutura do Financiamento</p>
        <div class="form-row">
          <div class="form-group">
            <label>% de Entrada</label>
            <input type="number" id="f-entrada" value="20" step="1" oninput="calcular()">
          </div>
          <div class="form-group">
            <label>Taxa de Juros Anual (%)</label>
            <input type="number" id="f-taxa" value="8.99" step="0.01" oninput="calcular()">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Prazo do Financiamento (meses, máx 420)</label>
            <input type="number" id="f-prazo-fin" value="240" max="420" oninput="calcular()">
          </div>
          <div class="form-group">
            <label>Tabela de Amortização</label>
            <select id="f-tabela" onchange="calcular()">
              <option value="PRICE">PRICE (parcela fixa)</option>
              <option value="SAC">SAC (amortização constante)</option>
            </select>
          </div>
        </div>
      </div>

      <div class="resultado" id="resultado" style="display:none"></div>
    </div>
  </div>

  <script>{JS}</script>
</body>
</html>"""
```

- [ ] **Step 5: Rodar todos os testes**

```bash
pytest tests/test_scraper.py -v
```

Expected: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add scraper.py tests/test_scraper.py
git commit -m "feat: HTML generator com cards e calculadora PRICE/SAC"
```

---

## Task 5: Função main e escrita do arquivo

**Files:**
- Modify: `scraper.py` (adicionar main())

- [ ] **Step 1: Adicionar main() ao final de scraper.py**

```python
def main():
    timestamp = datetime.now().strftime("%d/%m/%Y às %H:%M")
    try:
        html_response = fetch_properties()
        properties = parse_properties(html_response)
        print(f"[OK] {len(properties)} imóvel(is) encontrado(s)")
    except Exception as e:
        print(f"[ERRO] Falha ao buscar imóveis: {e}")
        raise  # re-raise: GitHub Actions registra falha e não faz commit

    html_output = generate_html(properties, timestamp)
    with open("resultado.html", "w", encoding="utf-8") as f:
        f.write(html_output)
    print("[OK] resultado.html gerado")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Testar execução local completa**

```bash
python scraper.py
```

Expected:
```
[OK] X imóvel(is) encontrado(s)
[OK] resultado.html gerado
```

- [ ] **Step 3: Abrir resultado.html no browser e verificar**

Abrir o arquivo gerado localmente. Verificar:
- Cards aparecem com endereço, valor e modalidade
- Botão "Ver na Caixa →" abre o link correto em nova aba
- Botão "Calcular ▶" abre o modal com o valor pré-preenchido
- Calculadora mostra resultado em tempo real ao digitar
- Modo "Financiado" revela campos extras de financiamento
- Resultado fica verde (lucro) ou vermelho (prejuízo) conforme os valores

- [ ] **Step 4: Commit**

```bash
git add scraper.py resultado.html
git commit -m "feat: main() completo — pipeline fetch → parse → HTML"
```

---

## Task 6: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/busca-diaria.yml`

- [ ] **Step 1: Criar diretório**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Criar .github/workflows/busca-diaria.yml**

```yaml
name: Busca Diária de Imóveis

on:
  schedule:
    - cron: '0 11 * * *'   # 8h BRT = 11h UTC
  workflow_dispatch:         # permite rodar manualmente pelo GitHub

permissions:
  contents: write

jobs:
  buscar:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Instalar dependências
        run: pip install -r requirements.txt

      - name: Executar scraper
        run: python scraper.py

      - name: Commit resultado.html
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add resultado.html
          git diff --staged --quiet || git commit -m "chore: atualização diária $(date +'%d/%m/%Y %H:%M')"
          git push
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/busca-diaria.yml
git commit -m "feat: GitHub Actions cron diário às 8h BRT"
```

---

## Task 7: Publicar no GitHub e ativar GitHub Pages

Esta task é executada manualmente pelo usuário no site do GitHub.

- [ ] **Step 1: Criar repositório no GitHub**

1. Acessar github.com → botão "+" → "New repository"
2. Nome: `leilao-imoveis`
3. Visibilidade: **Public** (obrigatório para GitHub Pages gratuito)
4. Não marcar nenhuma opção de inicialização (sem README, sem .gitignore)
5. Clicar em "Create repository"

- [ ] **Step 2: Fazer push do código local**

Executar no terminal, substituindo `SEU-USUARIO` pelo username do GitHub:

```bash
git remote add origin https://github.com/SEU-USUARIO/leilao-imoveis.git
git branch -M main
git push -u origin main
```

- [ ] **Step 3: Ativar GitHub Pages**

1. No repositório → aba **Settings** → seção **Pages** (menu lateral)
2. Em "Source": selecionar **"Deploy from a branch"**
3. Branch: `main` → pasta: `/ (root)`
4. Clicar em **Save**
5. Aguardar ~2 minutos — o link aparece na mesma página: `https://SEU-USUARIO.github.io/leilao-imoveis/`

- [ ] **Step 4: Testar o workflow manualmente**

1. No repositório → aba **Actions**
2. Clicar em "Busca Diária de Imóveis" (menu lateral)
3. Clicar em **"Run workflow"** → **"Run workflow"**
4. Aguardar ~1-2 minutos
5. Verificar ícone verde ✓ na execução

- [ ] **Step 5: Verificar o link público**

Abrir `https://SEU-USUARIO.github.io/leilao-imoveis/` no browser.
- Página carrega com os imóveis (ou mensagem de "nenhum encontrado")
- Calculadora funciona ao clicar em "Calcular ▶"
- Link "Ver na Caixa →" abre a página correta

---

## Notas de Implementação

### Fórmulas da calculadora (referência)

**À Vista:**
```
totalCustos     = arrematacao + comissaoLeiloeiro + itbi + registro + advogado
                  + reforma + outros + (iptu + cond) * prazoMeses
ganhoBruto      = venda - totalCustos
ir              = max(0, ganhoBruto * 0.15)
comissaoCorretor = venda * pctCorretor
valorRealVenda  = venda - comissaoCorretor - ir
lucroReais      = valorRealVenda - totalCustos
lucroPercent    = lucroReais / totalCustos
```

**Financiado (PRICE):**
```
i_mensal        = (1 + taxaAnual) ^ (1/12) - 1
pmt             = financiado * i * (1+i)^n / ((1+i)^n - 1)
totalPagoFin    = pmt * prazoVenda
saldoDevedor    = financiado*(1+i)^k - pmt*((1+i)^k - 1)/i
totalCustos     = entrada + custos + totalPagoFin
ganhoBruto      = venda - totalCustos - saldoDevedor
ir              = max(0, ganhoBruto * 0.15)
valorRealVenda  = venda - comissaoCorretor - ir - saldoDevedor
lucroPercent    = lucroReais / (totalCustos + saldoDevedor)
```

**Financiado (SAC):**
```
amort           = financiado / nMeses   (constante)
parcela_k       = amort + saldo_anterior * i_mensal
totalPagoFin    = soma das parcelas de 1 até prazoVenda
saldoDevedor    = financiado - prazoVenda * amort
```

### Ajuste de seletores CSS (Task 3, Step 6)

Se o HTML da Caixa usar uma tabela (`<table>`), os seletores seriam:
```python
items = soup.select("table.resultado tr[data-imovel], tbody tr")
endereco_tag = item.select_one("td:nth-child(2)")
```

Se usar divs com classes customizadas, inspecionar o HTML real e ajustar conforme necessário.
