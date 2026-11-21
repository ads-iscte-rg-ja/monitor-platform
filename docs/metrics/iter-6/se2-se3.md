# SE2 e SE3 (Passo 8: D18, ADR-0016)

21/11/2026, central c8e1ed7 + D18 por commitar. Go 1.27.4; Chrome (Claude in Chrome) para a verificação no
navegador.

## SE2: XSS e *clickjacking* bloqueados

**Testes** (`go test ./internal/utils/middleware/ ./internal/templating/pages/ ./internal/handlers/`):
* `TestSecurityHeadersOnEveryResponse`: página, API JSON, erro 500 e rota inexistente, nos dois modos. Todas com
  a CSP (`script-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`), `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy`, `Cross-Origin-Opener-Policy`; HSTS só com `COOKIE_SECURE=true`; em *Report-Only* só muda o
  nome do cabeçalho da CSP.
* O teste de *render* de todas as páginas falha se uma página tiver um `<script>` com corpo, um atributo `on…=` ou
  um URL de CDN; e exige o Tailwind local.

**Navegador real** (central local, `COOKIE_SECURE=false`, CSP em *enforce*, sessão de operador):

| Passo | Resultado |
|---|---|
| Volta às páginas `/dashboard`, `/hosts`, `/errors`, `/alerts`, `/profile`, `/terms` (e `/login`) | Todas 200, estilos do Tailwind aplicados; **0 relatórios** no `/csp-report` |
| `<script>` com corpo injetado na página (como faria um XSS) | **Não executou** (`window.__xss` continuou `false`); evento `securitypolicyviolation` com `script-src-elem`, `disposition: enforce`; relatório recebido no `/csp-report` |
| A página carregada num `<iframe>` | **Bloqueada** (`frame-ancestors`); relatório recebido no `/csp-report` |

Total no log do servidor: 2 relatórios de violação, os dois das injeções de propósito.

**Defeito encontrado na verificação (anterior ao D18):** no *dashboard*, a opção provisória do seletor de hosts
("Loading hosts…") não tinha `value`; o `dashboard.js` enviava esse texto como `host_id`, o primeiro pedido de
métricas recebia 400 e a lista de hosts nunca era preenchida (`frontend/templates/dashboard.html`, desde o
primeiro commit). Os testes de carga (k6) chamam a API diretamente e não o viam. Corrigido (`value=""`), com
teste; depois da correção, o pedido de métricas responde 200 e o seletor mostra os hosts.

## SE3: *endpoint* de saúde para *loopback* ou metadados recusado

**Testes** (`go test ./internal/services/ -run 'ProbeGuard|HealthEndpointForm|ProbeToLoopback'`):
* `TestProbeGuardRanges`: 14 endereços bloqueados (*loopback* IPv4/IPv6, `169.254.169.254` e restante
  *link-local*, não especificado, *multicast*, `fd00:ec2::254`, `100.100.100.200`, IPv4 mapeado em IPv6) e 6
  permitidos (RFC 1918, ULA, públicos), na função e no `Dialer.Control`.
* `TestHealthEndpointFormRefusesBlockedTargets`: o formulário recusa 8 *endpoints* (IP literal bloqueado,
  `localhost`, `*.localhost`) e aceita 3 de redes internas.
* `TestProbeToLoopbackNeverReachesIt`: *probes* reais para `http://127.0.0.1:<porta>` e
  `http://localhost:<porta>` (nome resolvido, depois recusado) a um servidor local: **0 pedidos** chegam ao
  servidor e os dois hosts ficam *unhealthy*. Controlo: sem a guarda, o mesmo servidor recebe a *probe* e o host
  fica *healthy*, por isso é a guarda que trava.
