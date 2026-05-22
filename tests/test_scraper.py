"""Unit tests for scraper.py — written before implementation (TDD)."""

import pytest
from scraper import parse_valor, parse_properties


def test_parse_valor_formato_brasileiro():
    assert parse_valor("R$ 85.000,00") == 85000.0


def test_parse_valor_sem_rs():
    assert parse_valor("120.000,00") == 120000.0


def test_parse_valor_string_vazia():
    assert parse_valor("") == 0.0


def test_parse_valor_invalido():
    assert parse_valor("N/D") == 0.0


def test_parse_properties_html_vazio_retorna_lista_vazia():
    assert parse_properties("<html><body></body></html>") == []


def test_parse_properties_retorna_lista():
    result = parse_properties("<html><body></body></html>")
    assert isinstance(result, list)


def test_parse_properties_extrai_campos_corretos():
    """Test with a minimal HTML snippet that matches the real Caixa structure."""
    html = """
    <ul class="control-group no-bullets">
      <li class="group-block-item">
        <div class="fotoimovel-col1">
          <img class="fotoimovel" src="/fotos/F123.jpg" onclick="detalhe_imovel(123456)">
          <strong>Leilão Único</strong>
        </div>
        <div class="dadosimovel-col2">
          <font>SAO CARLOS - CENTRO | R$ 85.000,00</font>
          <font>Apartamento - 52 m2, 2 quarto(s), 1 vaga(s) na garagem<br/>
          Número do imóvel: 123456<br/>
          Número do item: 1<br/>
          RUA TESTE, N. 123, CENTRO</font>
        </div>
      </li>
    </ul>
    """
    props = parse_properties(html)
    assert len(props) == 1
    assert props[0]["valor"] == 85000.0
    assert props[0]["modalidade"] == "Leilão Único"
    assert "52" in props[0]["area"]
    assert "TESTE" in props[0]["endereco"]


def test_parse_properties_foto_url_completa():
    """Photo with relative src should get the base URL prepended."""
    html = """
    <ul class="control-group no-bullets">
      <li class="group-block-item">
        <div class="fotoimovel-col1">
          <img class="fotoimovel" src="/fotos/F999.jpg">
          <strong>Venda Direta Online</strong>
        </div>
        <div class="dadosimovel-col2">
          <font>SAO CARLOS - CENTRO | R$ 90.000,00</font>
          <font>Apartamento - 60 m2, 3 quarto(s), 0 vaga(s) na garagem<br/>
          Número do imóvel: 999<br/>
          Número do item: 2<br/>
          AV. BRASIL, N. 500, CENTRO</font>
        </div>
      </li>
    </ul>
    """
    props = parse_properties(html)
    assert len(props) == 1
    assert props[0]["foto"].startswith("https://")


def test_parse_properties_chaves_obrigatorias():
    """All required keys must be present in each property dict."""
    html = """
    <ul class="control-group no-bullets">
      <li class="group-block-item">
        <div class="fotoimovel-col1">
          <img class="fotoimovel" src="/fotos/F1.jpg">
          <strong>Leilão Único</strong>
        </div>
        <div class="dadosimovel-col2">
          <font>SAO CARLOS - BAIRRO | R$ 100.000,00</font>
          <font>Apartamento - 70 m2, 2 quarto(s), 1 vaga(s) na garagem<br/>
          Número do imóvel: 111<br/>
          Número do item: 1<br/>
          RUA A, N. 1, BAIRRO</font>
        </div>
      </li>
    </ul>
    """
    props = parse_properties(html)
    required_keys = {"endereco", "valor", "area", "modalidade", "foto", "link"}
    assert required_keys.issubset(props[0].keys())
