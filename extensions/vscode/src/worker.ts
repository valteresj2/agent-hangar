/* O posto de trabalho de um Digital employee no VS Code: o laço do worker (heartbeat → rodadas AG-UI → ferramentas
   aqui → resultado) e as ferramentas em si. A alçada é da plataforma: o que muda algo (arquivo, comando, publicação)
   pergunta antes no /gate; o que precisa de decisão para a tarefa até alguém decidir no portal, no app ou no Slack. */
import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import {
  AguiMessage, compact, decisionResult, GATED, gateArgs, HangarError, tail, toAguiMessages, WorkerClient, WorkerTask, WORKSTATION_TOOLS,
} from './core';

const MAX_ROUNDS = 400;  // por vez que a tarefa vem do heartbeat; depois ela volta à fila e segue (a plataforma confere o orçamento)
const IGNORE = new Set(['.git', '.venv', 'venv', 'node_modules', '__pycache__', '.ipynb_checkpoints', '.mypy_cache', '.pytest_cache']);
const WIN = process.platform === 'win32';

interface Call { id: string; name: string; input: Record<string, unknown>; raw: string }
/** serverSeen: quantas mensagens da conversa da plataforma já entraram aqui (as novas — a decisão com o texto de
 *  quem decidiu, um comentário na tarefa — entram quando a tarefa volta). */
interface TaskState { messages: AguiMessage[]; pending: Call[]; waiting?: { callId: string; request?: number }; serverSeen?: number }

export interface WorkstationOptions {
  base: string; token: string; slug: string; name: string; root: string; version: string; storage: vscode.Uri;
  onStatus(text: string, tooltip?: string): void;
  onRevoked(): void;
}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

export class Workstation {
  private stopped = false;
  private abort = new AbortController();
  private readonly out: vscode.OutputChannel;
  private pty?: { term: vscode.Terminal; write: vscode.EventEmitter<string> };
  private readonly client: WorkerClient;

  constructor(private readonly o: WorkstationOptions) {
    this.out = vscode.window.createOutputChannel(`Agent Hangar — ${o.name}`);
    this.client = new WorkerClient(o.base, o.token);
  }

  start() { void this.loop(); }

  dispose() {
    this.stopped = true;
    this.abort.abort();
    this.out.dispose();
    this.pty?.term.dispose();
  }

  // ------------------------------------------------------------------ laço do worker
  private info() {
    return { name: `VS Code (${os.hostname()})`, version: this.o.version, folder: path.basename(this.o.root), os: `${os.platform()} ${os.release()}` };
  }

  private async loop() {
    this.out.appendLine(`${this.o.name} trabalha nesta pasta: ${this.o.root}`);
    while (!this.stopped) {
      try {
        const hb = await this.client.heartbeat(this.info());
        if (hb.task) {
          await this.work(hb.task);
          continue;
        }
        this.o.onStatus(`${this.o.name}: aguardando tarefas`, `Status do funcionário: ${hb.status}`);
        await sleep((hb.next_heartbeat_s || 10) * 1000);
      } catch (e) {
        if (this.stopped) return;
        if (e instanceof HangarError && e.status === 401) {
          this.out.appendLine('O token do posto de trabalho não vale mais (revogado ou o funcionário voltou para a plataforma).');
          this.o.onRevoked();
          return;
        }
        this.out.appendLine(`Sem contato com a plataforma: ${(e as Error).message}. Tento de novo em 15 s.`);
        await sleep(15_000);
      }
    }
  }

  private stateFile(id: number) { return vscode.Uri.joinPath(this.o.storage, `task-${id}.json`).fsPath; }

  private load(id: number): TaskState | undefined {
    try { return JSON.parse(fs.readFileSync(this.stateFile(id), 'utf8')) as TaskState; } catch { return undefined; }
  }

  private save(id: number, s: TaskState) {
    fs.mkdirSync(this.o.storage.fsPath, { recursive: true });
    fs.writeFileSync(this.stateFile(id), JSON.stringify(s));
  }

  private context(task: WorkerTask) {
    const shell = WIN ? 'Windows PowerShell 5.1 (use ; entre comandos, não &&)' : 'sh';
    return [
      { description: 'Posto de trabalho', value: `Você está trabalhando no VS Code da pessoa (${os.platform()} ${os.release()}), na pasta ${this.o.root}. `
        + `Terminal: ${shell}. Caminhos relativos partem dessa pasta. Use as ferramentas do posto (list_files, read_file, search_files, `
        + 'write_file, edit_file, run_command, publish_github) para fazer o trabalho de verdade e conferir cada resultado antes de seguir. '
        + 'Comandos longos: rode e espere (timeout_s). Nunca leia nem exponha segredos (.env, chaves).' },
      { description: 'Tarefa', value: `#${task.id} ${task.title} — ${task.url}` },
    ];
  }

