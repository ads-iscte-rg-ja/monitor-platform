// Testes de carga da ingestão (D10). Cada VU é um host e comporta-se como o monitor-remote:
// estatísticas a cada 30 s, erros a cada 10 s, lotes de até 100 registos, os mais recentes
// primeiro, novas tentativas nas falhas transitórias e paragem nas definitivas (ADR-0003).
//
// Variáveis (preenchidas por correr.sh):
//   CENARIO     nominal | recovery-storm | noisy-neighbour | capacidade
//   MULT_LOGS   multiplicador da taxa de logs (análise de sensibilidade: 1, 2, 5)
//   DURACAO     duração dos cenários contínuos (ex.: 10m)
//   RESULTADO   ficheiro de saída em /results (sem extensão)
import grpc from 'k6/net/grpc';
import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { Counter, Rate, Trend } from 'k6/metrics';

const CENARIO = __ENV.CENARIO || 'nominal';
const MULT_LOGS = parseFloat(__ENV.MULT_LOGS || '1');
const DURACAO = __ENV.DURACAO || '10m';
const RESULTADO = __ENV.RESULTADO || CENARIO;
const CENTRAL_GRPC = __ENV.CENTRAL_GRPC || 'backend:3334';
const CENTRAL_HTTP = __ENV.CENTRAL_HTTP || 'http://backend:3333';

const HOSTS = new SharedArray('hosts', () => JSON.parse(open('/dados/hosts.json')));

// Perfil de logs (relatório, Tabela "Perfil de logs por host"), em registos por segundo.
const TAXA = { silencioso: 0.5 / 60, normal: 10 / 60, ruidoso: 1, rajada: 10 / 60 };
const TAXA_EM_RAJADA = 200;                 // noisy-neighbour: 200/s durante 2 min
const INICIO_RAJADA_S = parseInt(__ENV.INICIO_RAJADA_S || '180', 10);
const DURACAO_RAJADA_S = 120;
const INTERVALO_ERROS_S = 10;               // ERROR_POST_INTERVAL do remote
const TICKS_POR_STATS = 3;                  // STATS_POST_INTERVAL = 30 s
const LOTE = 100;                           // MaxBatchRecords do contrato
// Os mesmos códigos que o remote trata como transitórios (monitor-remote/internal/requests/failures.go).
// Canceled incluído: é o que o cliente recebe quando o pedido chega ao timeout.
// Códigos numéricos gRPC: no k6 2.x, res.status é o nome do código, por isso compara-se res.error.code.
// Canceled (1), Unknown (2), DeadlineExceeded (4), ResourceExhausted (8), Aborted (10), Internal (13),
// Unavailable (14).
const TRANSITORIOS = new Set([1, 2, 4, 8, 10, 13, 14]);

// Métricas próprias. O atraso é o que o central acrescenta: do primeiro envio de um lote à
// confirmação, incluindo as novas tentativas. O intervalo de recolha do agente (até 10 s nos
// erros e 30 s nas estatísticas) é fixo por desenho e fica de fora.
const atraso = new Trend('atraso_central', true);
const falhas = new Rate('lotes_perdidos');            // lotes com falha definitiva (o agente pausaria)
const rejeicoes = new Counter('respostas_nao_ok');    // por código gRPC
const registos = new Counter('registos_confirmados');
const recuperacao = new Trend('tempo_recuperacao', true);  // um valor por host que entregou tudo
const backlog = new Counter('backlog_total');                 // registos que os hosts tinham pendentes

const thresholds = {
  // SC1 / SC5: medidas do lado do agente. O CPU e o p95 do servidor vêm do Prometheus.
  'grpc_req_duration{ingestao:sim}': ['p(95)<300'],
  'lotes_perdidos': ['rate==0'],
  'atraso_central{vizinho:sim}': ['p(95)<5000'],
};
// Uma submétrica por código gRPC, para o resumo mostrar que respostas não OK houve.
for (let codigo = 1; codigo <= 16; codigo++) {
  thresholds[`respostas_nao_ok{codigo:${codigo}}`] = ['count>=0'];
}
if (CENARIO === 'noisy-neighbour') {
  thresholds['atraso_central{fase:rajada,vizinho:sim}'] = ['p(95)<5000']; // SC5: só durante a rajada
  thresholds['atraso_central{perfil:rajada}'] = ['p(95)<999999999'];     // registado para o relatório
}
if (CENARIO === 'recovery-storm') {
  thresholds['tempo_recuperacao'] = ['max<900000'];        // SC2: backlog absorvido em 15 min
  thresholds['http_req_duration{dashboard:sim}'] = ['p(95)<1000'];
}

