"""Testes unitários para o motor de Distribuição Multiplataforma Local."""
import asyncio
import pytest
from unittest.mock import AsyncMock

from app import db, distribuicao


def test_salvar_listar_alternar_e_remover_canal():
    db.init()
    perfil_id = 999

    # Limpa antes do teste
    db.x("DELETE FROM canais_distribuicao WHERE perfil_id=?", (perfil_id,))

    # 1. Salva canal Threads
    distribuicao.salvar_canal(
        perfil_id=perfil_id,
        canal="threads",
        identificador="threads_user_123",
        token="th_token_secreto_999",
        ativo=True,
    )

    # 2. Salva canal YouTube Shorts
    distribuicao.salvar_canal(
        perfil_id=perfil_id,
        canal="youtube",
        identificador="UC_canal_123",
        token="yt_token_secreto_888",
        ativo=True,
        extra={"privacy_status": "unlisted"},
    )

    canais = distribuicao.listar_canais(perfil_id)
    assert len(canais) == 2

    # Verifica mascaramento
    threads = next(c for c in canais if c["canal"] == "threads")
    assert threads["tem_token"] is True
    assert "th_token_secreto_999" not in threads["token_mascarado"]
    assert threads["identificador"] == "threads_user_123"

    youtube = next(c for c in canais if c["canal"] == "youtube")
    assert youtube["extra"]["privacy_status"] == "unlisted"

    # 3. Obter canal descriptografado
    canal_dec = distribuicao.obter_canal(perfil_id, "threads")
    assert canal_dec is not None
    assert canal_dec["token"] == "th_token_secreto_999"

    # 4. Alternar status
    assert distribuicao.alternar_canal(perfil_id, "threads") is True
    canal_alt = distribuicao.obter_canal(perfil_id, "threads")
    assert canal_alt["ativo"] == 0

    # 5. Remover canal
    assert distribuicao.remover_canal(perfil_id, "threads") is True
    assert distribuicao.obter_canal(perfil_id, "threads") is None

    # Limpeza
    db.x("DELETE FROM canais_distribuicao WHERE perfil_id=?", (perfil_id,))


def test_publicar_multiplataforma_sem_canais():
    async def _run():
        res = await distribuicao.publicar_multiplataforma(99999, 99999, "https://exemplo.com")
        assert res["sucessos"] == []
        assert res["falhas"] == []
        assert res["pulados"] == []

    asyncio.run(_run())


def test_publicar_threads_mock():
    async def _run():
        post = {"id": 1, "legenda": "Teste de legenda no Threads", "formato": "feed"}
        arqs = ["foto1.jpg"]

        from unittest.mock import MagicMock
        mock_client = AsyncMock()
        # Mock criação container (httpx.Response é síncrono para status_code e json())
        mock_resp_cont = MagicMock()
        mock_resp_cont.status_code = 200
        mock_resp_cont.json.return_value = {"id": "threads_container_123"}

        # Mock publicação
        mock_resp_pub = MagicMock()
        mock_resp_pub.status_code = 200
        mock_resp_pub.json.return_value = {"id": "threads_post_789"}

        mock_client.post.side_effect = [mock_resp_cont, mock_resp_pub]

        post_id = await distribuicao._publicar_threads(
            c=mock_client,
            identificador="me",
            token="fake_token",
            post=post,
            arqs=arqs,
            base_url="https://exemplo.com",
        )
        assert post_id == "threads_post_789"

    asyncio.run(_run())


def test_publicar_tiktok_rejeita_formato_nao_video():
    async def _run():
        post = {"id": 1, "legenda": "Foto comum", "formato": "feed"}
        mock_client = AsyncMock()
        with pytest.raises(ValueError, match="apenas publicação de vídeos"):
            await distribuicao._publicar_tiktok(
                c=mock_client,
                identificador="creator_1",
                token="fake_token",
                post=post,
                arqs=["foto.jpg"],
                base_url="https://exemplo.com",
                extra={},
            )

    asyncio.run(_run())


def test_publicar_linkedin_texto_mock():
    async def _run():
        from unittest.mock import MagicMock
        post = {"id": 1, "legenda": "Post corporativo no LinkedIn", "formato": "feed"}
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"x-restli-id": "urn:li:share:999888"}
        mock_client.post.return_value = mock_resp

        urn = await distribuicao._publicar_linkedin(
            c=mock_client,
            identificador="12345678",
            token="fake_li_token",
            post=post,
            arqs=[],
            base_url="https://exemplo.com",
        )
        assert urn == "urn:li:share:999888"

    asyncio.run(_run())


def test_publicar_tiktok_mock():
    async def _run():
        from unittest.mock import MagicMock
        post = {"id": 1, "legenda": "Vídeo viral no TikTok", "formato": "reel"}
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": {"code": "ok"}, "data": {"publish_id": "tiktok_pub_555"}}
        mock_client.post.return_value = mock_resp

        pub_id = await distribuicao._publicar_tiktok(
            c=mock_client,
            identificador="open_id_123",
            token="fake_tk_token",
            post=post,
            arqs=["video.mp4"],
            base_url="https://exemplo.com",
            extra={"privacy_level": "PUBLIC_TO_EVERYONE"},
        )
        assert pub_id == "tiktok_pub_555"

    asyncio.run(_run())


def test_testar_canal_sem_token():
    async def _run():
        db.init()
        # Perfil inexistente ou sem canal
        res = await distribuicao.testar_canal(99999, "threads")
        assert res["ok"] is False
        assert "não configurado" in res["erro"].lower()

    asyncio.run(_run())

