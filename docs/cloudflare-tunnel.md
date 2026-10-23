# Criar o túnel da Cloudflare

Objetivo: o hostname `img.SEUDOMINIO.com` apontar para o servidor de imagens do app (só a pasta de JPEGs temporários). A Meta busca a imagem nessa URL. O próprio app inicia o `cloudflared`; você só cola o token no painel.

Pré-requisito: o domínio já está na Cloudflare.

1. Painel da Cloudflare → **Networking → Tunnels** → **Create a tunnel**.
2. Conector **Cloudflared**, nome `ic-ap`, criar.
3. **Copie só o token** (a string longa depois de `--token` ou `service install`). Não rode o comando.
4. Aba **Routes → Add route → Published application**:
   - Subdomain: `img`; Domain: o seu
   - Service URL: `http://localhost:8081` (o `cloudflared` roda dentro do container do app, junto do servidor de imagens)
5. No painel do app → **Conexões e acesso**:
   - Cole o token do túnel e salve (status deve ficar **conectado**).
   - Em URL pública, informe `https://img.SEUDOMINIO.com` e use o teste.
6. Teste manual opcional: coloque um arquivo em `data/public/teste.jpg` e abra a URL pública; apague depois.

Os nomes dos menus mudam de vez em quando; procure "Tunnels" no painel.

Segurança: esse hostname expõe somente `data/public/`. O painel (porta 8000, só local) não passa pelo túnel.
