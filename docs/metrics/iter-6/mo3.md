# MO3: uma alteração de apresentação não toca em `services` nem `repositories`

**Cenário (relatório, cap. 4):** mudança de apresentação de uma página → 0 alterações em `services` e
`repositories`.

**Método (21/11/2026):** experiência controlada numa cópia do `monitor-central` (`main@7f62c12` mais as
alterações por commitar do Passo 9), descartada no fim. Duas alterações de apresentação típicas, escolhidas
antes de olhar para o código que as serve:

* **A, *dashboard*:** os incidentes abertos passam a ser o primeiro cartão; o cartão de erros passa a mostrar
  "N of M critical" em vez de "N critical" (no HTML inicial e na atualização a cada 15 s).
* **B, página de erros:** o nível passa a *badge* com uma cor por severidade; o ambiente passa a ter coluna
  própria.

Os testes unitários do central (os dos *handlers* desenham os *templates* reais) passaram sem alterações.

**Resultado:** 4 ficheiros, todos em `frontend/`; **0 ficheiros Go**, logo **0 em `services` e
`repositories`** (e 0 em `models` e `database`). MO3 cumpre-se.

| Ficheiro | Linhas |
|---|---|
| `frontend/js/dashboard.js` | +1 / −1 |
| `frontend/public/app.css` | +4 |
| `frontend/templates/dashboard.html` | +3 / −2 |
| `frontend/templates/errors.html` | +1 / −1 |

**Porque se cumpre, e porque continua a cumprir-se:** os dados que as páginas mostram já chegam inteiros aos
*templates* e ao JSON. As regras `depguard` (`central-handlers`, `central-services`) impedem que a
apresentação passe a depender do acesso a dados, ou que os serviços passem a desenhar páginas
(`templating`), e são verificadas em cada PR. **Limite da medida:** uma alteração que precise de um **dado
novo** (por exemplo, a última mensagem de cada *host* na página de *hosts*) já não é só apresentação e toca
nas camadas de baixo, por desenho.

**Porque não o histórico do git:** os *commits* do `monitor-central` são por iteração e juntam alterações de
várias naturezas (os 4 que tocam em `frontend/` tocam também noutras camadas por outras razões), por isso não
isolam uma mudança de apresentação.