// Cada host é uma única iteração longa: o índice da iteração no cenário (0..N-1) dá a cada VU um
// host diferente, mesmo com os VUs do dashboard a partilhar a numeração.
const continuo = {
  executor: 'per-vu-iterations', vus: HOSTS.length, iterations: 1, maxDuration: '40m',
  gracefulStop: '30s', exec: 'hostContinuo',
};
const cenarios = {
  nominal: continuo,
  'noisy-neighbour': continuo,
  // SC3: cada host envia lotes de 100 erros sem pausa, para a carga ficar acima da capacidade.
  capacidade: { ...continuo, exec: 'hostCapacidade' },
  'recovery-storm': {
    executor: 'per-vu-iterations', vus: HOSTS.length, iterations: 1, maxDuration: '30m', exec: 'hostComBacklog',
  },
};

export const options = {
  scenarios: {
    ingestao: cenarios[CENARIO],
    // O dashboard é consultado durante toda a medição (SC2 exige p95 < 1 s durante a recuperação).
    dashboard: {
      executor: 'constant-arrival-rate', rate: 1, timeUnit: '2s', duration: DURACAO,
      preAllocatedVUs: 2, maxVUs: 10, exec: 'dashboard',
    },
  },
  thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
  setupTimeout: '2m',
};

// ---------------------------------------------------------------- estado de cada VU (host)
const client = new grpc.Client();
client.load(['/proto'], 'monitor/ingest/v1/ingest.proto');
let ligado = false;
let host;
let proximoStat = 1;
let proximoErro = 1;
let acumulado = 0;
let tick = 0;
let avisos = 0;
let avisosRetry = 0;

function iniciarHost() {
  if (!ligado) {
    host = HOSTS[exec.scenario.iterationInTest];
    client.connect(CENTRAL_GRPC, { plaintext: true, timeout: '30s' });
    ligado = true;
  }
}

function tags(tipo, fase) {
  // "vizinho": os hosts que não estão em rajada, cujo atraso SC5 protege.
  const emRajada = host.perfil === 'rajada' && fase === 'rajada';
  return { ingestao: 'sim', tipo, perfil: host.perfil, fase, vizinho: emRajada ? 'nao' : 'sim' };
}

// Como o remote: as falhas transitórias repetem-se até o lote ser entregue (o registo fica pendente no
// buffer, nunca se perde); o backoff é o do remote (5 s a duplicar, até 5 min, com jitter de ±20 %).
function enviar(metodo, pedido, n, t) {
  const inicio = Date.now();
  for (let tentativa = 0; ; tentativa++) {
    const res = client.invoke(`monitor.ingest.v1.IngestService/${metodo}`, pedido, {
      metadata: { 'x-api-key': host.chave }, tags: t, timeout: '15s',
    });
    if (res.status === grpc.StatusOK) {
      atraso.add(Date.now() - inicio, t);
      registos.add(n, { tipo: t.tipo });
      falhas.add(false, t);
      return;
    }
    const codigo = res.error && typeof res.error.code === 'number' ? res.error.code : 2;
    rejeicoes.add(1, { codigo: String(codigo), tipo: t.tipo });
    if (codigo === 8 && avisosRetry++ < 1) {
      console.log(`RetryInfo recebido: ${JSON.stringify(res.error.details)} -> ${atrasoPedido(res.error)} s`);
    }
    if (!TRANSITORIOS.has(codigo)) {
      falhas.add(true, t); // o agente pausaria
      if (avisos++ < 3) {
        console.warn(`falha definitiva: host=${host.nome} codigo=${codigo} erro=${JSON.stringify(res.error)}`);
      }
      return;
    }
    // Como o remote: espera o maior entre o seu backoff e o RetryInfo do central (ADR-0006).
    const backoff = Math.min(5 * 2 ** Math.min(tentativa, 6), 300) * (0.8 + Math.random() * 0.4);
    sleep(Math.max(backoff, atrasoPedido(res.error)));
  }
}

// Atraso de RetryInfo (google.rpc.RetryInfo) em segundos, ou 0. O k6 entrega os detalhes em JSON:
// "retryDelay" como texto ("3.2s") ou como {seconds, nanos}.
function atrasoPedido(erro) {
  for (const d of (erro && erro.details) || []) {
    const atraso = d.retryDelay || d.retry_delay;
    if (typeof atraso === 'string') {
      return parseFloat(atraso) || 0;
    }
    if (atraso && typeof atraso === 'object') {
      return Number(atraso.seconds || 0) + Number(atraso.nanos || 0) / 1e9;
    }
  }
  return 0;
}

function stat(id, quando) {
  return {
    sourceId: String(id), cpuPercent: 5 + Math.random() * 60, ramUsedMb: 2048, ramTotalMb: 8192,
    diskUsedGb: 40, diskTotalGb: 100, collectedAt: new Date(quando).toISOString(),
  };
}

const NIVEIS = ['LOG_LEVEL_INFO', 'LOG_LEVEL_WARN', 'LOG_LEVEL_ERROR', 'LOG_LEVEL_CRITICAL'];

