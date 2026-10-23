import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app import db, wizard, telegram

pytestmark = pytest.mark.usefixtures("estado_isolado")


def test_gerar_contexto_da_entrevista_deterministico():
    async def _test():
        db.init()
        # Sem LLM ativa, o fallback determinístico deve gerar um markdown completo de 2026
        md = await wizard.gerar_contexto_da_entrevista(
            nome="Emerson Assis",
            handle="emersonassis",
            nicho="Inteligência Artificial Aplicada",
            estilo="Direto, assertivo e didático",
            temas="automação, agentes, negócios",
            crencas="Praticidade supera teoria vazia",
            inimigos="Gurus de palco e promessas milagrosas",
        )
        assert "# Contexto e Tom de Voz: Emerson Assis" in md
        assert "Inteligência Artificial Aplicada" in md
        assert "Diretrizes de Tom de Voz (2026)" in md
        assert "Gancho" in md
        assert "Pilares de Conteúdo" in md
        assert "automação" in md
    asyncio.run(_test())


def test_gerar_contexto_do_meta_ai():
    async def _test():
        db.init()
        relatorio = """
        Análise do criador:
        - Foco em automações reais de ponta a ponta
        - Comunicação sem rodeios, estilo pragmático
        - Público busca parar de perder tempo com tarefas repetitivas
        """
        md = await wizard.gerar_contexto_do_meta_ai(relatorio, "Emerson Assis", "emersonassis")
        assert "Emerson Assis" in md
        assert "Diretrizes de Tom de Voz (2026)" in md
        assert "CTA única" in md
    asyncio.run(_test())


def test_criar_perfil_wizard():
    db.init()
    pid = wizard.criar_perfil_wizard(
        nome="Perfil Teste Wizard",
        handle="perfil_wizard",
        contexto_md="# Contexto Teste",
        palavras_chave="ia, automacao",
        horarios="10:00,19:00",
        telegram_chat_id="99887766",
        ativo=True,
    )
    assert pid > 0
    p = db.one("SELECT * FROM perfis WHERE id=?", (pid,))
    assert p is not None
    assert p["nome"] == "Perfil Teste Wizard"
    assert p["handle"] == "perfil_wizard"
    assert p["telegram_chat_id"] == "99887766"
    assert p["ativo"] == 1


def test_telegram_obter_me_e_detectar_chat():
    async def _test():
        # Quando desativado ou sem token
        with patch("app.settings.telegram_token", return_value=""):
            me = await telegram.obter_me()
            assert me is None
            telegram._ultimo_chat_detectado = None  # o polling do app (segundo plano) pode ter guardado um chat desde a fixture
            chat = await telegram.detectar_chat_recente()
            assert chat is None

        # Com mock de resposta do getUpdates
        mock_updates = {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "chat": {"id": 12345678, "first_name": "Emerson", "username": "emersonassis"},
                        "text": "Oi bot",
                    },
                }
            ],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_updates
        
        with patch("app.settings.telegram_token", return_value="123:ABC"):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
                chat = await telegram.detectar_chat_recente()
                assert chat is not None
                assert chat["chat_id"] == "12345678"
                assert "Emerson" in chat["nome"]
    asyncio.run(_test())