## Diff da experiência
```diff
diff --git a/frontend/js/dashboard.js b/frontend/js/dashboard.js
index 97cba44..5a02149 100644
--- a/frontend/js/dashboard.js
+++ b/frontend/js/dashboard.js
@@ -47,7 +47,7 @@
       const summaryResponse = await fetch('/api/v1/dashboard/summary', {signal});
       if (summaryResponse.ok) {
         const summary = await summaryResponse.json(); if (signal.aborted) return;
-        text('summary-hosts', `${summary.hosts_online} / ${summary.hosts_total}`); text('summary-errors', summary.errors_today); text('summary-critical', `${summary.critical_errors_today} critical`); text('summary-alerts', summary.firing_alerts); text('summary-cpu', `${number(summary.average_cpu)}%`);
+        text('summary-hosts', `${summary.hosts_online} / ${summary.hosts_total}`); text('summary-errors', summary.errors_today); text('summary-critical', `${summary.critical_errors_today} of ${summary.errors_today} critical`); text('summary-alerts', summary.firing_alerts); text('summary-cpu', `${number(summary.average_cpu)}%`);
         text('system-status', summary.hosts_total > 0 && summary.hosts_online === summary.hosts_total && summary.firing_alerts === 0 ? 'All systems operational' : 'Systems require attention');
       }
     } catch (error) { if (error.name !== 'AbortError') { status.textContent = 'Unable to refresh. Check your connection; retrying in 15 seconds.'; } }
diff --git a/frontend/public/app.css b/frontend/public/app.css
index 7dc749a..fc52928 100644
--- a/frontend/public/app.css
+++ b/frontend/public/app.css
@@ -1 +1,5 @@
 :root{color-scheme:dark}body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a,button{touch-action:manipulation}button,a,input,select,textarea{outline-offset:4px}button:focus-visible,a:focus-visible{outline:2px solid #a5b4fc}.nav-link{display:block;padding:.65rem .8rem;border-radius:.5rem;color:#b8b8b8}.nav-link:hover,.nav-link.active{background:#242333;color:#c7d2fe}.panel{background:#141414;border:1px solid #2a2a2a;border-radius:.75rem;padding:1.25rem}.field{display:block;width:100%;padding:.65rem .8rem;border:1px solid #3b3b3b;border-radius:.5rem;background:#1a1a1a;color:#e8e8e8}.label{display:block;margin-bottom:.35rem;font-size:.875rem;color:#c2c2c2}.button{display:inline-block;padding:.6rem 1rem;background:#4f46e5;color:white;border-radius:.5rem;cursor:pointer}.button.secondary{background:#262626}.button.danger{background:#991b1b}.muted{color:#a3a3a3}table{width:100%;text-align:left;border-collapse:collapse}th,td{padding:.8rem;border-bottom:1px solid #2a2a2a}th{color:#a3a3a3;font-size:.875rem}dialog{margin:auto;background:#141414;color:#e8e8e8;border:1px solid #444;border-radius:.75rem;padding:1.5rem;width:min(36rem,calc(100% - 2rem));max-height:90vh;overflow-y:auto}dialog::backdrop{background:#000b}.chart{width:100%;height:180px}.chart text{fill:#a3a3a3;font-size:10px}.chart line{stroke:#333}.notice{padding:1rem;border:1px solid #4f46e5;border-radius:.5rem;background:#1e1b4b}.error-notice{padding:1rem;border:1px solid #b91c1c;border-radius:.5rem;background:#450a0a}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}input[type=checkbox]{width:1rem;height:1rem} @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
+/* MO3 experiment: one colour per severity on the error log page. */
+.badge{display:inline-block;padding:.1rem .5rem;border-radius:.5rem;font-size:.75rem;font-weight:600}
+.level-INFO{background:#e0f2fe;color:#075985}.level-WARN{background:#fef3c7;color:#92400e}
+.level-ERROR{background:#fee2e2;color:#991b1b}.level-CRITICAL,.level-PANIC{background:#7f1d1d;color:#fff}
diff --git a/frontend/templates/dashboard.html b/frontend/templates/dashboard.html
index d6b0f4f..9bc52a1 100644
--- a/frontend/templates/dashboard.html
+++ b/frontend/templates/dashboard.html
@@ -1,9 +1,10 @@
 {{define "main"}}
 <div class="flex flex-wrap justify-between items-center gap-4 mb-6"><div><h1 class="text-3xl font-bold">Dashboard</h1><p class="muted mt-1">System overview across all monitored hosts.</p></div><p id="system-status" class="notice">{{if .AllSystemsOperational}}All systems operational{{else}}Systems require attention{{end}}</p></div>
 <div class="grid sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
-<section class="panel"><h2 class="muted">Hosts online</h2><p class="text-3xl font-bold mt-2" id="summary-hosts">{{.HostsOnline}} / {{.HostsTotal}}</p></section>
-<section class="panel"><h2 class="muted">Errors today</h2><p class="text-3xl font-bold mt-2" id="summary-errors">{{.ErrorsToday}}</p><p class="muted text-sm" id="summary-critical">{{.CriticalErrorsToday}} critical</p></section>
 <section class="panel"><h2 class="muted">Open incidents</h2><p class="text-3xl font-bold mt-2" id="summary-alerts">{{.FiringAlerts}}</p><p class="muted text-sm">Includes acknowledged incidents</p></section>
+<section class="panel"><h2 class="muted">Hosts online</h2><p class="text-3xl font-bold mt-2" id="summary-hosts">{{.HostsOnline}} / {{.HostsTotal}}</p></section>
+<section class="panel"><h2 class="muted">Errors today</h2><p class="text-3xl font-bold mt-2" id="summary-errors">{{.ErrorsToday}}</p><p class="muted text-sm" id="summary-critical">{{.CriticalErrorsToday}} of {{.ErrorsToday}} critical</p></section>
+
 <section class="panel"><h2 class="muted">Average latest CPU</h2><p class="text-3xl font-bold mt-2" id="summary-cpu">{{printf "%.1f" .AverageCPU}}%</p></section>
 </div>
 <section class="panel"><div class="flex flex-wrap justify-between gap-4 mb-6"><h2 class="text-xl font-semibold">Host metrics</h2><div class="flex gap-3"><label><span class="sr-only">History range</span><select class="field" id="range-selector"><option value="24h">24 hours</option><option value="1w">1 week</option><option value="1m">1 month</option></select></label><label><span class="sr-only">Host</span><select class="field" id="host-selector"><option value="">Loading hosts…</option></select></label></div></div>
diff --git a/frontend/templates/errors.html b/frontend/templates/errors.html
index f13a18b..0741f65 100644
--- a/frontend/templates/errors.html
+++ b/frontend/templates/errors.html
@@ -1,3 +1,3 @@
 {{define "main"}}<h1 class="text-3xl font-bold mb-2">Error logs</h1><p class="muted mb-6">{{.TotalErrors}}{{if .TotalCapped}}+{{end}} entries across monitored applications.</p>
 {{$filters := .Filters}}<form method="get" action="/errors" class="panel grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6"><label class="label">Host<select class="field" name="host_id"><option value="">All hosts</option>{{range .Hosts}}<option value="{{.ID}}" {{if eq $filters.HostID .ID}}selected{{end}}>{{.Name}}</option>{{end}}</select></label><label class="label">Level<select class="field" name="level"><option value="">All levels</option>{{range .Levels}}<option value="{{.}}" {{if eq $filters.Level .}}selected{{end}}>{{.}}</option>{{end}}</select></label><label class="label">Application<select class="field" name="app_name"><option value="">All applications</option>{{range .AppNames}}<option {{if eq $filters.AppName .}}selected{{end}}>{{.}}</option>{{end}}</select></label><label class="label">Message<input class="field" name="search" value="{{.Filters.Search}}" maxlength="500" placeholder="Search messages"></label><div class="flex gap-3"><button class="button">Apply filters</button><a class="button secondary" href="/errors">Clear</a></div></form>
-<section class="panel overflow-x-auto"><table><thead><tr><th>Level</th><th>Host / application</th><th>Message</th><th>Time</th></tr></thead><tbody>{{range .Errors}}<tr><td>{{.Level}}</td><td>{{.HostName}}<br><span class="muted text-sm">{{.AppName}} · {{.Environment}}</span></td><td><details><summary class="break-words">{{.Message}}</summary><div class="mt-4 text-sm"><p>Record {{.ID}}</p><h3 class="mt-3 muted">Stack trace</h3><pre>{{if .StackTrace}}{{.StackTrace}}{{else}}No stack trace{{end}}</pre><h3 class="mt-3 muted">Metadata</h3><pre>{{.MetadataText}}</pre></div></details></td><td class="whitespace-nowrap text-sm muted">{{.CreatedAtDisplay}}</td></tr>{{else}}<tr><td colspan="4">No entries match these filters.</td></tr>{{end}}</tbody></table>{{if .TotalPages}}<div class="flex justify-between items-center mt-5"><p class="muted">Page {{.Page}} of {{.TotalPages}}{{if .TotalCapped}}+{{end}}</p><div class="flex gap-3">{{if .PreviousPageURL}}<a class="button secondary" href="{{.PreviousPageURL}}">Previous</a>{{end}}{{if .NextPageURL}}<a class="button secondary" href="{{.NextPageURL}}">Next</a>{{end}}</div></div>{{end}}</section>{{end}}
+<section class="panel overflow-x-auto"><table><thead><tr><th>Level</th><th>Host / application</th><th>Environment</th><th>Message</th><th>Time</th></tr></thead><tbody>{{range .Errors}}<tr><td><span class="badge level-{{.Level}}">{{.Level}}</span></td><td>{{.HostName}}<br><span class="muted text-sm">{{.AppName}}</span></td><td class="text-sm">{{.Environment}}</td><td><details><summary class="break-words">{{.Message}}</summary><div class="mt-4 text-sm"><p>Record {{.ID}}</p><h3 class="mt-3 muted">Stack trace</h3><pre>{{if .StackTrace}}{{.StackTrace}}{{else}}No stack trace{{end}}</pre><h3 class="mt-3 muted">Metadata</h3><pre>{{.MetadataText}}</pre></div></details></td><td class="whitespace-nowrap text-sm muted">{{.CreatedAtDisplay}}</td></tr>{{else}}<tr><td colspan="5">No entries match these filters.</td></tr>{{end}}</tbody></table>{{if .TotalPages}}<div class="flex justify-between items-center mt-5"><p class="muted">Page {{.Page}} of {{.TotalPages}}{{if .TotalCapped}}+{{end}}</p><div class="flex gap-3">{{if .PreviousPageURL}}<a class="button secondary" href="{{.PreviousPageURL}}">Previous</a>{{end}}{{if .NextPageURL}}<a class="button secondary" href="{{.NextPageURL}}">Next</a>{{end}}</div></div>{{end}}</section>{{end}}
```
