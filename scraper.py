"""
scraper.py — Fetch and parse Caixa property listings for São Carlos, SP.

2-step AJAX flow:
  Step 1: POST carregaPesquisaImoveis.asp  → property ID groups + pagination info
  Step 2: POST carregaListaImoveis.asp     → HTML with property cards
"""

import re
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://venda-imoveis.caixa.gov.br"
MAIN_PAGE = f"{BASE_URL}/sistema/busca-imovel.asp?sltEstado=SP"
STEP1_URL = f"{BASE_URL}/sistema/carregaPesquisaImoveis.asp"
STEP2_URL = f"{BASE_URL}/sistema/carregaListaImoveis.asp"

STEP1_PARAMS = {
    "hdn_estado": "SP",
    "hdn_cidade": "9834",          # São Carlos
    "hdn_bairro": "",
    "hdn_tp_venda": "Selecione",   # all modalities
    "hdn_tp_imovel": "2",          # Apartamento
    "hdn_area_util": "",
    "hdn_faixa_vlr": "2",          # up to ~R$200k (we filter to <=120k in Python)
    "hdn_quartos": "",
    "hdn_vg_garagem": "",
    "strValorSimulador": "",
    "strAceitaFGTS": "",
    "strAceitaFinanciamento": "",
}

PRICE_LIMIT = 120_000.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": BASE_URL,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_session() -> requests.Session:
    """Create a requests.Session with the ASP session cookie from the main page."""
    session = requests.Session()
    session.headers.update(HEADERS)
    log.info("Loading main page to obtain ASP session cookie …")
    resp = session.get(MAIN_PAGE, timeout=30)
    resp.raise_for_status()
    asp_cookies = [k for k in session.cookies.keys() if k.startswith("ASPSESSION")]
    if asp_cookies:
        log.info("ASP session cookie obtained: %s", asp_cookies[0])
    else:
        log.warning("No ASPSESSIONID cookie found — requests may fail.")
    return session


