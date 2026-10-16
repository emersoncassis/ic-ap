# 04 · Contexto pessoal (`context/meu_contexto.md`)

Arquivo Markdown injetado como *system prompt* do modelo. Começar assim; só evoluir para RAG (Qdrant) se o arquivo ficar grande demais.

## Template

```md
# Quem eu sou
(2–4 linhas: cargo, área, experiência prática)

# Temas que comento
(lista; ex.: IA aplicada, videomonitoramento/segurança eletrônica, ...)

# No que eu acredito
- ...

# O que eu critico
- hype vazio, promessa sem prova, ...

# Tom de voz
(direto, técnico mas acessível, provocativo, bem-humorado... escolher e descrever)

# Bordões e expressões minhas
- ...

# Frases e jeitos que NUNCA uso
- "No mundo dinâmico de hoje"
- "Revolucionário", "game changer"
- ...

# Exemplos reais de textos meus (3 a 5)
1. ...

# Regras de saída
- Sempre em primeira pessoa
- Sempre citar a fonte
- Opinião marcada como opinião
- Português do Brasil
```

## Fonte do conteúdo: site pessoal

A história, trajetória e posicionamento já estão no site pessoal do Emerson. Fluxo: um script de importação baixa as páginas do site (extractor), e o `meu_contexto.md` é montado a partir delas (rascunho gerado por LLM, revisado por você). O perfil do Instagram é pessoal, então o tom é primeira pessoa. Regenerar o rascunho quando o site mudar.

## Pendente de você

Informar a URL do site. Depois revisar o rascunho: temas, tom, o que você critica e pelo menos 3 exemplos reais de textos seus (legendas antigas servem). É isso que mais determina se o post soa como você ou como robô.

Temas candidatos, a confirmar: inteligência artificial; segurança eletrônica e videomonitoramento; IC TEAM e a saúde como ativo de empresas e empresários.