  private async work(task: WorkerTask) {
    const saved = this.load(task.id);
    const s: TaskState = saved ?? { messages: toAguiMessages(task.messages), pending: [], serverSeen: task.messages.length };
    // o que chegou na conversa da plataforma enquanto a tarefa estava fora daqui
    const arrived = saved ? task.messages.slice(saved.serverSeen ?? task.messages.length).filter(m => m.role === 'user') : [];
    s.serverSeen = task.messages.length;
    this.out.show(true);
    this.out.appendLine(`\n=== Tarefa #${task.id}: ${task.title} (vez ${task.run}) ===`);
    // quem dá notícia não está preso: o prazo da rodada recomeça mesmo durante um comando longo, e o posto continua
    // "online" na tela do funcionário (heartbeat sem pedir outra tarefa)
    const keepalive = setInterval(() => {
      void this.client.progress(task.id).catch(() => undefined);
      void this.client.heartbeat(this.info(), false).catch(() => undefined);
    }, 60_000);
    try {
      const handled = s.waiting?.request;
      if (s.pending.length && (await this.runCalls(task, s, arrived)) === 'waiting') return;
      const said = new Set(s.messages.map(m => m.content));
      for (const m of arrived) {
        // a decisão da ação que acabou de ser tratada já está no resultado dela (e um "execute agora" repetiria a ação)
        if (handled !== undefined && m.content.startsWith(`DECISÃO #${handled}:`)) continue;
        if (!said.has(m.content)) s.messages.push({ id: `u-${Date.now()}-${s.messages.length}`, role: 'user', content: m.content });
      }
      this.save(task.id, s);
      for (let round = 1; round <= MAX_ROUNDS && !this.stopped; round++) {
        this.o.onStatus(`${this.o.name}: #${task.id} rodada ${round}`, task.title);
        let text = '';
        let state: { status: string } | undefined;
        const calls: Call[] = [];
        const body = { threadId: `task-${task.id}`, runId: `r-${Date.now()}`, messages: compact(s.messages),
          tools: WORKSTATION_TOOLS, context: this.context(task) };
        for await (const ev of this.client.agui(task.id, body, this.abort.signal)) {
          if (ev.type === 'text') { text += ev.text; this.out.append(ev.text); }
          else if (ev.type === 'server_tool') this.out.appendLine(`\n[plataforma] ${ev.name}`);
          else if (ev.type === 'client_call') calls.push(ev);
          else if (ev.type === 'task') state = ev.value;
          else if (ev.type === 'error') throw new Error(ev.message);
        }
        if (text) this.out.appendLine('');
        s.messages.push({ id: `a-${Date.now()}`, role: 'assistant', content: text,
          ...(calls.length ? { toolCalls: calls.map(c => ({ id: c.id, type: 'function' as const, function: { name: c.name, arguments: c.raw } })) } : {}) });
        s.pending = calls;
        this.save(task.id, s);
        if (state?.status === 'waiting_human') {  // uma ferramenta da plataforma parou na alçada
          this.out.appendLine('Aguardando uma decisão (Decisões, no app ou no portal). A tarefa volta sozinha depois.');
          return;
        }
        if (!calls.length) {
          await this.client.result(task.id, 'done', text.trim() || '(sem texto final)');
          fs.rmSync(this.stateFile(task.id), { force: true });
          this.out.appendLine(`=== Tarefa #${task.id} entregue ===`);
          void vscode.window.showInformationMessage(`${this.o.name} entregou a tarefa #${task.id}: ${task.title}`);
          return;
        }
        if ((await this.runCalls(task, s)) === 'waiting') return;
        await this.client.progress(task.id, calls.map(c => `${c.name} ${summary(c)}`).join(' · ').slice(0, 900)).catch(() => undefined);
      }
      if (!this.stopped) await this.client.result(task.id, 'waiting');  // volta para a fila e segue na próxima vez
    } catch (e) {
      const msg = (e as Error).message;
      this.out.appendLine(`\nA rodada parou: ${msg}`);
      if (e instanceof HangarError && e.status === 409) {
        if (/orçamento|budget/i.test(msg)) await this.client.result(task.id, 'failed', '', msg).catch(() => undefined);
        return;  // a tarefa não está mais com este posto (decisão pendente, cancelada) — o heartbeat traz quando voltar
      }
      if (!this.stopped) {
        await this.client.result(task.id, 'waiting').catch(() => undefined);  // volta para a fila; a conversa fica salva aqui
        await sleep(10_000);
      }
    } finally {
      clearInterval(keepalive);
    }
  }