def fetch_property_ids(session: requests.Session) -> list[str]:
    """
    POST Step 1: retrieve property ID group strings.

    Returns a list where each element is a '||'-separated string of property IDs,
    one element per page of results.
    """
    log.info("Step 1: fetching property ID groups from Caixa …")
    resp = None
    for attempt in range(1, 4):
        try:
            resp = session.post(STEP1_URL, data=STEP1_PARAMS, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            log.warning("Step 1 attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(2)
            else:
                raise

    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    total_pages_tag = soup.find("input", {"name": "hdnQtdPag"})
    total_count_tag = soup.find("input", {"name": "hdnQtdRegistros"})

    max_pages = 50  # safety cap when hdnQtdPag is absent
    if total_pages_tag:
        log.info("Total pages: %s", total_pages_tag.get("value", "?"))
        try:
            max_pages = int(total_pages_tag.get("value", 50))
        except (ValueError, TypeError):
            pass
    if total_count_tag:
        log.info("Total records: %s", total_count_tag.get("value", "?"))

    id_groups: list[str] = []
    for page in range(1, max_pages + 1):
        tag = soup.find("input", {"name": f"hdnImov{page}"})
        if tag is None:
            break
        value = tag.get("value", "").strip()
        if value:
            id_groups.append(value)

    log.info("Found %d ID group(s).", len(id_groups))
    return id_groups


def fetch_property_html(session: requests.Session, ids_str: str) -> str:
    """
    POST Step 2: fetch the HTML listing for a group of property IDs.

    Args:
        ids_str: '||'-separated property IDs, e.g. '08555537594011||08444425715079'

    Returns:
        Raw HTML string.
    """
    resp = None
    for attempt in range(1, 4):
        try:
            resp = session.post(STEP2_URL, data={"hdnImov": ids_str}, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            log.warning("Step 2 attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(2)
            else:
                raise

    resp.encoding = resp.apparent_encoding
    return resp.text


def parse_valor(valor_str: str) -> float:
    """
    Convert a Brazilian-formatted currency string to a float.

    Examples:
        'R$ 85.000,00'  → 85000.0
        '120.000,00'    → 120000.0
        ''              → 0.0
        'N/D'           → 0.0
    """
    if not valor_str:
        return 0.0
    # Strip 'R$' and whitespace
    cleaned = valor_str.replace("R$", "").strip()
    # Remove thousands separator (period) and replace decimal comma with dot
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_properties(html: str) -> list[dict]:
    """
    Parse the HTML returned by Step 2 and return a list of property dicts.

    Each dict has keys: endereco, valor, area, modalidade, foto, link.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for ul in soup.find_all("ul", class_="control-group"):
        prop = _parse_single_property(ul)
        if prop:
            results.append(prop)

    return results


def fetch_all_properties() -> list[dict]:
    """
    Orchestrate the full 2-step fetch and return properties with valor <= 120 000.

    1. Obtain ASP session cookie.
    2. Fetch all property ID groups (Step 1).
    3. For each group, fetch property HTML (Step 2) and parse.
    4. Filter to valor <= PRICE_LIMIT.
    """
    session = get_session()
    try:
        id_groups = fetch_property_ids(session)

        all_props: list[dict] = []
        for i, ids_str in enumerate(id_groups, start=1):
            log.info("Fetching group %d/%d …", i, len(id_groups))
            html = fetch_property_html(session, ids_str)
            props = parse_properties(html)
            log.info("  → %d properties parsed.", len(props))
            all_props.extend(props)
    finally:
        session.close()

    before = len(all_props)
    filtered = [p for p in all_props if p["valor"] > 0.0 and p["valor"] <= PRICE_LIMIT]
    log.info(
        "Total fetched: %d | After price filter (0 < valor <= R$%.0f): %d",
        before,
        PRICE_LIMIT,
        len(filtered),
    )
    return filtered


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

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

function pmtPrice(pv, nMeses, i) {
  if (nMeses <= 0 || i <= 0) return 0;
  return pv * i * Math.pow(1 + i, nMeses) / (Math.pow(1 + i, nMeses) - 1);
}

function saldoPrice(pv, k, nMeses, i) {
  if (nMeses <= 0 || i <= 0) return pv;
  const pmt = pmtPrice(pv, nMeses, i);
  return pv * Math.pow(1 + i, k) - pmt * (Math.pow(1 + i, k) - 1) / i;
}

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

  const ganhoBruto      = venda - totalCustos - saldoDevedor;
  const ir              = Math.max(0, ganhoBruto * 0.15);
  const comissaoCorretor = venda * pctCorretor;
  const valorRealVenda  = venda - comissaoCorretor - ir - saldoDevedor;
  const lucroReais      = valorRealVenda - totalCustos;
  const base            = modoAtual === 'avista' ? totalCustos : (totalCustos + saldoDevedor);
  const lucroPercent    = base > 0 ? lucroReais / base : 0;

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


def fmt_valor(valor: float) -> str:
    """85000.0 -> 'R$ 85.000'"""
    return f"R$ {valor:,.0f}".replace(",", ".")


def generate_card(prop: dict) -> str:
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


def generate_html(properties: list, timestamp: str) -> str:
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_single_property(ul_tag) -> Optional[dict]:
    """Extract property data from a single <ul class='control-group'> element.

    The Caixa website has two layout variants:

    Variant A (Leilão):
      - Modality in  div.fotoimovel-col1 > div > span > strong
      - Price in     div.dadosimovel-col2 font (first font, contains '|')
      - Details in   div.dadosimovel-col2 font (second font, line 0 = specs, line 3 = address)

    Variant B (Venda Online / Compra Direta):
      - Modality in  div before div.fotoimovel-col1, inside a <b> tag
      - Price in     div.dadosimovel-col2 via <b>Valor mínimo de venda: R$ …</b>
      - Details in   div.dadosimovel-col2 font (last font, line 0 = specs, line 2 = address)
    """
    try:
        ul_html = str(ul_tag)

        # --- property ID (from any onclick on the page) ---
        property_id = ""
        pid_match = re.search(r"detalhe_imovel\((\d+)\)", ul_html)
        if pid_match:
            property_id = pid_match.group(1)

        # --- photo ---
        img_tag = ul_tag.select_one("img.fotoimovel")
        foto = ""
        if img_tag:
            src = img_tag.get("src", "")
            if src:
                foto = src if src.startswith("http") else f"{BASE_URL}{src}"

        col2 = ul_tag.select_one("div.dadosimovel-col2")
        if col2 is None:
            return None

        fonts = col2.find_all("font")

        # --- detect variant ---
        # Variant A: first font text contains " | R$ " (city | price on same font)
        is_variant_a = len(fonts) >= 1 and "|" in fonts[0].get_text()

        if is_variant_a:
            # Modality: strong inside fotoimovel-col1
            modality_tag = ul_tag.select_one("div.fotoimovel-col1 strong")
            modalidade = modality_tag.get_text(strip=True) if modality_tag else ""

            # Price: first font text — "SAO CARLOS - BAIRRO | R$ 160.000,00"
            first_font_text = fonts[0].get_text(separator=" ", strip=True)
            valor_match = re.search(r"R\$\s*[\d.,]+", first_font_text)
            valor = parse_valor(valor_match.group(0) if valor_match else "")

            # Details: second font with br-separated lines
            area = ""
            endereco = ""
            if len(fonts) >= 2:
                parts = _split_by_br(fonts[1])
                # Line 0: "Apartamento - 88,01 m2, 2 quarto(s), …"
                if parts:
                    area_match = re.search(r"([\d,.]+ m2)", parts[0])
                    area = area_match.group(1).replace("m2", "m²") if area_match else ""
                # Line 3: full street address (Número do imóvel is line 1, item is line 2)
                if len(parts) >= 4:
                    endereco = parts[3].strip()
                elif len(parts) >= 2:
                    for line in reversed(parts):
                        if line.strip():
                            endereco = line.strip()
                            break

        else:
            # Variant B: Venda Online / Compra Direta
            # Modality: <b> or <strong> inside div.fotoimovel-col1
            modality_b_tag = ul_tag.select_one("div.fotoimovel-col1 b") or ul_tag.select_one("div.fotoimovel-col1 strong")
            modalidade = modality_b_tag.get_text(strip=True) if modality_b_tag else ""

            # Price: bold tag inside col2 — "Valor mínimo de venda: R$ 113.025,32"
            bold_tags = col2.find_all("b")
            valor = 0.0
            for b in bold_tags:
                b_text = b.get_text(strip=True)
                if "mínimo" in b_text or "minimo" in b_text.lower():
                    v_match = re.search(r"R\$\s*[\d.,]+", b_text)
                    if v_match:
                        valor = parse_valor(v_match.group(0))
                        break
            # Fallback: search all font text for R$
            if valor == 0.0:
                for font in fonts:
                    v_match = re.search(r"R\$\s*[\d.,]+", font.get_text())
                    if v_match:
                        valor = parse_valor(v_match.group(0))
                        break

            # Details: last font with br-separated lines
            area = ""
            endereco = ""
            if fonts:
                detail_font = fonts[-1]
                parts = _split_by_br(detail_font)
                # Line 0: "Apartamento - 88,01 m2, 2 quarto(s), …"
                if parts:
                    area_match = re.search(r"([\d,.]+ m2)", parts[0])
                    area = area_match.group(1).replace("m2", "m²") if area_match else ""
                # Variant B has: line 0 = specs, line 1 = Número do imóvel, line 2 = address
                if len(parts) >= 3:
                    endereco = parts[2].strip()
                elif len(parts) >= 2:
                    for line in reversed(parts):
                        if line.strip():
                            endereco = line.strip()
                            break

        # --- link ---
        if property_id:
            link = f"{BASE_URL}/sistema/detalhe-imovel.asp?hdnimovel={property_id}"
        else:
            link = f"{BASE_URL}/sistema/busca-imovel.asp?sltEstado=SP"

        return {
            "endereco": endereco,
            "valor": valor,
            "area": area,
            "modalidade": modalidade,
            "foto": foto,
            "link": link,
        }

    except Exception as exc:
        log.warning("Failed to parse a property entry: %s", exc)
        return None


def _split_by_br(tag) -> list[str]:
    """Return a list of text segments split at <br> tags within a BeautifulSoup tag."""
    segments: list[str] = []
    current: list[str] = []
    for child in tag.children:
        if hasattr(child, "name") and child.name == "br":
            segments.append("".join(current).strip())
            current = []
        else:
            text = child.get_text() if hasattr(child, "get_text") else str(child)
            current.append(text)
    if current:
        segments.append("".join(current).strip())
    return segments
