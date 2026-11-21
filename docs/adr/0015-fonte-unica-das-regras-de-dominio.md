# ADR-0015: Uma fonte única por repositório para os níveis de log e o endereço do central

* **Estado:** Aceite
* **Data:** 2026-11-21
* **Autores:** João Afonso, Rodrigo Gorjão
* **QA principal:** Modifiability
* **Cenários relacionados:** MO2; lacunas M3, M7
* **Decisão do plano:** D12 (`../PLANO_MELHORIAS.md` §7.3)

## Contexto
MO2: alterar uma regra do protocolo toca **1 sítio por repositório**, e uma divergência é apanhada por um
teste. O contrato entre repositórios já está no `monitor-api` (ADR-0003, `LogLevel` em *protobuf*). Dentro de
cada repositório, as mesmas regras repetem-se (contagem de 21/11):

**Níveis de log (M3).** A lista completa (INFO, WARN, ERROR, CRITICAL, PANIC) está escrita:
* **central:** 5 vezes em Go (`handlers/error_logs.go:116`, `services/ingestion.go:172`,
  `services/error_logs.go:41`, `services/buffer_status.go:12`, `alertmetric/errors.go:47`), mais a tradução do
  *protobuf* (`grpcapi/ingest.go:222`) e o `CHECK` do SQL (`init.sql:42`);
* **remote:** 1 em Go (`validation/records.go:67`), mais a tradução para o *protobuf*
  (`requests/errorlogs.go:20`) e 2 `CHECK` no esquema do *buffer* (`schema.sql:16,56`);
* **SDK:** 1 (`monitor.go:102`), não exportada; o **hello-world** repete-a (`main.go:51`).

Nada liga as cópias: acrescentar um nível exige encontrar todas, e esquecer uma não falha nenhum teste.

**Endereço do central no remote (M7).** `CENTRAL_GRPC_URL` é validado duas vezes, com regras diferentes:
`config.Load` aceita `http://` só para `localhost`, `127.0.0.1` e `::1` e deixa passar um caminho;
`requests.parseTarget` aceita qualquer endereço de *loopback* (`127.0.0.2`) e recusa caminhos, credenciais e
*query*. Um valor pode passar numa e falhar na outra, e a mensagem de erro depende de qual apanha primeiro.

## Decisão
1. **Central:** as cinco constantes `models.Level*` e `models.Levels` (ordenados por gravidade, com
   `Severity` e `ValidLevel`); os cinco sítios em Go usam-nos. São constantes de texto, não um tipo novo: os
   campos `Level` dos modelos continuam `string`, e um tipo próprio obrigaria a converter em cada consulta. Um **teste compara `models.Levels` com o `CHECK` de
   `init.sql`**, e outro com a tradução do *protobuf* (cada `LogLevel` conhecido tem um nível, e vice-versa).
2. **Remote:** `validation` é o dono dos níveis (`validation.Levels`); a tradução para o *protobuf* e o teste
   do esquema usam-no. Um teste compara-o com os dois `CHECK` de `schema.sql`.
3. **SDK:** constantes exportadas (`monitorsdk.LevelInfo` … `LevelPanic`, `monitorsdk.Levels`), publicadas numa
   versão nova (v0.2.0); o hello-world passa a usá-las. Um teste do SDK compara-as com o `CHECK` de
   `schema.sql` do remote (o SDK escreve nesse esquema; o CI já faz *checkout* do remote).
4. **Remote, endereço:** uma só validação, `validation.CentralURL`; `config.Load` e o cliente gRPC chamam-na.
   Fica em `validation`, e não no cliente, para a configuração não depender do gRPC. A regra é a do
   cliente, a mais estrita: `https://`, ou `http://` só em *loopback*, sem caminho, credenciais, *query* nem
   fragmento.

O SQL continua a ter as suas listas (`CHECK`, e o `IN` das métricas de erro): a base de dados também valida, de
propósito. A diferença é que agora um teste as compara com o Go.

## Fundamentação teórica
* **Modifiability → *Increase Semantic Coherence*:** o que muda junto (os níveis) fica num sítio.
* **Modifiability → *Abstract Common Services*:** a validação do endereço é um serviço que dois módulos usavam
  em versões diferentes.
* **Testability:** a duplicação que não se pode eliminar (Go ↔ SQL, Go ↔ *protobuf*) fica coberta por testes de
  consistência, que falham quando as cópias divergem.

## Alternativas consideradas
| Alternativa | Porque foi rejeitada |
|---|---|
| Usar o `LogLevel` do *protobuf* em todo o lado | Leva o tipo do contrato de rede para as camadas internas e para o SQL; a tradução na fronteira é o que isola o domínio do protocolo (ADR-0003) |
| Um módulo partilhado com os níveis para os quatro repositórios | Mais uma dependência entre repositórios que mudam a ritmos diferentes; o contrato entre eles já é o `monitor-api` |
| Gerar o `CHECK` do SQL a partir do Go | As migrações são SQL escrito à mão, e a base (`init.sql`) é imutável (`deployments/database/embed.go`); um teste que compara é mais simples e cobre as migrações antigas |
| Aceitar a regra menos estrita do `config` | Deixava passar caminhos que o cliente gRPC ignora; a regra estrita é a que de facto funciona |

## Consequências
* **Positivas:** acrescentar um nível passa a ser 1 sítio em Go por repositório, mais o SQL e o *protobuf*, e os
  testes dizem quais faltam; o endereço do central tem uma só regra e uma só mensagem de erro.
* **Negativas / *trade-offs*:** o SDK muda de versão (v0.2.0) e o hello-world tem de a pedir, pela mesma ordem de
  *merges* do ADR-0012: SDK primeiro, *tag*, depois o hello-world. Um `CENTRAL_GRPC_URL` com caminho, que
  hoje o `config` aceita, passa a ser recusado no arranque (antes era recusado logo a seguir, pelo cliente).

## Verificação
* **MO2:** contagem antes/depois das definições da lista de níveis em Go, por repositório (alvo: 1); testes de
  consistência Go ↔ SQL e Go ↔ *protobuf* que falham quando se altera uma das cópias (verificado alterando uma
  e vendo o teste falhar).
* **M7:** um teste de tabela com os endereços que divergiam (`http://127.0.0.2:3334`, `https://h/caminho`) passa
  pela mesma função no `config` e no cliente.

**Resultado (21/11):** MO2 cumpre-se (`docs/metrics/iter-6/te2-te3-mo2.md`). Lista de níveis em Go: central
5 → 1, remote 1 → 1, SDK 1 (não exportada) → 1 exportada, hello-world 1 → 0. Seis testes de consistência
(central: `init.sql`, *protobuf*, SQL das métricas; remote: `schema.sql`, *protobuf*; SDK: `schema.sql`); retirar
um nível do `CHECK` do `init.sql` ou de `monitorsdk.Levels` faz falhar o teste respetivo (verificado e
revertido). M7: 2 validações → 1. Lint do remote 20 → 19.

## Histórico