  /** Executa as chamadas pendentes, cada uma depois da alçada. 'waiting': a tarefa saiu do posto até alguém decidir. */
  private async runCalls(task: WorkerTask, s: TaskState, arrived: { content: string }[] = []): Promise<'ok' | 'waiting'> {
    for (const call of s.pending) {
      if (s.messages.some(m => m.role === 'tool' && m.toolCallId === call.id)) continue;
      let content: string;
      const decided = s.waiting?.callId === call.id ? task.decisions.find(d => d.id === s.waiting?.request) : undefined;
      const refused = decisionResult(decided, arrived);  // recusa ou instrução: o texto de quem decidiu
      if (refused !== undefined) {
        content = refused;
      } else if (GATED.has(call.name)) {
        const g = await this.client.gate(task.id, `vscode:${call.name}`, gateArgs(call.name, call.input));
        if (g.status === 'waiting') {
          s.waiting = { callId: call.id, request: g.request_id };
          this.save(task.id, s);
          this.out.appendLine(`\n[alçada] ${call.name} ${summary(call)} precisa de aprovação — veja Decisões no app ou no portal.`);
          this.o.onStatus(`${this.o.name}: aguardando decisão (#${task.id})`, `${call.name} ${summary(call)}`);
          return 'waiting';
        }
        if (g.status === 'denied') content = `NEGADO pela alçada: ${g.message ?? ''}. Não tente contornar; siga sem essa ação ou explique.`;
        else if (g.status === 'simulated') content = '(modo sombra) ação simulada, não executada.';
        else content = await this.exec(call);
      } else {
        content = await this.exec(call);
      }
      s.waiting = undefined;
      s.messages.push({ id: `t-${call.id}`, role: 'tool', toolCallId: call.id, content });
      this.save(task.id, s);
    }
    s.pending = [];
    this.save(task.id, s);
    return 'ok';
  }

  // ------------------------------------------------------------------ ferramentas
  private resolve(p: unknown): string {
    const full = path.resolve(this.o.root, String(p ?? '.'));
    const rel = path.relative(this.o.root, full);
    if (rel.startsWith('..') || path.isAbsolute(rel)) throw new Error(`fora da pasta de trabalho: ${p}`);
    return full;
  }

  private async exec(call: Call): Promise<string> {
    this.out.appendLine(`\n[${call.name}] ${summary(call)}`);
    try {
      const i = call.input;
      switch (call.name) {
        case 'list_files': return this.listFiles(this.resolve(i.path), Math.min(Number(i.depth ?? 2) || 2, 5));
        case 'read_file': return this.readFile(this.resolve(i.path), Number(i.start_line ?? 0), Number(i.end_line ?? 0));
        case 'search_files': return await this.search(String(i.pattern ?? ''), String(i.glob ?? '**/*'));
        case 'write_file': return await this.writeFile(this.resolve(i.path), String(i.content ?? ''));
        case 'edit_file': return this.editFile(this.resolve(i.path), String(i.old_string ?? ''), String(i.new_string ?? ''));
        case 'run_command': return await this.run(String(i.command ?? ''), this.resolve(i.cwd), Math.min(Number(i.timeout_s ?? 900) || 900, 7200));
        case 'publish_github': return await this.publish(String(i.repo ?? ''), String(i.description ?? ''), i.public !== false, String(i.message ?? ''));
        default: return `ferramenta desconhecida: ${call.name}`;
      }
    } catch (e) {
      const msg = `erro: ${(e as Error).message}`;
      this.out.appendLine(msg);
      return msg;
    }
  }

  private listFiles(dir: string, depth: number): string {
    const lines: string[] = [];
    const walk = (d: string, level: number) => {
      if (lines.length >= 400) return;
      for (const ent of fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
        if (IGNORE.has(ent.name)) continue;
        const full = path.join(d, ent.name);
        const rel = path.relative(this.o.root, full).replace(/\\/g, '/');
        if (ent.isDirectory()) {
          lines.push(`${rel}/`);
          if (level < depth) walk(full, level + 1);
        } else {
          lines.push(`${rel} (${fs.statSync(full).size} bytes)`);
        }
        if (lines.length >= 400) { lines.push('…(lista cortada em 400)'); return; }
      }
    };
    walk(dir, 1);
    return lines.join('\n') || '(pasta vazia)';
  }