function erro(id, quando) {
  return {
    sourceId: String(id), appName: 'app-carga', environment: 'carga',
    level: NIVEIS[id % NIVEIS.length],
    message: `falha simulada ${id}: timeout ao contactar o serviço de pagamentos`,
    metadataJson: '{"rota":"/encomendas","tentativa":1}',
    createdAt: new Date(quando).toISOString(),
  };
}

// Envia n erros criados no intervalo [fim - janelaMs, fim], os mais recentes primeiro.
function enviarErros(n, fim, janelaMs, fase) {
  for (let enviados = 0; enviados < n; enviados += LOTE) {
    const lote = [];
    for (let i = 0; i < Math.min(LOTE, n - enviados); i++) {
      const quando = fim - ((enviados + i) / Math.max(n, 1)) * janelaMs;
      lote.push(erro(proximoErro++, quando));
    }
    enviar('IngestErrors', { errors: lote }, lote.length, tags('errors', fase));
  }
}

function faseAtual() {
  const decorrido = (Date.now() - exec.scenario.startTime) / 1000;
  return CENARIO === 'noisy-neighbour' && decorrido >= INICIO_RAJADA_S && decorrido < INICIO_RAJADA_S + DURACAO_RAJADA_S
    ? 'rajada' : 'normal';
}

// ---------------------------------------------------------------- cenários contínuos (SC1, SC5)
export function hostContinuo() {
  iniciarHost();
  const fim = exec.scenario.startTime + duracaoMs(DURACAO);
  sleep(Math.random() * INTERVALO_ERROS_S); // os agentes não arrancam todos no mesmo segundo
  while (Date.now() < fim) {
    const inicio = Date.now();
    const fase = faseAtual();
    if (tick % TICKS_POR_STATS === 0) {
      enviar('IngestStats', { stats: [stat(proximoStat++, inicio)] }, 1, tags('stats', fase));
    }
    const taxa = host.perfil === 'rajada' && fase === 'rajada' ? TAXA_EM_RAJADA : TAXA[host.perfil] * MULT_LOGS;
    acumulado += taxa * INTERVALO_ERROS_S;
    const n = Math.floor(acumulado);
    acumulado -= n;
    enviarErros(n, inicio, INTERVALO_ERROS_S * 1000, fase);
    tick++;
    sleep(Math.max(0, Math.min(INTERVALO_ERROS_S - (Date.now() - inicio) / 1000, (fim - Date.now()) / 1000)));
  }
}

// ---------------------------------------------------------------- capacidade (SC3)
// A carga é a mesma com 1, 2 ou 3 instâncias; o que se mede é quantos registos o central confirma.
export function hostCapacidade() {
  iniciarHost();
  const fim = exec.scenario.startTime + duracaoMs(DURACAO);
  sleep(Math.random() * 2);
  while (Date.now() < fim) {
    enviarErros(LOTE, Date.now(), 1000, 'capacidade');
  }
}

function duracaoMs(texto) {
  const m = /^(\d+)(s|m|h)$/.exec(texto);
  if (!m) {
    throw new Error(`DURACAO inválida: ${texto}`);
  }
  return parseInt(m[1], 10) * { s: 1000, m: 60000, h: 3600000 }[m[2]];
}

// ---------------------------------------------------------------- recuperação (SC2)
// O central esteve 1 h em baixo: cada host tem 120 estatísticas e 1 h de erros pendentes, e
// todos começam a enviar ao mesmo tempo, o mais depressa que o central deixar.
export function hostComBacklog() {
  iniciarHost();
  const agora = Date.now();
  const hora = 3600 * 1000;
  const erros = Math.round(TAXA[host.perfil] * MULT_LOGS * 3600);
  backlog.add(120 + erros);
  for (let i = 0; i < 120; i += LOTE) {
    const lote = [];
    for (let j = i; j < Math.min(120, i + LOTE); j++) {
      lote.push(stat(proximoStat++, agora - (j / 120) * hora));
    }
    enviar('IngestStats', { stats: lote }, lote.length, tags('stats', 'recuperacao'));
  }
  enviarErros(erros, agora, hora, 'recuperacao');
  recuperacao.add(Date.now() - exec.scenario.startTime);
}

// ---------------------------------------------------------------- dashboard
export function setup() {
  const res = http.post(`${CENTRAL_HTTP}/login`, { email: __ENV.ADMIN_EMAIL, password: __ENV.ADMIN_PASSWORD },
    { redirects: 0 });
  const sessao = Object.values(res.cookies).flat()[0];
  if (!sessao) {
    throw new Error(`login no dashboard falhou (estado ${res.status})`);
  }
  return { cookie: `${sessao.name}=${sessao.value}` };
}

export function dashboard(dados) {
  http.get(`${CENTRAL_HTTP}/api/v1/dashboard/summary`, {
    headers: { Cookie: dados.cookie }, tags: { dashboard: 'sim', name: 'dashboard_summary' },
  });
}

export function handleSummary(data) {
  return { [`/results/${RESULTADO}.json`]: JSON.stringify(data, null, 2) };
}
