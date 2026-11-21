# ADR-0016: Endurecimento por *checklist* (OWASP ASVS 5.0 nível 1): cabeçalhos, CSP, Tailwind local e guarda SSRF

* **Estado:** Aceite
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Security
* **Cenários relacionados:** SE2, SE3; lacunas X1, X2
* **Decisão do plano:** D18 (`../PLANO_MELHORIAS.md` §7.5)

## Contexto
Os repositórios são públicos. Duas lacunas estavam identificadas desde a linha de base:

* **X1:** a interface carrega o Tailwind de uma CDN em tempo de execução (`frontend/partials/layout.html:6`) e
  nenhuma resposta tem cabeçalhos de segurança: nem CSP, nem `X-Frame-Options`/`frame-ancestors`, nem `nosniff`,
  nem HSTS (nenhum `Header().Set` destes no código). Um XSS executaria sem obstáculo e qualquer página pode ser
  posta num `<iframe>` (*clickjacking*); a CDN é um ponto de falha e de ataque fora do nosso controlo.
* **X2:** o *endpoint* de saúde de um host é um URL que o operador escreve e o central visita a cada 30 s
  (ADR-0013). Aceita `http://127.0.0.1:…`, `http://169.254.169.254/…` (metadados de *cloud*) ou um nome que
  resolva para lá: é um SSRF a partir do central.

Cenários: **SE2** (XSS ou *clickjacking* no *dashboard* → bloqueado por CSP e `frame-ancestors`) e **SE3**
(*endpoint* de saúde para metadados de *cloud* ou *loopback* → rejeitado).

Para não endurecer às cegas, usámos uma *checklist* como método: os **70 requisitos de nível 1 do OWASP ASVS
5.0.0**, a versão atual, avaliados um a um em [`docs/seguranca/asvs-n1.md`](../seguranca/asvs-n1.md). Antes do
D18: **36 cumprem, 25 não se aplicam, 9 falham** (V3.2.1, V3.3.1, V3.4.1, V6.1.1, V6.2.2, V6.2.4, V8.1.1,
V14.3.1, V15.1.1).

