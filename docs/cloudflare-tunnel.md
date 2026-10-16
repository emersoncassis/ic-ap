# Criar o túnel da Cloudflare

Objetivo: o hostname `img.SEUDOMINIO.com` apontar para o serviço `public` (nginx) do compose, que serve só os JPEGs temporários. A Meta busca a imagem nessa URL.

Pré-requisito: o domínio já está na Cloudflare (você já tem).

1. Painel da Cloudflare → **Networking → Tunnels** → **Create a tunnel**.
2. Escolha o conector **Cloudflared**, dê o nome `ic-ap` e crie.
3. A tela mostra um comando de instalação. **Copie só o token**: a string longa depois de `--token` (ou `service install`). Não precisa rodar o comando; o Docker faz isso.
4. Na aba **Routes → Add route → Published application**:
   - Subdomain: `img`
   - Domain: o seu
   - Service URL: `http://public:80` (é o nome do serviço no compose; `localhost` não funciona dentro do container)
5. No `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=<token copiado>
   PUBLIC_BASE_URL=https://img.SEUDOMINIO.com
   ```
6. `docker compose up -d`. No painel, o túnel deve aparecer como **Healthy**.
7. Teste: coloque qualquer arquivo em `data/public/teste.jpg` e abra `https://img.SEUDOMINIO.com/teste.jpg` no navegador. Apague depois.

Os nomes dos menus mudam de vez em quando; se algo não bater, procure "Tunnels" no painel.

Segurança: esse hostname expõe somente `data/public/`. O dashboard (spec 06) **não** deve usar esse túnel/hostname.
