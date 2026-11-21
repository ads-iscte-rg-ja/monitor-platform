# OWASP ASVS 5.0.0, nível 1: avaliação do Monitor

Método do D18 ([ADR-0016](../adr/0016-endurecimento-por-checklist-asvs.md)): os 70 requisitos de nível 1 do
**OWASP ASVS 5.0.0** (lista oficial: `OWASP_Application_Security_Verification_Standard_5.0.0_en.csv` da
*release* `v5.0.0_release` de `github.com/OWASP/ASVS`, coluna `L` = 1), avaliados contra o central (interface web,
API do *dashboard*, ingestão gRPC) e o remote. Avaliação de 21/11/2026, sobre o `main` (central c8e1ed7, remote
4197277), e de novo com as alterações do D18.

**Resultado:** C = cumpre, N/A = não se aplica (a funcionalidade não existe), F = falha.
A coluna "Antes" é o `main`; "Depois" inclui o D18. Requisitos em falha depois do D18 ficam com o risco aceite e
um gatilho no ADR.

| Resumo | C | N/A | F |
|---|---|---|---|
| Antes do D18 | 36 | 25 | **9** |
| Depois do D18 | 42 | 25 | **3** |

## V1 Codificação e sanitização

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V1.2.1 | Codificação de saída adequada ao contexto | C | C | `html/template` (escape por contexto) em todas as páginas (`templating/pages`); erros em `text/plain` |
| V1.2.2 | URLs construídos com dados não confiáveis codificados; só protocolos seguros | C | C | `url.Values` (`handlers/error_logs.go`); *endpoints* de saúde só `http`/`https` (`validateHostHealth`) |
| V1.2.3 | JavaScript/JSON construídos com codificação | C | C | JSON por `encoding/json`; o servidor não gera JavaScript |
| V1.2.4 | Consultas parametrizadas | C | C | `$n` em todas as consultas; os nomes de tabela da retenção são constantes (falso positivo triado no Sonar) |
| V1.2.5 | Injeção de comandos do SO | N/A | N/A | Nenhum `os/exec` nos dois repositórios |
| V1.3.1 | HTML de editores WYSIWYG sanitizado | N/A | N/A | Não há entrada HTML |
| V1.3.2 | Sem `eval()` nem execução dinâmica | C | C | `frontend/js` sem `eval`; o Tailwind servido localmente não usa `eval` nem `new Function` (verificado no ficheiro) |
| V1.5.1 | Parsers XML sem entidades externas | N/A | N/A | Nenhum `encoding/xml` |

## V2 Validação e lógica de negócio

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V2.1.1 | Regras de validação documentadas | C | C | Contrato com limites (`monitor-api`, ADR-0003); campos dos *hosts* e alertas no README e nos erros `models.Err*` |
| V2.2.1 | Validação positiva (listas, padrões, limites) | C | C | `validateHostHealth`, `validateAlert`, ingestão (`services/ingestion.go`), níveis por lista (ADR-0015) |
| V2.2.2 | Validação numa camada de serviço confiável | C | C | Serviços do central; os atributos HTML (`required`, `maxlength`) são só usabilidade |
| V2.3.1 | Fluxos de vários passos pela ordem certa | N/A | N/A | Não há fluxos de vários passos |

## V3 Segurança do *frontend* web

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V3.2.1 | O navegador não interpreta respostas no contexto errado | **F** | C | Antes: sem `nosniff` nem CSP. Depois: `X-Content-Type-Options: nosniff` e CSP em todas as respostas (`middleware.SecurityHeaders`) |
| V3.2.2 | Texto mostrado com funções seguras (`textContent`) | C | C | `frontend/js` sem `innerHTML`; o *dashboard* usa `textContent` e nós SVG |
| V3.3.1 | *Cookies* com `Secure` e prefixo `__Host-`/`__Secure-` | **F** | C | Antes: *cookie* `session`. Depois: `__Host-session` com `COOKIE_SECURE=true` (`Secure`, `Path=/`, sem `Domain`) |
| V3.4.1 | HSTS em todas as respostas, ≥ 1 ano | **F** | C | Depois: `Strict-Transport-Security: max-age=31536000` com `COOKIE_SECURE=true` (sem TLS não faz sentido) |
| V3.4.2 | CORS com origem fixa ou validada | N/A | N/A | Nenhuma resposta envia `Access-Control-Allow-Origin` (só a mesma origem) |
| V3.5.1 | Proteção contra CSRF | C | C | `middleware.CSRF` (Fetch Metadata, com `Origin` como alternativa) e `SameSite=Strict` |
| V3.5.2 | Se depende do *preflight* CORS, não pode ser contornado | N/A | N/A | Não depende do *preflight* (V3.5.1) |
| V3.5.3 | Funções sensíveis por POST, não GET | C | C | Todas as alterações são POST (`protectedRoutes`, ADR-0012), incluindo o *logout* |