## Decisão
1. ***Middleware* de cabeçalhos** em todas as respostas HTTP:
   * `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
     img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self';
     frame-ancestors 'none'; report-uri /csp-report`;
   * **modo por omissão: *enforce***; `CSP_MODE=report-only` envia a mesma política como
     `Content-Security-Policy-Report-Only` (para quem estiver a mudar a interface ver o que partiria);
   * `X-Frame-Options: DENY` sempre (os navegadores ignoram `frame-ancestors` em *Report-Only*, e assim o
     *clickjacking* fica bloqueado nos dois modos);
   * `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
     `Cross-Origin-Opener-Policy: same-origin`;
   * `Strict-Transport-Security: max-age=31536000` quando `COOKIE_SECURE=true` (só faz sentido com HTTPS).
2. **`POST /csp-report`** recebe os relatórios de violação do navegador (corpo limitado a 16 KiB) e regista-os
   como aviso, sem guardar nada: é o sinal de que uma página nova precisa de mudar antes de ir para produção.
3. **Tailwind servido pelo central** (`frontend/public/tailwindcss-browser-4.1.18.js`), a mesma versão que vinha
   da CDN, verificada contra a integridade publicada no registo npm (`sha512-cnAUsj2T…UV8Q==`, MIT). O ficheiro não
   usa `eval` nem `new Function`, por isso `script-src 'self'` chega; gera o CSS num `<style>`, por isso
   `style-src` precisa de `'unsafe-inline'`.
4. **Guarda SSRF nas *probes***, no `net.Dialer.Control`, isto é, **depois da resolução DNS** (protege também
   contra um nome que resolve para um IP interno e contra *DNS rebinding*). Rejeita *loopback*, *link-local*
   (inclui `169.254.169.254`), não especificado, *multicast* e os endereços de metadados conhecidos fora dessas
   gamas (`fd00:ec2::254`, `100.100.100.200`). **Permite RFC 1918 e ULA**: os *hosts* monitorizados estão,
   normalmente, em redes internas. No formulário, um IP literal destas gamas, ou `localhost`, é recusado logo, com
   uma mensagem clara; a guarda no *dial* é o controlo real.
5. **Correções que a *checklist* encontrou:** *cookie* de sessão `__Host-session` com `COOKIE_SECURE=true`
   (V3.3.1); `Clear-Site-Data: "cache", "storage"` no *logout* (V14.3.1); regras de autorização e prazos de
   correção de dependências documentados aqui (V8.1.1, V15.1.1).

**Regras de autorização (V8.1.1).** Há um papel, o operador: todas as páginas e a API do *dashboard* exigem a
sessão dele (`protectedRoutes`, ADR-0012); um operador vê e altera todos os *hosts*, por definição (um só
inquilino). A ingestão gRPC exige a chave de um host, e cada lote é atribuído ao host dessa chave, nunca a um
identificador do pedido. `/health*`, `/login`, as páginas legais e os ficheiros estáticos são públicos.

**Prazos de correção de dependências (V15.1.1).** Uma vulnerabilidade alcançável que o `govulncheck` encontre
falha o CI de todos os repositórios: é corrigida antes do *merge* seguinte, e nos repositórios com ela em `main`
em ≤ 7 dias. O Dependabot propõe atualizações todas as semanas; as que não são de segurança entram na iteração
seguinte (≤ 30 dias). A versão do Go acompanha a última correção (*patch*) da versão estável.

## Fundamentação teórica
* **Security → Resist Attacks: *Limit Exposure*:** o código de terceiros deixa de vir de outra origem em cada
  visita; a CSP reduz o que um XSS consegue fazer; a guarda SSRF reduz o que o central pode alcançar.
* **Security → *Limit Access*:** `frame-ancestors`/`X-Frame-Options` (ninguém enquadra a interface), CSP (só a
  própria origem executa *scripts*), guarda no *dial* (o central não fala com *loopback* nem metadados).
* **Security → *Change Default Settings*:** os navegadores aceitam *scripts* de qualquer origem, enquadramento e
  *sniffing* por omissão; os cabeçalhos mudam esses valores.
* **Análise por *checklist*:** um padrão externo e completo (ASVS) em vez de uma lista inventada; cada falha
  fica com evidência e uma decisão.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| CSP em *Report-Only* por omissão | Não bloqueia um XSS (SE2 falharia por omissão); as páginas atuais não têm *scripts* nem estilos *inline* e foram verificadas num navegador sem violações. *Report-Only* continua disponível |
| Compilar o CSS do Tailwind (CLI, Node) e tirar o `'unsafe-inline'` de `style-src` | Introduz um passo de *build* na interface, que hoje não tem nenhum; `'unsafe-inline'` em estilos é um risco muito menor do que em *scripts* (não executa código). Gatilho abaixo |
| Manter a CDN com `integrity` (SRI) | Protege contra um ficheiro alterado, mas a CDN continua a ser um ponto de falha (sem ela não há estilos) e a revelar o IP de cada utilizador a terceiros |
| Bloquear todos os IPs privados nas *probes* | Inutiliza o produto: os *hosts* monitorizados estão em redes internas |
| Validar o URL só no formulário | Um nome DNS que resolve para `127.0.0.1` (ou muda de resolução depois) passa; só a verificação no *dial*, com o IP resolvido, fecha o SSRF |
| Mudança de palavra-passe na interface, lista de palavras-passe comuns, bloqueio de contas sem negação de serviço (V6.2.2, V6.2.4, V6.1.1) | Há uma só conta, de operador, criada e mudada pela implantação (`ADMIN_PASSWORD`, `cmd/seed`, que revoga as sessões); o custo não compensa a este âmbito. Risco aceite, gatilho abaixo |

## Consequências
* **Positivas:** SE2 e SE3 cumprem-se; a interface funciona sem acesso à Internet; 6 das 9 falhas do ASVS N1
  fechadas, as 3 restantes com risco aceite e gatilho.
* **Negativas / *trade-offs*:**
  * `style-src 'unsafe-inline'`: um atacante que injete HTML pode alterar estilos (não executar código).
    **Gatilho:** quando a interface tiver um passo de *build*, gerar o CSS e retirar `'unsafe-inline'`.
  * Uma página nova com um *script inline* parte em *enforce*; o `/csp-report` e o modo *Report-Only* mostram-no
    antes de produção.
  * A guarda recusa *endpoints* em *loopback*: monitorizar uma aplicação na mesma máquina do central deixa de ser
    possível (usar o IP da interface de rede). Os testes que usam servidores locais desligam a guarda de forma
    explícita.
  * Renomear o *cookie* termina, uma vez, as sessões abertas no momento da atualização.
  * **Risco aceite (V6.1.1, V6.2.2, V6.2.4):** um atacante pode bloquear o *login* do operador durante a janela de
    1 minuto enquanto insistir; a palavra-passe muda-se pela implantação e não é comparada com uma lista de
    palavras-passe comuns (tem pelo menos 12 caracteres). **Gatilho:** mais do que uma conta, ou contas criadas
    por utilizadores.

## Verificação
* **SE2:** teste do *router* completo: todas as respostas (página, API, estáticos, erro) com a CSP, `DENY`,
  `nosniff`, `Referrer-Policy`; HSTS só com `COOKIE_SECURE`; o modo *Report-Only* muda só o nome do cabeçalho.
  Num navegador real: 0 violações nas páginas atuais em *enforce*, e um *script inline* injetado de propósito é
  bloqueado e reportado.
* **SE3:** teste do validador do *dial* com IPs de cada gama (bloqueados e permitidos); teste ponta a ponta de uma
  *probe* para `localhost` e para um nome que resolve para *loopback*: o host fica `offline`, sem pedido nenhum a
  chegar ao servidor local; o formulário recusa IPs literais bloqueados.
* **ASVS N1:** a tabela de `docs/seguranca/asvs-n1.md` atualizada depois da implementação.

**Resultado (21/11):** SE2 e SE3 cumprem-se (`docs/metrics/iter-6/se2-se3.md`). ASVS N1: **9 → 3 falhas**
(36 → 42 cumprem, 25 não se aplicam). Num navegador real, com a CSP em *enforce*: 0 relatórios de violação nas
páginas atuais; um *script inline* injetado não executou e um `<iframe>` da página foi bloqueado, ambos com
relatório no `/csp-report`. As *probes* reais para `127.0.0.1` e para `localhost` (resolvido) não chegaram ao
servidor local e os hosts ficaram *unhealthy*. Lint do central 53 → 52 (a validação do *endpoint* foi partida
em sintaxe e destino, e baixou de complexidade); cobertura das linhas novas 96,6 %.

**Encontrado na verificação, anterior ao D18:** o seletor de hosts do *dashboard* enviava o texto da opção
provisória como `host_id`, e o painel de métricas nunca carregava no navegador (400 no primeiro pedido).
Corrigido, com teste.

## Histórico
