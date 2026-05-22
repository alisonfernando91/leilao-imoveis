"""
scraper.py — Fetch and parse Caixa property listings for São Carlos, SP.

2-step AJAX flow:
  Step 1: POST carregaPesquisaImoveis.asp  → property ID groups + pagination info
  Step 2: POST carregaListaImoveis.asp     → HTML with property cards
"""

import re
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
    resp = session.post(STEP1_URL, data=STEP1_PARAMS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    total_pages_tag = soup.find("input", {"name": "hdnQtdPag"})
    total_count_tag = soup.find("input", {"name": "hdnQtdRegistros"})
    if total_pages_tag:
        log.info("Total pages: %s", total_pages_tag.get("value", "?"))
    if total_count_tag:
        log.info("Total records: %s", total_count_tag.get("value", "?"))

    id_groups: list[str] = []
    page = 1
    while True:
        tag = soup.find("input", {"name": f"hdnImov{page}"})
        if tag is None:
            break
        value = tag.get("value", "").strip()
        if value:
            id_groups.append(value)
        page += 1

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
    resp = session.post(STEP2_URL, data={"hdnImov": ids_str}, timeout=30)
    resp.raise_for_status()
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
    id_groups = fetch_property_ids(session)

    all_props: list[dict] = []
    for i, ids_str in enumerate(id_groups, start=1):
        log.info("Fetching group %d/%d …", i, len(id_groups))
        html = fetch_property_html(session, ids_str)
        props = parse_properties(html)
        log.info("  → %d properties parsed.", len(props))
        all_props.extend(props)

    before = len(all_props)
    filtered = [p for p in all_props if p["valor"] <= PRICE_LIMIT]
    log.info(
        "Total fetched: %d | After price filter (<=R$%.0f): %d",
        before,
        PRICE_LIMIT,
        len(filtered),
    )
    return filtered


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
            # Modality: <b> tag before fotoimovel-col1 (e.g. <b>Venda Online</b>)
            modality_b_tag = ul_tag.select_one("b")
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