## V4 Serviços web e API

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V4.1.1 | `Content-Type` certo, com `charset` nos tipos de texto | C | C | Páginas `text/html; charset=utf-8`; erros `text/plain; charset=utf-8`; JSON `application/json`; estáticos pelo tipo da extensão |
| V4.4.1 | WebSockets por TLS | N/A | N/A | Não há WebSockets |

## V5 Ficheiros

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V5.2.1 | Tamanho dos ficheiros aceites | N/A | N/A | Não há *upload* (corpos limitados a `MaxRequestBodySize`) |
| V5.2.2 | Extensão e conteúdo dos ficheiros aceites | N/A | N/A | Não há *upload* |
| V5.3.1 | Ficheiros carregados não executados | N/A | N/A | Não há *upload* |
| V5.3.2 | Caminhos de ficheiros a partir de dados confiáveis | C | C | Modelos e páginas por nomes internos; estáticos confinados a um nível, sem ficheiros ocultos nem *symlinks* (`MountStatic`) |

## V6 Autenticação

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V6.1.1 | Documentação dos limites contra *credential stuffing*, sem bloqueio malicioso de contas | **F** | **F** | Limites documentados (README, ADR-0007), mas o limite por conta (5 por minuto) deixa um atacante bloquear a conta enquanto insistir. Risco aceite no ADR-0016 |
| V6.2.1 | Palavras-passe com ≥ 8 caracteres | C | C | `ADMIN_PASSWORD` com 12 a 72 bytes (`config/admin.go`) |
| V6.2.2 | O utilizador pode mudar a palavra-passe | **F** | **F** | Só o operador, ao reprovisionar (`cmd/seed`, revoga as sessões). Risco aceite no ADR-0016 |
| V6.2.3 | Mudança exige a palavra-passe atual | N/A | N/A | Não há mudança pela interface (V6.2.2) |
| V6.2.4 | Palavras-passe comparadas com as 3.000 mais comuns | **F** | **F** | Não há verificação. Risco aceite no ADR-0016 |
| V6.2.5 | Sem regras de composição | C | C | Só o comprimento |
| V6.2.6 | Campo `type=password` | C | C | `frontend/templates/login.html` |
| V6.2.7 | Colar e gestores de palavras-passe permitidos | C | C | `autocomplete="current-password"`, sem bloqueios |
| V6.2.8 | Palavra-passe verificada como recebida, sem truncar | C | C | bcrypt recusa > 72 bytes em vez de truncar; o *email* é normalizado, a palavra-passe não |
| V6.3.1 | Controlos contra *brute force* conforme documentado | C | C | Limites por IP e por conta partilhados no PostgreSQL (ADR-0007), comparações bcrypt limitadas (`LOGIN_MAX_CONCURRENT`) |
| V6.3.2 | Sem contas por omissão | C | C | A única conta vem de `ADMIN_EMAIL`/`ADMIN_PASSWORD`, obrigatórios, sem valor por omissão |
| V6.4.1 | Palavras-passe iniciais geradas com segurança e de curta duração | N/A | N/A | O sistema não gera palavras-passe |
| V6.4.2 | Sem dicas nem perguntas secretas | C | C | Não existem |

## V7 Sessões

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V7.2.1 | Sessões verificadas no servidor | C | C | `scs` com armazenamento no PostgreSQL |
| V7.2.2 | *Tokens* gerados dinamicamente | C | C | *Tokens* de referência por sessão |
| V7.2.3 | *Tokens* de referência com CSPRNG e ≥ 128 bits | C | C | `scs`: 32 bytes de `crypto/rand` (256 bits) |
| V7.2.4 | *Token* novo na autenticação | C | C | `RenewToken` em `LoginUser` (`utils/session/manager.go`) |
| V7.4.1 | Terminar a sessão impede o seu uso | C | C | `Destroy` apaga a sessão no PostgreSQL |
| V7.4.2 | Sessões terminadas quando a conta é desativada ou apagada | C | C | `sessions.user_id … ON DELETE CASCADE`; o reprovisionamento revoga (teste `TestSeedReprovisionAndSessionRevocation`) |