  private readFile(file: string, start: number, end: number): string {
    const text = fs.readFileSync(file, 'utf8');
    const body = start || end ? text.split('\n').slice(Math.max(0, start - 1), end || undefined).join('\n') : text;
    return body.length > 20_000 ? `${body.slice(0, 20_000)}\n…[cortado: ${body.length} caracteres; leia por trechos]` : body;
  }

  private async search(pattern: string, glob: string): Promise<string> {
    const rx = new RegExp(pattern);
    const files = await vscode.workspace.findFiles(new vscode.RelativePattern(this.o.root, glob),
      '{**/.git/**,**/.venv/**,**/venv/**,**/node_modules/**,**/__pycache__/**}', 3000);
    const hits: string[] = [];
    for (const f of files) {
      if (fs.statSync(f.fsPath).size > 1_000_000) continue;
      fs.readFileSync(f.fsPath, 'utf8').split('\n').forEach((line, n) => {
        if (hits.length < 100 && rx.test(line)) hits.push(`${path.relative(this.o.root, f.fsPath).replace(/\\/g, '/')}:${n + 1}: ${line.trim().slice(0, 200)}`);
      });
      if (hits.length >= 100) break;
    }
    return hits.join('\n') || '(nada encontrado)';
  }

  private async writeFile(file: string, content: string): Promise<string> {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, content, 'utf8');
    if (content.length < 200_000) {
      await vscode.window.showTextDocument(vscode.Uri.file(file), { preview: true, preserveFocus: true }).then(undefined, () => undefined);
    }
    return `ok: ${path.relative(this.o.root, file)} (${content.length} caracteres)`;
  }

  private editFile(file: string, oldS: string, newS: string): string {
    const text = fs.readFileSync(file, 'utf8');
    const n = oldS ? text.split(oldS).length - 1 : 0;
    if (n !== 1) return `erro: o trecho aparece ${n} vezes (precisa aparecer exatamente 1)`;
    fs.writeFileSync(file, text.replace(oldS, () => newS), 'utf8');
    return `ok: ${path.relative(this.o.root, file)} editado`;
  }

  private terminal() {
    if (!this.pty || this.pty.term.exitStatus) {
      const write = new vscode.EventEmitter<string>();
      const term = vscode.window.createTerminal({ name: `Hangar · ${this.o.name}`, pty: {
        onDidWrite: write.event, open: () => undefined, close: () => undefined,
      } });
      this.pty = { term, write };
    }
    this.pty.term.show(true);
    return this.pty.write;
  }

  private run(command: string, cwd: string, timeoutS: number): Promise<string> {
    const write = this.terminal();
    write.fire(`\r\n\x1b[36m${path.relative(this.o.root, cwd) || '.'}>\x1b[0m ${command.replace(/\n/g, '\r\n')}\r\n`);
    const [exe, args] = WIN
      ? ['powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
          `$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; & { ${command} }; `
          + '$ok=$?; if ($LASTEXITCODE) { exit $LASTEXITCODE }; if (-not $ok) { exit 1 }']]
      : ['/bin/sh', ['-c', command]];
    return new Promise(resolve => {
      const t0 = Date.now();
      let output = '';
      const child = cp.spawn(exe, args, { cwd, env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' }, windowsHide: true });
      const onData = (b: Buffer) => {
        const s = b.toString('utf8');
        output = (output + s).slice(-200_000);
        write.fire(s.replace(/\r?\n/g, '\r\n'));
      };
      child.stdout.on('data', onData);
      child.stderr.on('data', onData);
      let killed = false;
      const timer = setTimeout(() => {
        killed = true;
        if (WIN && child.pid) cp.exec(`taskkill /pid ${child.pid} /T /F`);
        else child.kill('SIGKILL');
      }, timeoutS * 1000);
      const abort = () => { killed = true; if (WIN && child.pid) cp.exec(`taskkill /pid ${child.pid} /T /F`); else child.kill('SIGKILL'); };
      this.abort.signal.addEventListener('abort', abort, { once: true });
      child.on('close', code => {
        clearTimeout(timer);
        this.abort.signal.removeEventListener('abort', abort);
        const secs = Math.round((Date.now() - t0) / 1000);
        write.fire(`\x1b[90m[saída ${code}${killed ? ', interrompido' : ''} em ${secs}s]\x1b[0m\r\n`);
        resolve(`código de saída: ${code}${killed ? ` (interrompido: passou de ${timeoutS}s)` : ''} · ${secs}s\n${tail(output)}`);
      });
      child.on('error', e => { clearTimeout(timer); resolve(`erro ao rodar: ${e.message}`); });
    });
  }

  private git(args: string[], extra: string[] = []): Promise<{ code: number; out: string }> {
    return new Promise(resolve => {
      cp.execFile('git', [...extra, ...args], { cwd: this.o.root, maxBuffer: 20_000_000 }, (err, stdout, stderr) => {
        resolve({ code: err ? (typeof (err as { code?: unknown }).code === 'number' ? (err as { code: number }).code : 1) : 0, out: `${stdout}${stderr}`.trim() });
      });
    });
  }

  /** Cria o repositório (se não existir) na conta do GitHub com que a pessoa entrou no VS Code e publica a pasta.
   *  O token fica com o VS Code: vai só no cabeçalho do push, nunca na URL, no remote ou na conversa. */
  private async publish(repo: string, description: string, isPublic: boolean, message: string): Promise<string> {
    if (!/^[A-Za-z0-9._-]{1,100}$/.test(repo)) return 'erro: nome de repositório inválido (letras, números, . _ -)';
    const session = await vscode.authentication.getSession('github', ['repo'], { createIfNone: true });
    const gh = (p: string, init: RequestInit = {}) => fetch(`https://api.github.com${p}`, { ...init, headers: {
      Authorization: `Bearer ${session.accessToken}`, Accept: 'application/vnd.github+json', 'User-Agent': 'agent-hangar-vscode',
      'X-GitHub-Api-Version': '2022-11-28', ...(init.body ? { 'Content-Type': 'application/json' } : {}) } });
    const me = await (await gh('/user')).json() as { login: string; id: number; name?: string };
    let info = await gh(`/repos/${me.login}/${repo}`);
    if (info.status === 404) {
      info = await gh('/user/repos', { method: 'POST', body: JSON.stringify({ name: repo, description, private: !isPublic }) });
      if (!info.ok) return `erro ao criar o repositório: ${info.status} ${await info.text()}`;
    } else if (!info.ok) {
      return `erro ao consultar o repositório: ${info.status}`;
    }
    const r = await info.json() as { html_url: string; clone_url: string; private: boolean };
    const write = this.terminal();
    write.fire(`\r\n\x1b[36mgit\x1b[0m publicar em ${r.html_url}\r\n`);
    if (!fs.existsSync(path.join(this.o.root, '.git'))) await this.git(['init', '-b', 'main']);
    const hasIdentity = (await this.git(['config', 'user.email'])).out !== '';
    const who = hasIdentity ? [] : ['-c', `user.name=${me.name || me.login}`, '-c', `user.email=${me.id}+${me.login}@users.noreply.github.com`];
    await this.git(['add', '-A']);
    const commit = await this.git(['commit', '-m', message || 'Resultado do trabalho'], who);
    if (commit.code !== 0 && !/nothing to commit|nada a submeter/i.test(commit.out)) return `erro no commit: ${tail(commit.out, 2000)}`;
    if ((await this.git(['remote', 'get-url', 'origin'])).code !== 0) await this.git(['remote', 'add', 'origin', r.clone_url]);
    const auth = Buffer.from(`x-access-token:${session.accessToken}`).toString('base64');
    const push = await this.git(['push', '-u', 'origin', 'HEAD:main'],
      ['-c', 'credential.helper=', '-c', `http.https://github.com/.extraheader=AUTHORIZATION: basic ${auth}`]);
    write.fire(`${push.out.replace(/\r?\n/g, '\r\n')}\r\n`);
    if (push.code !== 0) return `erro no push: ${tail(push.out, 2000)}`;
    const sha = (await this.git(['rev-parse', '--short', 'HEAD'])).out;
    return `publicado: ${r.html_url} (${r.private ? 'privado' : 'público'}, branch main, commit ${sha})`;
  }
}

function summary(c: Call): string {
  const i = c.input;
  const v = c.name === 'run_command' ? i.command : c.name === 'publish_github' ? i.repo : i.path ?? i.pattern ?? '';
  return String(v ?? '').replace(/\s+/g, ' ').slice(0, 160);
}
