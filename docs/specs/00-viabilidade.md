# 00 · Viabilidade

**Veredito: viável.** Todas as peças existem e rodam em Docker. Mas "100% local" precisa de ressalvas, e o plano original do Gemini tem 4 pontos a corrigir.

## O que roda local de verdade

| Peça | Local? | Observação |
|---|---|---|
| Orquestração e painel (app Python) | Sim | Docker |
| LLM (Ollama) | Sim | Depende da VRAM, ver abaixo |
| Leitura de RSS | Sim | Só precisa de internet para buscar os feeds |
| Extração do texto da matéria | Sim | Usar `trafilatura` ou Crawl4AI locais |
| Render do post (HTML → JPEG) | Sim | Playwright/Browserless em Docker |
| Imagem de fundo por IA (opcional) | Sim | ComfyUI + Flux, só se houver GPU folgada |
| Aprovação | Quase | Telegram é serviço externo (gratuito) |
| **Publicação no Instagram** | **Não** | Exige internet, Graph API da Meta e URL pública da imagem |

Então: **geração 100% local; publicação inevitavelmente passa pela Meta.** Custo de API de IA = zero.

## Correções ao plano do Gemini

1. **Jina Reader não é local.** É serviço em nuvem. Trocar por `trafilatura` (Python) ou Crawl4AI.
2. **Página do Facebook não é mais obrigatória.** Existe o fluxo *Instagram API with Instagram Login* (token `graph.instagram.com`, permissão `instagram_business_content_publish`), que dispensa Página. O fluxo com Facebook Login continua válido, mas exige a Página vinculada e pode exigir Page Publishing Authorization. Como você já tem a API e o ID da conta Meta, a decisão fica na spec 03.
3. **Só JPEG.** A API aceita apenas JPEG (sem PNG, sem MPO/JPS). O screenshot do render tem que ser `type: jpeg`.
4. **App Review não é necessário** se o app só publica na sua própria conta (Standard Access). Não precisa esperar aprovação da Meta.

## Dependência crítica: URL pública

A Meta busca a imagem por URL no momento do publish. Opções, da mais simples à mais robusta:

- **Cloudflare R2** (free tier): sobe o JPEG, publica, apaga. Recomendado.
- **Cloudflare Tunnel** apontando para uma pasta/servidor estático local. Mantém tudo na sua máquina, mas o PC precisa estar ligado e o tunnel de pé na hora do publish.
- ngrok: serve para teste, não para produção (URL muda).

## Hardware

Informado: RTX 5070 + Intel Core Ultra 7. **VRAM confirmada: 8 GB** (RTX 5070 de notebook). Referência aproximada para modelos quantizados (Q4):

| VRAM | O que roda bem |
|---|---|
| 6–8 GB | Modelos ~7–8B. Português aceitável, tom de voz menos fiel |
| 12–16 GB | ~14B. Bom ponto de equilíbrio para PT-BR e JSON estrito |
| 24 GB+ | ~32B. Melhor fidelidade ao seu estilo |
| Sem GPU | Roda na CPU, mas lento (minutos por post). Aceitável para 1–3 posts/dia, já que não precisa ser em tempo real |

**Decisão para 8 GB:** o teto realista é um modelo de ~7–8B quantizado, que funciona para JSON e português, mas imita pior o tom de voz. Por isso o passo de reação terá **provedor configurável**: Ollama local por padrão, com troca por API de nuvem (Gemini ou Anthropic) via variável de ambiente, só nesse passo. O resto da esteira continua local. Observação: a assinatura do Claude Code serve para desenvolver o projeto, mas não substitui uma chave de API para rodar a esteira sozinha. Para usar Claude em produção seria uma chave da API da Anthropic, paga por uso.

Também com 8 GB: não rodar ComfyUI/Flux ao mesmo tempo que o Ollama (disputam a VRAM). Imagem de fundo por IA fica fora da v1.

Escolher o modelo no momento da implementação, consultando a biblioteca atual do Ollama. Não fixar nome de modelo nesta spec.

## Riscos

- **Alucinação / fato errado:** aprovação humana é obrigatória (nunca auto-publicar na v1).
- **Direitos autorais:** usar manchete + link/crédito da fonte + comentário próprio. Não reproduzir a matéria. Imagem da matéria só com cuidado; preferir card tipográfico sem foto de terceiros.
- **Spam / repetição:** variar templates e estrutura de texto.
- **Token expira:** token longo da Meta dura ~60 dias e precisa de refresh automático (spec 03).
- **PC desligado:** a esteira para. Aceitável na v1.
- **Automação não oficial:** proibida. Só Graph API oficial, nunca login simulado em navegador.