## V8 Autorização

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V8.1.1 | Regras de autorização documentadas | **F** | C | Depois: ADR-0016 (um papel, o operador; tudo o resto é público ou do agente por chave de host) |
| V8.2.1 | Acesso a funções só com permissão explícita | C | C | `mdw.Auth` em todas as `protectedRoutes`, com teste (ADR-0012); a ingestão exige chave de host |
| V8.2.2 | Acesso a dados por item (IDOR/BOLA) | N/A | N/A | Um só papel e um só inquilino: o operador vê todos os *hosts* por definição. Na ingestão, cada lote é do host da chave (`hostID` do contexto, nunca do pedido) |
| V8.3.1 | Autorização numa camada confiável | C | C | *Middleware* e interceptor gRPC no servidor |

## V9 *Tokens* autocontidos e V10 OAuth

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V9.1.1–V9.1.3, V9.2.1 | Assinatura, algoritmos, chaves e validade de *tokens* autocontidos | N/A | N/A | Não há *tokens* autocontidos: sessões e chaves de host são de referência (digest HMAC) |
| V10.4.1–V10.4.5 | Servidor de autorização OAuth | N/A | N/A | Não há OAuth |

(V9: 4 requisitos; V10: 5 requisitos.)

## V11 Criptografia

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V11.3.1 | Sem modos de bloco inseguros nem *padding* fraco | N/A | N/A | A aplicação não cifra dados; o TLS é da biblioteca padrão |
| V11.3.2 | Só cifras e modos aprovados | N/A | N/A | Idem |
| V11.4.1 | Só funções de *hash* aprovadas; nada de MD5 | C | C | HMAC-SHA256 (chaves de host), SHA-256 (limites de *login*), bcrypt; nenhum MD5/SHA-1 em produção |

## V12 Comunicações seguras

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V12.1.1 | Só TLS 1.2 e 1.3 | C | C | Remote: `MinVersion: TLS12` (`requests/client.go`). O central termina TLS no balanceador da implantação |
| V12.2.1 | TLS em todos os serviços externos, sem descer para texto | C | C | Remote recusa `http://` fora de *loopback* (ADR-0015); web com `COOKIE_SECURE` e HSTS (D18) |
| V12.2.2 | Certificados publicamente confiáveis | N/A | N/A | Da implantação (o código usa o repositório de raízes do sistema) |

## V13 Configuração, V14 Proteção de dados e V15 Arquitetura segura

| Req. | Em resumo | Antes | Depois | Evidência |
|---|---|---|---|---|
| V13.4.1 | Sem metadados de controlo de versões na implantação | C | C | `.dockerignore` exclui `.git`; a imagem final só tem binários e `frontend/` |
| V14.2.1 | Dados sensíveis só no corpo ou cabeçalhos, nunca no URL | C | C | Chave de host em metadados gRPC; sessão em *cookie*; formulários por POST |
| V14.3.1 | Dados autenticados apagados do cliente no fim da sessão | **F** | C | Depois: `Clear-Site-Data: "cache", "storage"` no *logout*; o *frontend* não guarda nada em `localStorage` |
| V15.1.1 | Prazos documentados para corrigir dependências vulneráveis | **F** | C | Depois: prazos no ADR-0016 (CI bloqueia vulnerabilidades alcançáveis; Dependabot semanal) |
| V15.2.1 | Componentes dentro desses prazos | C | C | `govulncheck` verde no CI dos seis repositórios |
| V15.3.1 | Só os campos necessários são devolvidos | C | C | API do *dashboard* com DTOs; a chave de host nunca é serializada (`json:"-"`) |

**Contagem:** 70 requisitos (V1 8, V2 4, V3 8, V4 2, V5 4, V6 13, V7 6, V8 4, V9 4, V10 5, V11 3, V12 3,
V13 1, V14 2, V15 3), todos avaliados; a cobertura e as contagens do resumo foram verificadas contra o CSV
oficial com um *script*, não à mão.
