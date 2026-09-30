/* Agent Hangar para VS Code: os agentes da empresa no seletor de modelos do chat (modo agente de código — o chat do
   VS Code executa arquivos e terminal localmente, com a sua aprovação) e o MCP da plataforma para criar e editar
   agentes sem sair do editor. Login pelo portal (SSO ou conta local) com PKCE; nada de colar chave. */
import * as os from 'os';
import * as vscode from 'vscode';
import {
  Env, exchangeCode, HangarAgent, HangarClient, HangarError, pkce, toOpenAIMessages, toOpenAITools,
} from './core';

const SECRET = 'agentHangar.token';
const KEY_ID = 'agentHangar.keyId';
const USER = 'agentHangar.user';

interface HangarModel extends vscode.LanguageModelChatInformation { slug: string }

let pending: { verifier: string; state: string; base: string } | undefined;

function cfg() {
  const c = vscode.workspace.getConfiguration('agentHangar');
  return { base: (c.get<string>('url') || 'http://localhost:8090').replace(/\/$/, ''), env: (c.get<string>('environment') || 'prod') as Env };
}

export function activate(ctx: vscode.ExtensionContext) {
  const changedModels = new vscode.EventEmitter<void>();
  const changedMcp = new vscode.EventEmitter<void>();
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
  status.command = 'agentHangar.menu';
  ctx.subscriptions.push(changedModels, changedMcp, status);

  const token = () => ctx.secrets.get(SECRET);
  const client = async () => {
    const t = await token();
    return t ? new HangarClient(cfg().base, t) : undefined;
  };
  const refreshStatus = async () => {
    const user = ctx.globalState.get<string>(USER);
    status.text = user ? `$(rocket) Hangar: ${user}` : '$(rocket) Hangar: entrar';
    status.tooltip = user ? `Agent Hangar (${cfg().base}, ${cfg().env})` : 'Conectar ao Agent Hangar';
    status.show();
  };
  const changed = () => { changedModels.fire(); changedMcp.fire(); void refreshStatus(); };

  // ------------------------------------------------------------------ login (portal + PKCE)
  const signIn = async (baseOverride?: string) => {
    let base = baseOverride || cfg().base;
    if (!baseOverride) {
      const typed = await vscode.window.showInputBox({ title: 'Agent Hangar', prompt: 'Endereço do Agent Hangar', value: base, ignoreFocusOut: true });
      if (!typed) return;
      base = typed.replace(/\/$/, '');
    }
    if (base !== cfg().base) await vscode.workspace.getConfiguration('agentHangar').update('url', base, vscode.ConfigurationTarget.Global);
    const p = pkce();
    pending = { verifier: p.verifier, state: p.state, base };
    const q = new URLSearchParams({ challenge: p.challenge, state: p.state, device: `VS Code em ${os.hostname()}` });
    await vscode.env.openExternal(vscode.Uri.parse(`${base}/app/#/vscode?${q}`));
    vscode.window.showInformationMessage('Confirme a conexão no navegador (portal do Agent Hangar). O VS Code volta sozinho.');
  };

  ctx.subscriptions.push(vscode.window.registerUriHandler({
    async handleUri(uri: vscode.Uri) {
      const q = new URLSearchParams(uri.query);
      if (uri.path === '/signin') {  // "Abrir no VS Code" no portal: já traz o endereço
        await signIn(q.get('url') || undefined);
        return;
      }
      if (uri.path !== '/auth') return;
      if (!pending || q.get('state') !== pending.state) {
        vscode.window.showErrorMessage('Agent Hangar: conexão expirada ou de outra janela — comece de novo em "Agent Hangar: Entrar".');
        return;
      }
      try {
        const r = await exchangeCode(pending.base, q.get('code') || '', pending.verifier);
        await ctx.secrets.store(SECRET, r.token);
        await ctx.globalState.update(KEY_ID, r.key_id);
        await ctx.globalState.update(USER, r.user.name || r.user.email);
        pending = undefined;
        changed();
        vscode.window.showInformationMessage(`Agent Hangar: conectado como ${r.user.name || r.user.email}. Os seus agentes estão no seletor de modelos do chat.`);
      } catch (e) {
        vscode.window.showErrorMessage(`Agent Hangar: ${(e as Error).message}`);
      }
    },
  }));

  const signOut = async () => {
    const c = await client();
    const id = ctx.globalState.get<number>(KEY_ID);
    if (c && id) await c.revokeKey(id).catch(() => undefined);  // a chave deixa de valer no servidor também
    await ctx.secrets.delete(SECRET);
    await ctx.globalState.update(KEY_ID, undefined);
    await ctx.globalState.update(USER, undefined);
    changed();
    vscode.window.showInformationMessage('Agent Hangar: desconectado (a chave foi revogada).');
  };

  // ------------------------------------------------------------------ agentes como modelos do chat
  const provider: vscode.LanguageModelChatProvider<HangarModel> = {
    onDidChangeLanguageModelChatInformation: changedModels.event,
    async provideLanguageModelChatInformation(options) {
      const c = await client();
      if (!c) {
        if (!options.silent) void vscode.commands.executeCommand('agentHangar.signIn');
        return [];
      }
      const { env } = cfg();
      try {
        const agents = await c.usableAgents(env);
        return agents.map((a: HangarAgent): HangarModel => ({
          id: `${a.slug}@${env}`, slug: a.slug, name: env === 'stage' ? `${a.name} (stage)` : a.name, family: 'agent-hangar',
          version: String(a.version), detail: a.team?.name ?? 'Agent Hangar', tooltip: a.objective,
          maxInputTokens: 128000, maxOutputTokens: 16000, capabilities: { toolCalling: true, imageInput: false },
        }));
      } catch (e) {
        if (e instanceof HangarError && e.status === 401) {
          await ctx.secrets.delete(SECRET);
          void refreshStatus();
          if (!options.silent) vscode.window.showWarningMessage('Agent Hangar: sessão expirada — entre de novo.');
        }
        return [];
      }
    },
    async provideLanguageModelChatResponse(model, messages, options, progress, cancel) {
      const c = await client();
      if (!c) throw new Error('Agent Hangar: entre primeiro (comando "Agent Hangar: Entrar").');
      const abort = new AbortController();
      const sub = cancel.onCancellationRequested(() => abort.abort());
      try {
        const body: Record<string, unknown> = { messages: toOpenAIMessages(messages as readonly { role: number; content: readonly unknown[] }[]) };
        const tools = toOpenAITools(options.tools);
        if (tools.length) {
          body.tools = tools;
          if (options.toolMode === vscode.LanguageModelChatToolMode.Required) body.tool_choice = 'required';
        }
        for await (const ev of c.chat(model.slug, cfg().env, body, abort.signal, `vscode-${vscode.env.sessionId}`)) {
          if (ev.type === 'text') progress.report(new vscode.LanguageModelTextPart(ev.text));
          else if (ev.type === 'tool_call') progress.report(new vscode.LanguageModelToolCallPart(ev.id, ev.name, ev.input));
        }
      } catch (e) {
        if (abort.signal.aborted) return;
        if (e instanceof HangarError && e.status === 429) throw new Error(`Agent Hangar: ${e.message}`);
        throw new Error(`Agent Hangar: ${(e as Error).message}`);
      } finally {
        sub.dispose();
      }
    },
    async provideTokenCount(_model, text) {
      const s = typeof text === 'string' ? text : JSON.stringify(text.content);
      return Math.ceil(s.length / 4);
    },
  };
  ctx.subscriptions.push(vscode.lm.registerLanguageModelChatProvider('agent-hangar', provider));

  // ------------------------------------------------------------------ MCP da plataforma (criar/editar agentes)
  ctx.subscriptions.push(vscode.lm.registerMcpServerDefinitionProvider('agent-hangar.platform', {
    onDidChangeMcpServerDefinitions: changedMcp.event,
    async provideMcpServerDefinitions() {
      const t = await token();
      if (!t) return [];
      return [new vscode.McpHttpServerDefinition('Agent Hangar (plataforma)', vscode.Uri.parse(`${cfg().base}/mcp`),
        { Authorization: `Bearer ${t}` })];
    },
    async resolveMcpServerDefinition(server) {
      const t = await token();
      if (!t) {
        await vscode.commands.executeCommand('agentHangar.signIn');
        return undefined;
      }
      if (server instanceof vscode.McpHttpServerDefinition) server.headers = { Authorization: `Bearer ${t}` };
      return server;
    },
  }));

  // ------------------------------------------------------------------ comandos
  const testConnection = async () => {
    const c = await client();
    if (!c) return signIn();
    const { env } = cfg();
    const agents = await c.usableAgents(env);
    if (!agents.length) {
      vscode.window.showWarningMessage(`Agent Hangar: nenhum agente de chat seu está no ar em ${env}.`);
      return;
    }
    const pick = await vscode.window.showQuickPick(agents.map(a => ({ label: a.name, description: a.slug, detail: a.objective, slug: a.slug })),
      { title: `Testar conexão (${env})`, placeHolder: 'Qual agente?' });
    if (!pick) return;
    const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Testando ${pick.label}…` },
      () => c.testConnection(pick.slug, env));
    const lines = r.steps.map(s => `${s.ok ? '✓' : '✗'} ${s.name} — ${s.detail}`).join('\n');
    if (r.ok) vscode.window.showInformationMessage(`Agent Hangar: conexão funcionando com ${pick.label}.`, { modal: true, detail: lines });
    else vscode.window.showErrorMessage(`Agent Hangar: o teste com ${pick.label} falhou.`, { modal: true, detail: lines });
  };

  ctx.subscriptions.push(
    vscode.commands.registerCommand('agentHangar.signIn', () => signIn()),
    vscode.commands.registerCommand('agentHangar.signOut', signOut),
    vscode.commands.registerCommand('agentHangar.testConnection', testConnection),
    vscode.commands.registerCommand('agentHangar.refresh', () => changed()),
    vscode.commands.registerCommand('agentHangar.openPortal', () => vscode.env.openExternal(vscode.Uri.parse(`${cfg().base}/app/`))),
    vscode.commands.registerCommand('agentHangar.signInWithToken', async () => {
      const t = await vscode.window.showInputBox({ title: 'Agent Hangar', prompt: 'Token pessoal (Minhas chaves → token pessoal)', password: true, ignoreFocusOut: true });
      if (!t) return;
      try {
        const me = await new HangarClient(cfg().base, t).me();
        await ctx.secrets.store(SECRET, t);
        await ctx.globalState.update(KEY_ID, undefined);
        await ctx.globalState.update(USER, me.user?.name || me.name);
        changed();
      } catch (e) { vscode.window.showErrorMessage(`Agent Hangar: ${(e as Error).message}`); }
    }),
    vscode.commands.registerCommand('agentHangar.menu', async () => {
      const signedIn = !!(await token());
      const items = signedIn
        ? [{ label: '$(beaker) Testar conexão com um agente', id: 'agentHangar.testConnection' },
           { label: '$(refresh) Atualizar a lista de agentes', id: 'agentHangar.refresh' },
           { label: '$(globe) Abrir o portal', id: 'agentHangar.openPortal' },
           { label: '$(sign-out) Sair', id: 'agentHangar.signOut' }]
        : [{ label: '$(sign-in) Entrar pelo portal', id: 'agentHangar.signIn' },
           { label: '$(key) Entrar com token pessoal', id: 'agentHangar.signInWithToken' }];
      const pick = await vscode.window.showQuickPick(items, { title: 'Agent Hangar' });
      if (pick) await vscode.commands.executeCommand(pick.id);
    }),
    vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('agentHangar')) changed(); }),
  );
  void refreshStatus();
}

export function deactivate() { /* nada a liberar além das subscriptions */ }
