# ADR-0023: Chaves dos *hosts* aleatórias de 256 bits, guardadas como *digest* HMAC-SHA256

* **Estado:** Aceite (retroativo)
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Security, Performance
* **Cenários relacionados:** SE1; SC1, SC2 (o custo de autenticar cada pedido)
* **Decisão do plano:** nenhuma (anterior ao plano; o ADR-0001 cita-a como decisão implícita).

## Contexto
Cada remote autentica-se no central com uma chave própria, enviada em cada pedido de ingestão (metadado
`x-api-key`, ADR-0003). Até à migração 2, o central guardava a chave **em claro** (`hosts.api_key`): quem lesse
a base de dados, um *backup* ou um *log* com uma consulta podia fazer-se passar por qualquer *host*.

Forças em jogo:
* **SE1:** uma chave inválida ou revogada é recusada (401) e nada fica gravado;
* uma fuga da base de dados não pode revelar chaves que funcionem;
* **cada pedido de ingestão é autenticado**: na medição nominal com 1.000 *hosts* são ≈ 69 pedidos por segundo,
  e na recuperação de SC2 muitos mais, com 2 vCPU para o central inteiro;
* o pedido traz só a chave, não o identificador do *host*: o central tem de encontrar o *host* a partir dela.

## Decisão
1. **A chave é aleatória e longa:** 32 bytes de `crypto/rand`, em hexadecimal (64 carateres, 256 bits de
   entropia), gerada pelo central. É mostrada **uma única vez**, ao criar ou regenerar o *host*; depois só se
   vê uma máscara (`abcd...wxyz`).
2. **O central guarda só um *digest*:** `HMAC-SHA256(segredo, "monitor:host-api-key:v1:" + chave)`, com um
   segredo de 32 bytes do servidor (`HOST_API_KEY_SECRET`), fora da base de dados. O prefixo com versão permite
   mudar o esquema mais tarde sem ambiguidade.
3. **A autenticação é uma pesquisa por índice:** o central calcula o *digest* da chave recebida e procura-o
   (`hosts.api_key_digest`, único). Não há comparação de *hashes* um a um.
4. **O segredo é verificado no arranque:** a base de dados guarda uma impressão digital do segredo
   (`api_key_settings`), e o central recusa arrancar com um segredo diferente. Um segredo trocado por engano
   invalidaria todas as chaves sem aviso.
5. Regenerar a chave de um *host* substitui o *digest*: a chave antiga deixa de funcionar de imediato
   (*Revoke Access*).

## Fundamentação teórica
* **Security → *Authenticate Actors*** e ***Revoke Access*** (slide 03).
* **Security → *Limit Exposure* / *Encrypt Data*:** a base de dados não guarda nada que sirva para entrar; o
  segredo que torna o *digest* útil fica fora dela.
* **Performance → *Reduce Overhead*:** verificar uma chave custa uma operação HMAC e uma pesquisa por índice.
* **Porque um HMAC e não uma função lenta de *password*:** as funções lentas (bcrypt, Argon2) existem para
  segredos de **baixa entropia**, que um atacante consegue adivinhar por força bruta se tiver o *hash*. Uma
  chave aleatória de 256 bits não se adivinha, por isso a lentidão não acrescenta segurança e só acrescenta
  custo. As *passwords* dos utilizadores, essas sim, usam bcrypt (`internal/services/auth.go`).

**Medição** (21/11, *benchmark* Go, numa máquina com 16 *threads*): verificar uma chave com HMAC-SHA256 custa
**0,6 µs**, e com bcrypt (custo 10) **50 ms**, cerca de 83.000 vezes mais. Com os ≈ 69 pedidos por segundo da
medição nominal, o bcrypt precisaria de ≈ 3,4 CPUs só para autenticar, mais do que os 2 vCPU do central.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Chave em claro na base de dados (iteração 0) | Uma fuga da base de dados, de um *backup* ou de um *log* revela todas as chaves |
| bcrypt ou Argon2 para as chaves | 50 ms por pedido (medido acima): o CPU da autenticação passaria do que o central tem. Além disso, um *hash* com sal não se pesquisa por índice: o pedido teria de trazer o identificador do *host*, ou o central compararia com todos |
| SHA-256 simples, sem segredo | Rápido e pesquisável, mas uma fuga da base de dados permitiria verificar chaves candidatas sem mais nada. O HMAC exige também o segredo do servidor |
| mTLS, um certificado por *host* | Mais forte (a chave privada nunca sai do *host*), mas exige uma CA, emissão, renovação e revogação de certificados em cada *host*. Fica como evolução se o modelo de ameaças o pedir |
| *Tokens* assinados de curta duração (JWT) | Precisariam de um fluxo de emissão e renovação no remote; a revogação imediata, que hoje é apagar um *digest*, passaria a depender de listas de revogação |

## Consequências
* **Positivas:**
  * A base de dados não guarda chaves utilizáveis.
  * A autenticação custa microssegundos e uma pesquisa por índice, mesmo na recuperação de SC2.
  * A revogação é imediata.
* **Negativas / *trade-offs*:**
  * **O segredo do servidor passa a ser crítico:** quem tiver a base de dados **e** o segredo pode verificar
    chaves candidatas. Mitigação: o segredo vive no ambiente do central, não na base de dados nem no
    repositório (a validação recusa segredos com menos de 32 bytes).
  * **Mudar o segredo invalida todas as chaves:** cada *host* tem de receber uma chave nova. A verificação da
    impressão digital no arranque torna isso uma decisão explícita, e não um acidente.
  * A chave viaja em cada pedido: tem de ir sempre por TLS. O E2E usa um nginx com TLS à frente do central
    (ADR-0012); o Compose do central não termina TLS e só publica as portas em *loopback*, por isso um *deploy*
    exposto precisa de um terminador TLS à frente.
  * A migração 2 converteu as chaves antigas para *digest* e apagou a coluna em claro; as sessões existentes
    foram invalidadas, porque podiam conter uma chave à espera de ser mostrada.

## Verificação
* **SE1** (relatório, cap. 7): chave inválida ou revogada → 401, e nada fica gravado (E2E e testes do *handler*
  gRPC).
* Testes de integração: a migração das chaves em claro para *digest* preserva a autenticação
  (`TestLegacyNumericMigration`, `TestVersionOneUpgradePreservesKeysAndReceipts`); a verificação do segredo
  recusa um segredo diferente (`CheckAPIKeySecret`, no mesmo teste).
* *Benchmark* acima, para o custo por pedido.

## Histórico
