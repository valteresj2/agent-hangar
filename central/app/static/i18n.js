/* Idiomas do portal e do console: português (o texto original da UI) e inglês.
   O idioma vem da escolha da pessoa (seletor no rodapé do menu, guardado no navegador) ou, na primeira visita, do
   idioma do navegador. Em inglês, uma camada de tradução troca os textos da interface conforme a tela é desenhada:
   textos inteiros, pedaços de texto misturados com valores ("5 chamadas" -> "5 calls") e atributos (placeholder, title).
   Não traduz o que é dado: conversas, respostas dos agentes, código, specs e campos que a pessoa digitou. */
(function () {
  let saved = null;
  try { saved = localStorage.getItem('hangar_lang'); } catch (e) { /* navegação privada */ }
  const LANG = saved || ((navigator.language || 'pt').toLowerCase().startsWith('pt') ? 'pt' : 'en');
  window.LANG = LANG;
  window.LOCALE = LANG === 'en' ? 'en-US' : 'pt-BR';
  window.setLang = l => { try { localStorage.setItem('hangar_lang', l); } catch (e) { /* ok */ } location.reload(); };
  document.documentElement.lang = LANG === 'en' ? 'en' : 'pt-BR';

  const D = {
    // ---- navegação e páginas
    'Pular para o conteúdo': 'Skip to content', 'Meu espaço': 'My space', 'Início': 'Home', 'Meus agentes': 'My agents',
    'Catálogo da empresa': 'Company catalog', 'Pedidos e aprovações': 'Requests and approvals', 'Criar': 'Create',
    'Novo agente': 'New agent', 'Templates': 'Templates', 'Skills e MCPs': 'Skills and MCPs', 'Usar': 'Use',
    'Conectar ferramentas': 'Connect tools', 'Minhas chaves': 'My keys', 'Uso e custo': 'Usage and cost',
    'Organização': 'Organization', 'Meus times': 'My teams', 'Sair': 'Sign out', 'Trocar senha': 'Change password',
    'Agent Hangar · Meu espaço': 'Agent Hangar · My space', 'Portal do usuário': 'User portal', 'Agentes': 'Agents',
    'Catálogo': 'Catalog', 'Times': 'Teams', 'Usuários': 'Users', 'SSO e SCIM': 'SSO and SCIM', 'Aprovações': 'Approvals',
    'Provedores de LLM': 'LLM providers', 'Chaves de API': 'API keys', 'Construção': 'Build', 'Operação': 'Operations',
    'Pipeline de agentes': 'Agent pipeline', 'Auditoria': 'Audit log', 'Deployments': 'Deployments', 'Testes': 'Tests',
    'Visão geral': 'Overview', 'Conectar': 'Connect', 'Multiagente': 'Multi-agent', 'Versões': 'Versions', 'Uso': 'Usage',
    'Agendamentos': 'Schedules', 'Memória': 'Memory', 'Acesso': 'Access', '← Agentes': '← Agents', '← Times': '← Teams',
    'Painel': 'Dashboard', 'Console': 'Console',
    // ---- painéis
    'Agentes registrados': 'Registered agents', 'Rodando em produção': 'Running in production', 'Rodando em stage': 'Running in stage',
    'Multiagentes': 'Multi-agents', 'Testes aprovados (': 'Tests passed (', 'execuções)': 'runs)', 'Tokens 24h': 'Tokens 24h',
    'Custo 7d': 'Cost 7d', '(mostrando 24 — refine a busca)': '(showing 24 — refine the search)',
    '(o time pode liberar a spec em Acesso → “expor spec”)': '(the team can share the spec in Access → “expose spec”)',
    '(sem refresh!)': '(no refresh!)', '+ Novo agente': '+ New agent', '+ Novo time': '+ New team', 'Excluir time': 'Delete team',
    ', crie em “Novo agente” ou procure no': ', create one in “New agent” or look in the',
    'Agente com harness: cada chamada (OpenAI, A2A, ACP ou MCP) vira um job num container efêmero.':
      'Harness agent: each call (OpenAI, A2A, ACP or MCP) becomes a job in an ephemeral container.',
    'Aprovação e orçamento são definidos por admins.': 'Approval and budget are set by admins.',
    'Descreva o que o agente deve fazer': 'Describe what the agent should do', 'E-mails em': 'E-mails in',
    'Nenhum agente de outros times visível para você.': 'No agents from other teams visible to you.',
    'Nenhum agente seu ainda. Peça no chat (Claude/ChatGPT/Codex) conectado ao MCP do hangar, use um':
      'No agents of yours yet. Ask in a chat (Claude/ChatGPT/Codex) connected to the hangar MCP, use a',
    'No ar em produção': 'Live in production',
    'O agente ainda não está em produção: os agendamentos ficam aguardando e começam a disparar quando ele subir.':
      'The agent is not in production yet: schedules wait and start running when it goes live.',
    'Os agentes dos seus times: o que está no ar e como está indo': 'Your teams\' agents: what is live and how it is going',
    'Pedidos para você decidir': 'Requests for you to decide', 'Pedidos seus em aberto': 'Your open requests',
    'Sessão de emergência': 'Emergency session', 'Seu custo (30 dias)': 'Your cost (30 days)', 'Suas chamadas (30 dias)': 'Your calls (30 days)',
    'Testa em stage e pede a aprovação de um mantenedor do time': 'Tests in stage and asks a team maintainer for approval',
    'Todos': 'All', 'Todos os agentes da empresa (você é admin)': 'All the company\'s agents (you are an admin)',
    'Tudo o que está no ar na empresa, e como está indo': 'Everything live in the company, and how it is going',
    'Você vê só as suas conexões.': 'You see only your connections.', 'aguarda aprovação': 'awaiting approval',
    'catálogo Docker': 'Docker catalog', 'conexão funcionando': 'connection working', 'fora do ar': 'down', 'memória': 'memory',
    'nenhuma (mock — só para testar o fluxo)': 'none (mock — only to test the flow)', 'não aprovada': 'not approved',
    'segredo do app': 'app secret', '· só leitura': '· read-only', '•••••• (salvo — vazio mantém)': '•••••• (saved — empty keeps it)',
    // ---- telas do console e fragmentos entre links
    '% erros': '% errors', '), revogada quando você sair da extensão ou perder o acesso.': '), revoked when you sign out of the extension or lose access.',
    '), roda a tarefa e é destruída. Pode levar até alguns minutos.': '), runs the task and is destroyed. It can take a few minutes.',
    '): o cliente age como você, com os seus times e papéis. Para': '): the client acts as you, with your teams and roles. To',
    '+ Cadastrar usuário': '+ Register user', ', MCP da plataforma no Claude/Codex).': ', platform MCP in Claude/Codex).', ', em': ', in',
    ', onde você revoga quando quiser.': ', where you can revoke it anytime.', ', ou': ', or',
    '. Revogar desconecta o app na hora.': '. Revoking disconnects the app at once.',
    '. Stage lê a memória de produção, mas grava à parte — testar não suja a produção.': '. Stage reads the production memory but writes separately — testing does not pollute production.',
    ': Configurações → Apps e conectores → Criar (modo desenvolvedor) → URL acima, autenticação OAuth.': ': Settings → Apps & Connectors → Create (developer mode) → the URL above, OAuth authentication.',
    ': Configurações → Conectores → Adicionar conector personalizado → URL acima.': ': Settings → Connectors → Add custom connector → the URL above.',
    ': escolha a ferramenta (Claude Code, Codex, OpenCode, Cursor, VS Code, LibreChat, Open WebUI…) e o modo (MCP ou modelo) e receba a configuração pronta, com uma chave só daquela ferramenta. Os exemplos abaixo são genéricos.':
      ': pick the tool (Claude Code, Codex, OpenCode, Cursor, VS Code, LibreChat, Open WebUI…) and the mode (MCP or model) and get a ready configuration, with a key just for that tool. The examples below are generic.',
    ': só chama os agentes escolhidos pelo gateway (LibreChat, Slack, SDKs).': ': only calls the chosen agents through the gateway (LibreChat, Slack, SDKs).',
    ': token pessoal — age como você (CLI': ': personal token — acts as you (CLI',
    '? Clientes que a usam param de funcionar.': '? Clients using it stop working.', '? Todas as pessoas que o conectaram são desconectadas.': '? Everyone who connected it is disconnected.',
    'Abra o agente em': 'Open the agent in', 'Abrir mão': 'Give up', 'Acesso de': 'Access for',
    'Adaptadores nativos estão no roadmap. Hoje: aponte o bot para o endpoint OpenAI-compatible enviando': 'Native adapters are on the roadmap. Today: point the bot at the OpenAI-compatible endpoint sending',
    'Adicione o(s) provedor(es) de LLM que você tem — a conexão fica disponível para qualquer agente ou harness via design_agent(llm=...) / design_agent(harness=...)':
      'Add the LLM provider(s) you have — the connection becomes available to any agent or harness via design_agent(llm=...) / design_agent(harness=...)',
    'Agente como ferramenta MCP (Claude Desktop/Code, OpenCode…)': 'Agent as an MCP tool (Claude Desktop/Code, OpenCode…)',
    'Agentes prontos para aplicar, testar e shipar. Sem conexão de LLM eles nascem em modo mock (bom para ver o fluxo).': 'Agents ready to apply, test and ship. Without an LLM connection they start in mock mode (good to see the flow).',
    'Agentes selecionados restringem uma chave': 'Selected agents restrict a key', 'Agora só conexões aprovadas recebem código': 'Now only approved connections receive code',
    'Aguardando a sua decisão': 'Waiting for your decision', 'Alimenta agentes de chat e o harness codex (o caminho mais direto para o codex).': 'Powers chat agents and the codex harness (the most direct path for codex).',
    'Alimenta agentes de chat e o harness codex. Não serve o harness claude-code (só fala o protocolo da OpenAI, não o da Anthropic).': 'Powers chat agents and the codex harness. Does not serve the claude-code harness (it only speaks the OpenAI protocol, not Anthropic\'s).',
    'Aprovação retirada': 'Approval removed', 'Ativar login com este provedor': 'Enable sign-in with this provider', 'Ação': 'Action',
    'Cada agente deployado é também o seu próprio servidor MCP, com 1 tool (o nome do agente) — as skills, MCPs e tools configurados nele continuam ativos por trás da chamada.':
      'Each deployed agent is also its own MCP server, with 1 tool (the agent\'s name) — the skills, MCPs and tools configured in it stay active behind the call.',
    'Cada execução sobe um container Docker isolado (': 'Each run starts an isolated Docker container (', 'Catálogo Docker MCP': 'Docker MCP catalog',
    'Chamadas de agentes e multiagentes por canal e protocolo · custo = tokens × preço da conexão (ou o que o harness reportou)': 'Agent and multi-agent calls by channel and protocol · cost = tokens × connection price (or what the harness reported)',
    'Cole só a URL': 'Paste only the URL', 'Com a extensão,': 'With the extension,', 'Com a extensão, os agentes que você pode usar aparecem no seletor de modelos do chat do VS Code.': 'With the extension, the agents you can use appear in the VS Code chat model picker.',
    'Comece por aqui': 'Start here', 'Conectar um agente pronto a uma ferramenta?': 'Connect a ready agent to a tool?',
    'Conecte o MCP do hangar ao seu cliente e peça: “crie um agente que…”': 'Connect the hangar MCP to your client and ask: “create an agent that…”',
    'Conecte o MCP do hangar no Claude, ChatGPT, Codex ou OpenCode e peça': 'Connect the hangar MCP in Claude, ChatGPT, Codex or OpenCode and ask',
    'Conexão': 'Connection', 'Conexão aprovada para código': 'Connection approved for code', 'Conexão salva': 'Connection saved', 'Conexões de LLM (': 'LLM connections (',
    'Copie agora — não será exibida de novo:': 'Copy it now — it will not be shown again:', 'Criar time': 'Create team', 'Código': 'Code',
    'Dias úteis (seg a sex)': 'Weekdays (Mon to Fri)', 'Dê um nome à chave': 'Give the key a name',
    'Endpoint do Gemini compatível com OpenAI. Alimenta agentes de chat e o harness codex.': 'Gemini\'s OpenAI-compatible endpoint. Powers chat agents and the codex harness.',
    'Entrar com': 'Sign in with', 'Enviar o resultado para (webhook, opcional)': 'Send the result to (webhook, optional)', 'Escolha os agentes que a chave pode chamar': 'Pick the agents the key can call',
    'Execuções em stage registradas por versão': 'Stage runs recorded by version', 'Kit completo (Docker Compose, anexos, workspace por conversa, títulos baratos):': 'Full kit (Docker Compose, attachments, per-conversation workspace, cheap titles):',
    'Latência média ·': 'Average latency ·', 'Ligar memória': 'Turn on memory', 'LiteLLM (gateway próprio)': 'LiteLLM (your own gateway)',
    'Mantenedor (e-mail ou usuário, opcional)': 'Maintainer (e-mail or username, optional)', 'Modelo padrão': 'Default model',
    'Modelo rodando na sua própria máquina, fora do Docker. A chave geralmente não é validada — pode deixar qualquer valor (ex.:': 'A model running on your own machine, outside Docker. The key is usually not validated — any value works (e.g.',
    'Nenhum LLM roda em Docker aqui — cada conexão é uma URL externa (gateway LiteLLM da empresa, OpenRouter, OpenAI…) + model_name + api key virtual.': 'No LLM runs in Docker here — each connection is an external URL (company LiteLLM gateway, OpenRouter, OpenAI…) + model_name + virtual API key.',
    'Novo time': 'New team', 'O que está acontecendo com os seus agentes': 'What is happening with your agents',
    'Peça acesso: um mantenedor do time aprova, e aí você conecta o agente nas suas ferramentas (aba Conectar).': 'Request access: a team maintainer approves, then you connect the agent to your tools (Connect tab).',
    'Playground — job de harness': 'Playground — harness job', 'Precisa de atenção (': 'Needs attention (', 'Preço (US$/1M in · out)': 'Price (US$/1M in · out)',
    'Produção de': 'Production of', 'Produção exige aprovação de outro mantenedor': 'Production requires approval from another maintainer', 'Próximo': 'Next',
    'Próximos disparos agendados': 'Upcoming scheduled runs', 'Qual chave usar?': 'Which key to use?', 'Qualquer conexão pode receber código': 'Any connection can receive code',
    'Qualquer endpoint compatível com OpenAI (Bedrock, Vertex AI, Groq, Together, etc.) ou com a API da Anthropic — escolha o protocolo certo abaixo.': 'Any endpoint compatible with OpenAI (Bedrock, Vertex AI, Groq, Together, etc.) or with the Anthropic API — pick the right protocol below.',
    'Quem ainda não entrou fica pré-cadastrado e cai no time no primeiro login.': 'People who have not signed in yet are pre-registered and join the team at their first sign-in.',
    'Redirect URI (cadastre no provedor):': 'Redirect URI (register it with the provider):', 'Remover a conexão': 'Remove the connection', 'Revogar a chave': 'Revoke the key',
    'Salvar conexão': 'Save connection', 'Sem webhook, o resultado fica no histórico desta aba.': 'Without a webhook, the result stays in this tab\'s history.', 'Seu pedido de': 'Your request for',
    'Seu próprio gateway. Use host.docker.internal (não': 'Your own gateway. Use host.docker.internal (not', 'Skills, MCP servers e conexões de LLM reutilizáveis pelos agentes': 'Skills, MCP servers and LLM connections reusable by agents',
    'Suas chaves morrem se você perder o acesso.': 'Your keys stop working if you lose access.',
    'Só e-mail: pré-cadastro, a pessoa entra pelo SSO. Com usuário e senha: conta local (login direto na tela de entrada).': 'E-mail only: pre-registration, the person signs in with SSO. With username and password: local account (direct sign-in on the login screen).',
    'Tudo que foi criado, alterado, testado e deployado': 'Everything created, changed, tested and deployed', 'Um container Docker isolado por agente e ambiente': 'One isolated Docker container per agent and environment',
    'Usar agentes já deployados': 'Use agents already deployed', 'Você ainda não tem agentes.': 'You have no agents yet.', 'agentes': 'agents',
    'agentes (MCP do hangar) use o seu': 'agents (hangar MCP) use your', 'atrás está': 'ago is', 'bloquear chamadas ao estourar': 'block calls when exceeded', 'chamadas ·': 'calls ·',
    'conectado — use-o nos agentes pelo nome': 'connected — use it in agents by name', 'de': 'of', 'do agente ou uma chave': 'of the agent or a key', 'e com': 'and with',
    'e os outros agentes que você pode usar aparecem no seletor de modelos do chat do VS Code.': 'and the other agents you can use appear in the VS Code chat model picker.',
    'e peça acesso.': 'and request access.', 'em': 'in', 'em 7 dias': 'in 7 days', 'em vez de': 'instead of', 'especialista agora em v': 'specialist now at v',
    'gateway no ar,': 'gateway up,', 'invoke — consumir agentes': 'invoke — use agents', 'já faz isso — usar como está': 'already does this — use it as is', 'no': 'in', 'no ar': 'live',
    'no repositório. De dentro de um container, troque': 'in the repository. From inside a container, replace', 'nos agentes': 'in agents', 'o mantenedor do time.': 'the team maintainer.',
    'openai — agente de chat, codex, hermes': 'openai — chat agent, codex, hermes', 'ou': 'or', 'para testar contra a versão de stage.': 'to test against the stage version.',
    'para ver as métricas por canal.': 'to see per-channel metrics.', 'pedido por': 'requested by', 'pela chave.': 'with the key.', 'pelo slug do agente. Use': 'with the agent\'s slug. Use',
    'procure no': 'look in the', 'qualquer pessoa da empresa usa direto': 'anyone in the company uses it directly', 'só o time vê e usa': 'only the team sees and uses it',
    'tokens no total': 'tokens in total', 'um agente (LibreChat, Slack, OpenCode…) use a aba': 'an agent (LibreChat, Slack, OpenCode…) use the tab', 'viram admin no login:': 'become admins at sign-in:',
    '· último uso:': '· last used:', 'É criada uma chave pessoal (em': 'A personal key is created (in', 'Único protocolo que serve o harness claude-code de verdade.': 'The only protocol that really serves the claude-code harness.',
    '— chamadas bloqueadas': '— calls blocked', '— ou use um': '— or use a', '— próximo em': '— next on', '“crie um agente que…”': '“create an agent that…”',
    'Para': 'To', 'construir': 'build', 'usar': 'use', 'Erros': 'Errors', 'Chave': 'Key', '? A ferramenta que usa essa chave para de funcionar.': '? The tool using this key stops working.',
    'Latência média': 'Average latency', 'erros': 'errors', 'requisições': 'requests', 'Requisições': 'Requests', 'Sessão': 'Session',
    'sessão de emergência': 'emergency session', 'Detalhe': 'Detail', 'Quem': 'Who', 'Alvo': 'Target',
    // ---- clientes da aba Conectar (textos vindos do servidor, services/connect.py)
    'CLI da Anthropic. O agente vira uma ferramenta que o Claude chama.': 'Anthropic\'s CLI. The agent becomes a tool that Claude calls.',
    'App desktop, via mcp-remote (precisa de Node.js).': 'Desktop app, via mcp-remote (needs Node.js).',
    'CLI da OpenAI (~/.codex/config.toml).': 'OpenAI\'s CLI (~/.codex/config.toml).',
    'Como ferramenta (MCP) ou como modelo (provedor OpenAI-compatible).': 'As a tool (MCP) or as a model (OpenAI-compatible provider).',
    'IDE: .cursor/mcp.json (no projeto) ou ~/.cursor/mcp.json (global).': 'IDE: .cursor/mcp.json (in the project) or ~/.cursor/mcp.json (global).',
    'Como modelo no chat (agente de código: edita arquivos e usa o terminal do VS Code) ou como ferramenta MCP (.vscode/mcp.json).':
      'As a model in the chat (coding agent: edits files and uses the VS Code terminal) or as an MCP tool (.vscode/mcp.json).',
    'Extensões de código do VS Code: o agente vira o modelo e edita o projeto com as ferramentas da extensão.':
      'VS Code coding extensions: the agent becomes the model and edits the project with the extension\'s tools.',
    'Extensão do VS Code/JetBrains (config.yaml), com uso de ferramentas.': 'VS Code/JetBrains extension (config.yaml), with tool use.',
    'Como modelo (recomendado: anexos, workspace por conversa, progresso ao vivo) ou como ferramenta MCP.':
      'As a model (recommended: attachments, per-conversation workspace, live progress) or as an MCP tool.',
    'Como modelo (conexão OpenAI) ou como ferramenta (MCP).': 'As a model (OpenAI connection) or as a tool (MCP).',
    'Qualquer cliente OpenAI-compatible (Python, JS, n8n…).': 'Any OpenAI-compatible client (Python, JS, n8n…).',
    'Qualquer cliente MCP com Streamable HTTP e cabeçalhos.': 'Any MCP client with Streamable HTTP and headers.',
    'SDK OpenAI / outros': 'OpenAI SDK / others', 'Outro cliente MCP': 'Other MCP client',
    'A chave aparece só agora; revogar a conexão desliga só esta ferramenta.': 'The key is shown only now; revoking the connection turns off only this tool.',
    'Rode no terminal (escopo do usuário; troque --scope user por project para só este projeto).': 'Run it in the terminal (user scope; change --scope user to project for this project only).',
    'Mescle o bloco em mcpServers e reinicie o Claude Desktop.': 'Merge the block into mcpServers and restart Claude Desktop.',
    'Acrescente ao ~/.codex/config.toml e reinicie o Codex.': 'Append it to ~/.codex/config.toml and restart Codex.',
    'Mescle o bloco no opencode.json.': 'Merge the block into opencode.json.', 'Mescle em .cursor/mcp.json; o servidor aparece em Settings → MCP.': 'Merge it into .cursor/mcp.json; the server shows up in Settings → MCP.',
    'Mescle em .vscode/mcp.json e habilite o servidor no Copilot Chat (modo Agent).': 'Merge it into .vscode/mcp.json and enable the server in Copilot Chat (Agent mode).',
    'Acrescente ao librechat.yaml e reinicie o LibreChat.': 'Append it to librechat.yaml and restart LibreChat.',
    'Habilite a ferramenta no modelo (Workspace → Models) ou no chat.': 'Enable the tool in the model (Workspace → Models) or in the chat.',
    'Cliente MCP genérico: transporte Streamable HTTP, servidor stateless (sem sessão).': 'Generic MCP client: Streamable HTTP transport, stateless server (no session).',
    'Chat do VS Code → seletor de modelos → Gerenciar modelos → provedor OpenAI Compatible (disponível nas versões recentes do Copilot Chat).':
      'VS Code chat → model picker → Manage models → OpenAI Compatible provider (available in recent Copilot Chat versions).',
    'Informe a URL base, a chave e o id do modelo abaixo, com chamada de ferramentas ativada.': 'Enter the base URL, the key and the model id below, with tool calling turned on.',
    'Escolha o agente no seletor e use o modo Agent: ele lê e edita arquivos e roda comandos no terminal do VS Code, sempre com a sua aprovação.':
      'Pick the agent in the picker and use Agent mode: it reads and edits files and runs commands in the VS Code terminal, always with your approval.',
    'Sem essa opção no seu VS Code? Use Cline, Roo Code ou Continue (mesma URL e chave).': 'No such option in your VS Code? Use Cline, Roo Code or Continue (same URL and key).',
    'Preencha Base URL, API Key e Model ID com os valores abaixo e salve.': 'Fill Base URL, API Key and Model ID with the values below and save.',
    'O agente passa a planejar e editar o projeto com as ferramentas da extensão (arquivos, terminal), que pedem a sua aprovação antes de agir.':
      'The agent then plans and edits the project with the extension\'s tools (files, terminal), which ask for your approval before acting.',
    'Mescle o bloco em models do config.yaml do Continue.': 'Merge the block into models in Continue\'s config.yaml.',
    'Escolha o agente no seletor do Continue e use o modo Agent para editar o projeto.': 'Pick the agent in Continue\'s picker and use Agent mode to edit the project.',
    'Mescle no librechat.yaml e reinicie o LibreChat.': 'Merge it into librechat.yaml and restart LibreChat.',
    'Mescle no opencode.json e escolha o modelo com /models.': 'Merge it into opencode.json and pick the model with /models.',
    'Qualquer SDK/cliente OpenAI-compatible (stream suportado).': 'Any OpenAI-compatible SDK/client (streaming supported).',
    // ---- restos encontrados na varredura
    'Criar agendamento': 'Create schedule', 'Erros 24h': 'Errors 24h', 'No modo': 'In', 'Para ligar o gateway:': 'To turn on the gateway:',
    'Salvar MCP': 'Save MCP', 'Salvar skill': 'Save skill',
    'restrita a ele — nunca distribua o ADMIN_TOKEN. Nos exemplos, troque': 'restricted to it — never hand out the ADMIN_TOKEN. In the examples, replace',
    'Claude.ai e ChatGPT (web) — sem chave': 'Claude.ai and ChatGPT (web) — no key',
    '; o app pede para você entrar aqui no portal e autorizar (OAuth).': '; the app asks you to sign in here in the portal and authorize (OAuth).',
    'Login corporativo por OAuth2 e provisionamento automático de usuários e grupos. Segredos ficam criptografados; variáveis OAUTH_* do .env valem como padrão.':
      'Company sign-in with OAuth2 and automatic provisioning of users and groups. Secrets are stored encrypted; OAUTH_* variables in .env act as defaults.',
    'Adicionar / editar conexão (mesmo nome = edição; chave vazia mantém a atual)': 'Add / edit connection (same name = edit; an empty key keeps the current one)',
    'o que os agentes ganham com ele': 'what agents gain from it', 'nome do token (ex.: entra-id)': 'token name (e.g. entra-id)',
    'ex.: http://localhost:8098 — quando a central usa um endereço interno': 'e.g. http://localhost:8098 — when the central uses an internal address',
    'Time padrão: agentes criados antes dos times e pelo token de admin.': 'Default team: agents created before teams and by the admin token.',
    'Cria uma nova versão da spec; faça deploy em stage para testar.': 'Creates a new spec version; deploy to stage to test it.',
    'Claude.ai, ChatGPT e outros apps que você autorizou a usar o MCP do hangar em seu nome': 'Claude.ai, ChatGPT and other apps you authorized to use the hangar MCP in your name',
    'Seu próprio gateway. Use host.docker.internal (não "litellm") — o nome de serviço só resolve de dentro da rede Docker do projeto do LiteLLM, uma rede diferente desta. Alimenta agentes de chat e o harness codex; se seu LiteLLM expuser /v1/messages para um modelo Anthropic, dá pra registrar de novo aqui com protocolo anthropic para servir o harness claude-code.':
      'Your own gateway. Use host.docker.internal (not "litellm") — the service name only resolves inside the Docker network of the LiteLLM project, a different network from this one. Powers chat agents and the codex harness; if your LiteLLM exposes /v1/messages for an Anthropic model, register it again here with the anthropic protocol to serve the claude-code harness.',
    'API oficial da DeepSeek. Com protocolo deepseek serve o harness deepseek-harness; registre de novo com protocolo openai (base https://api.deepseek.com/v1) para agentes de chat.':
      'DeepSeek\'s official API. With the deepseek protocol it serves the deepseek-harness harness; register it again with the openai protocol (base https://api.deepseek.com/v1) for chat agents.',
    'Servidores MCP que exigem login (Activepieces, Notion, Linear, Atlassian…). Você autoriza uma vez; a central guarda os tokens criptografados, renova sozinha e entrega o MCP aos agentes por um proxy interno — o agente nunca vê a credencial. Use o':
      'MCP servers that require sign-in (Activepieces, Notion, Linear, Atlassian…). You authorize once; the central stores the tokens encrypted, renews them on its own and hands the MCP to agents through an internal proxy — the agent never sees the credential. Use the',
    ': revogue quando quiser, sem afetar as outras; o uso aparece por ferramenta. Se você perder o acesso ao agente, suas chaves são revogadas automaticamente.':
      ': revoke it anytime without affecting the others; usage shows up per tool. If you lose access to the agent, your keys are revoked automatically.',
    'ADMIN_TOKEN ou ah_…': 'ADMIN_TOKEN or ah_…',
    'O que está acontecendo com os seus agentes e com o seu time': 'What is happening with your agents and your team',
    'O que está acontecendo com os seus agentes e com os seus times': 'What is happening with your agents and your teams',
    'ex.: um agente para os executivos de contas que lembra o histórico de cada cliente e escreve o e-mail de follow-up antes das reuniões':
      'e.g. an agent for account executives that remembers each customer\'s history and writes the follow-up e-mail before meetings',
    'lembrar o histórico de cada cliente\nescrever o e-mail de follow-up\naprovar descontos pela política comercial':
      'remember each customer\'s history\nwrite the follow-up e-mail\napprove discounts under the sales policy',
    'lembrar o histórico de cada cliente escrever o e-mail de follow-up aprovar descontos pela política comercial':
      'remember each customer\'s history\nwrite the follow-up e-mail\napprove discounts under the sales policy',
    '); opcional': '); optional', 'ex.: Triagem de chamados': 'e.g. Ticket triage', 'Buscar na memória (ex.: plano da ACME)': 'Search the memory (e.g. ACME plan)', '(obrigatório). O valor da chave aparece uma única vez.': '(required). The key value is shown only once.',
    // ---- guia do agente
    'Canal': 'Channel', 'Protocolo': 'Protocol', 'Modo': 'Mode', 'Arquivo:': 'File:', 'Escopo:': 'Scope:', '· grupo': '· group',
    'Guia': 'Guide', 'Agendamento': 'Schedule', 'Ficha': 'Fact sheet', 'Entrega': 'Delivers', 'Dono': 'Owner',
    'Ferramentas': 'Tools', 'Pedidos de exemplo': 'Example requests', 'Onde chamar': 'Where to call',
    'Casos que passaram nos testes desta versão.': 'Cases that passed the tests of this version.',
    'Para ligar numa ferramenta (Claude, ChatGPT, VS Code…), use a aba': 'To plug it into a tool (Claude, ChatGPT, VS Code…), use the tab',
    'O fluxo sai da spec da versão descrita e mostra quais skills, ferramentas e especialistas o agente usa, não o conteúdo deles.':
      'The flow comes from the spec of the version described and shows which skills, tools and specialists the agent uses, not their content.',
    'Carregando…': 'Loading…', 'Fluxo do agente': 'Agent flow', 'Pedido': 'Request', 'Entrada': 'Input', 'Ferramenta': 'Tool',
    'Especialista': 'Specialist', 'Saída': 'Output', 'Container efêmero': 'Ephemeral container',
    '1 por tarefa · devolve resultado + git diff': '1 per task · returns result + git diff', 'ferramentas MCP': 'MCP tools',
    'ferramenta': 'tool', 'especialista (A2A)': 'specialist (A2A)', 'descrita': 'described', 'fora de produção': 'not in production',
    'rascunho gerado · não revisado': 'generated draft · not reviewed', 'revisado': 'reviewed',
    'Gerado pelo LLM do agente': 'Generated by the agent\'s LLM', 'Escrito por': 'Written by',
    'Este agente ainda não tem guia.': 'This agent has no guide yet.',
    'Escreva aqui, ou peça ao Claude/ChatGPT conectado ao hangar: “escreva o guia do agente com set_agent_guide”.':
      'Write it here, or ask Claude/ChatGPT connected to the hangar: “write the agent guide with set_agent_guide”.',
    'Escrever guia': 'Write guide', 'Aprovar rascunho': 'Approve draft', 'Gerar de novo com IA': 'Generate again with AI',
    'Gerar rascunho com IA': 'Generate draft with AI', 'Salvar guia': 'Save guide', 'Guia salvo': 'Guide saved',
    'Rascunho aprovado': 'Draft approved', 'Rascunho gerado — revise antes de aprovar': 'Draft generated — review it before approving',
    'Gerar um rascunho novo com o LLM do agente? Ele substitui o texto atual.': 'Generate a new draft with the agent\'s LLM? It replaces the current text.',
    'Markdown. Escreva para quem vai usar: o que é, o que faz, o que não faz, como usar (com pedidos de exemplo) e limites. Salvar não cria versão nova nem exige testes.':
      'Markdown. Write for the people who will use it: what it is, what it does, what it does not do, how to use it (with example requests) and limits. Saving does not create a new version or require tests.',
    // ---- status, papéis, visibilidade, tempo
    'Rascunho': 'Draft', 'Testado': 'Tested', 'Teste falhou': 'Test failed', 'Produção': 'Production', 'Rodando': 'Running',
    'Falhou': 'Failed', 'Parado': 'Stopped', 'Substituído': 'Replaced', 'substituído': 'replaced', 'Caiu': 'Crashed',
    'Ausente': 'Missing', 'Iniciando': 'Starting', 'Aprovado': 'Passed', 'multiagente': 'multi-agent',
    'mantenedor': 'maintainer', 'pode usar': 'can use', 'só catálogo': 'catalog only', 'privado': 'private',
    'empresa': 'company', 'aberto': 'open', 'Visibilidade': 'Visibility', 'Membro': 'Member', 'Mantenedor': 'Maintainer',
    'gerencia membros, aprova produção e pedidos de acesso': 'manages members, approves production and access requests',
    'cria, edita e testa os agentes do time': 'creates, edits and tests the team\'s agents',
    'usa os agentes do time (conectar, playground, uso)': 'uses the team\'s agents (connect, playground, usage)',
    'agora': 'now', 'atrás': 'ago', 'atrás ·': 'ago ·', 'segunda': 'Monday', 'terça': 'Tuesday', 'quarta': 'Wednesday',
    'quinta': 'Thursday', 'sexta': 'Friday', 'sábado': 'Saturday', 'domingo': 'Sunday', 'nunca': 'never',
    'concluído': 'completed', 'falhou': 'failed', 'pendente': 'pending', 'aprovado': 'approved', 'recusado': 'rejected',
    'revogada': 'revoked', 'revogado': 'revoked', 'bloqueado': 'blocked', 'em produção': 'in production',
    'produção': 'production', 'atual': 'current', 'até': 'until', 'todos': 'all', 'nenhum': 'none', 'nenhuma': 'none',
    'Nenhum': 'None', 'Nenhuma.': 'None.', 'por': 'by', 'ver': 'view', 'time': 'team', 'Time': 'Team', 'conexão': 'connection',
    // ---- ações comuns
    'Salvar': 'Save', 'Excluir': 'Delete', 'Testar': 'Test', 'Entrar': 'Sign in', 'Cancelar': 'Cancel', 'Copiar': 'Copy',
    'Revogar': 'Revoke', 'Remover': 'Remove', 'Editar': 'Edit', 'Fechar': 'Close', 'Aplicar': 'Apply', 'Buscar': 'Search',
    'Buscar...': 'Search...', 'Buscar…': 'Search…', 'Atualizar': 'Refresh', 'Enviar': 'Send', 'Aprovar': 'Approve',
    'Recusar': 'Reject', 'Desconectar': 'Disconnect', 'Bloquear': 'Block', 'Pausar': 'Pause', 'Retomar': 'Resume',
    'Histórico': 'History', 'Rodar agora': 'Run now', 'Rodar testes': 'Run tests', 'Deploy stage': 'Deploy to stage',
    'Publicar em produção': 'Publish to production', 'Testar e pedir aprovação': 'Test and request approval',
    'Parar prod': 'Stop prod', 'Solicitar acesso': 'Request access', 'Gerar chave': 'Generate key', 'Autorizar': 'Authorize',
    'Ver spec': 'View spec', 'Ver catálogo →': 'View catalog →', 'Ver todos com detalhes →': 'View all with details →',
    'Abrir aprovações →': 'Open approvals →', 'Conectar ferramenta →': 'Connect a tool →', 'clique aqui': 'click here',
    'Salvar como nova versão': 'Save as a new version', 'Aplicar no time': 'Apply to team', 'Criar login local': 'Create local login',
    // ---- portal: início, agentes, catálogo
    'Tudo certo por aqui': 'All good here',
    'Nenhum teste reprovado, agendamento com falha, erro recente ou orçamento estourando nos seus agentes.':
      'No failed tests, failing schedules, recent errors or budgets running out in your agents.',
    'Pedidos': 'Requests', 'Os seus pedidos': 'Your requests', 'Orçamento e uso': 'Budget and usage',
    'O seu uso nos últimos 30 dias': 'Your usage in the last 30 days', 'no mês': 'this month',
    'no mês (sem orçamento definido)': 'this month (no budget set)', 'Próximos agendamentos': 'Upcoming schedules',
    'Agentes mais usados': 'Most used agents', 'Ainda sem uso': 'No usage yet', 'Sem uso ainda': 'No usage yet',
    'Sem uso registrado': 'No usage recorded', 'Sem dados ainda': 'No data yet',
    'Sem uso com as suas chaves ou sessão ainda.': 'No usage with your keys or session yet.',
    'Nenhum pedido. Para usar um agente de outro time, peça acesso no catálogo da empresa.':
      'No requests. To use another team\'s agent, request access in the company catalog.',
    'Nenhum agendamento nos seus agentes. Um agente pode rodar sozinho no dia e hora que você escolher (aba Agendamentos).':
      'No schedules in your agents. An agent can run on its own at the day and time you choose (Schedules tab).',
    'Nenhum agente de outros times publicado para você ainda.': 'No agents from other teams published for you yet.',
    'Nenhum agente.': 'No agents.', 'Nenhum dos seus agentes usa memória.': 'None of your agents uses memory.',
    'Agentes com memória lembram fatos entre conversas (clientes, decisões, preferências). Você pode ver o que foi guardado e pedir a exclusão.':
      'Agents with memory remember facts between conversations (customers, decisions, preferences). You can see what was stored and ask for it to be deleted.',
    'Memória dos agentes': 'Agents\' memory', 'Memória de longo prazo': 'Long-term memory', 'Minhas conexões': 'My connections',
    'Chaves suas em uso (Claude, Codex, LibreChat…). Revogue as que não usa mais.':
      'Your keys in use (Claude, Codex, LibreChat…). Revoke the ones you no longer use.',
    'Nenhuma chave ativa.': 'No active keys.', 'sem uso há 60+ dias': 'unused for 60+ days', 'Pronto para usar': 'Ready to use',
    'No catálogo da empresa': 'In the company catalog', 'Quer usar este agente?': 'Want to use this agent?',
    'Conecte nas suas ferramentas pela aba': 'Connect it to your tools from the tab', 'Você ainda não faz parte de um time.':
      'You are not part of a team yet.', 'Gasto no mês': 'Spent this month', 'Orçamento do mês': 'Monthly budget',
    'Agentes dos seus times e os que você recebeu acesso': 'Your teams\' agents and the ones you were given access to',
    'Catálogo da empresa: agentes de outros times que você pode encontrar e pedir para usar':
      'Company catalog: other teams\' agents you can find and ask to use',
    'Todos os times': 'All teams', 'Agente': 'Agent', 'Tipo': 'Type', 'Status': 'Status', 'Versão': 'Version',
    'Ambientes': 'Environments', 'Último teste': 'Last test', 'Req. 7d': 'Req. 7d', 'Quem pode ver e usar': 'Who can see and use',
    // ---- página do agente
    'Registro': 'Record', 'Saída final': 'Final output', 'Contato': 'Contact', 'Versão atual': 'Current version',
    'Criado': 'Created', 'Atualizado': 'Updated', 'Composição': 'Composition', 'Conexão LLM': 'LLM connection',
    'Modelo': 'Model', 'padrão da conexão': 'connection default', 'Sub-agentes': 'Sub-agents', 'Canais': 'Channels',
    'Casos de teste': 'Test cases', 'Instruções': 'Instructions', '(sem instruções)': '(no instructions)',
    'Endpoints (produção)': 'Endpoints (production)', 'nenhuma (mock/echo)': 'none (mock/echo)',
    'nenhuma (modo mock)': 'none (mock mode)', 'agente com harness': 'harness agent', 'Seu acesso': 'Your access',
    'Time dono': 'Owner team', 'Orquestração': 'Orchestration', 'Orquestrador · delega via A2A': 'Orchestrator · delegates over A2A',
    'Cada chamada sobe um container Docker efêmero, roda a tarefa e é destruída — nunca fica um container ocioso.':
      'Each call starts an ephemeral Docker container, runs the task and destroys it — no container is ever left idle.',
    'Instruções, spec, versões e logs são visíveis só para o time dono': 'Instructions, spec, versions and logs are visible only to the owner team',
    'Há um pedido de promoção para produção aguardando aprovação — veja em': 'There is a promotion request waiting for approval — see',
    'Testes aprovados — pedido de promoção enviado para um mantenedor do time':
      'Tests passed — promotion request sent to a team maintainer', 'Agente em produção': 'Agent in production',
    'Deploy em stage concluído': 'Stage deploy completed', 'Produção parada': 'Production stopped',
    'e seus containers?': 'and its containers?', 'Agente criado': 'Agent created', 'Logs do container': 'Container logs',
    'Nenhum deployment': 'No deployments', 'Nenhum teste ainda': 'No tests yet',
    'Nenhum teste registrado. Clique em “Rodar testes”.': 'No tests recorded. Click “Run tests”.',
    'Nenhum job ainda. Use a aba Playground para disparar uma tarefa.': 'No jobs yet. Use the Playground tab to start a task.',
    'Mensagem para o agente…': 'Message to the agent…', 'Descreva a tarefa que o agente deve executar…': 'Describe the task the agent should run…',
    'Latência': 'Latency', 'Quando': 'When', 'Custo': 'Cost', 'Requisições (14d)': 'Requests (14d)',
    'Requisições por dia (14d)': 'Requests per day (14d)', 'Custo (14d, US$)': 'Cost (14d, US$)',
    'Custo por dia (14d, US$)': 'Cost per day (14d, US$)', 'Por canal': 'By channel', 'Por protocolo': 'By protocol',
    'Últimas chamadas': 'Latest calls', 'Últimas 100 chamadas': 'Latest 100 calls', 'Custo 14 dias': 'Cost 14 days',
    'Custo 24h': 'Cost 24h', 'Requisições 24h': 'Requests 24h', 'Restaurar a spec da v': 'Restore the spec of v',
    'como uma nova versão? (depois rode testes/ship)': 'as a new version? (then run tests/ship)', 'Versão restaurada': 'Version restored',
    'Substitui a spec inteira (PUT). Validação no servidor: campos desconhecidos ou combinações inválidas (ex.:':
      'Replaces the whole spec (PUT). Server-side validation: unknown fields or invalid combinations (e.g.',
    ') são recusados com a mensagem do erro. Salvar sem mudanças não cria versão.':
      ') are rejected with the error message. Saving without changes does not create a version.',
    'Salvo como v': 'Saved as v', 'Sem mudanças': 'No changes', 'JSON inválido:': 'Invalid JSON:',
    // ---- conectar
    'Conectar a ferramentas — plug and play, opcional por ferramenta': 'Connect to tools — plug and play, optional per tool',
    ': o agente vira uma': ': the agent becomes a', 'que o LLM da ferramenta chama (todas as plataformas).':
      'that the tool\'s LLM calls (all platforms).', ': o agente vira um': ': the agent becomes a',
    'no seletor do chat e conduz a conversa — recebe anexos e usa as próprias tools (LibreChat, Open WebUI, OpenCode, SDKs). Cada conexão gera uma chave só desta ferramenta e deste agente,':
      'in the chat picker and leads the conversation — it receives attachments and uses its own tools (LibreChat, Open WebUI, OpenCode, SDKs). Each connection creates a key just for this tool and this agent,',
    'em seu nome': 'in your name', 'Como ferramenta (MCP)': 'As a tool (MCP)', 'Como modelo': 'As a model',
    'Conexões ativas (': 'Active connections (', 'Nenhuma ainda — escolha uma ferramenta abaixo.': 'None yet — pick a tool below.',
    'A chave aparece só agora.': 'The key is shown only now.',
    'Para desligar, use “Desconectar” acima (só esta ferramenta perde o acesso).':
      'To turn it off, use “Disconnect” above (only this tool loses access).', 'Conexão criada (': 'Connection created (',
    'Configuração copiada': 'Configuration copied', '? Essa ferramenta perde o acesso ao agente.': '? This tool loses access to the agent.',
    'Testar conexão — agente de código': 'Test connection — coding agent',
    'Faz o caminho do chat do VS Code, Cline, Roo e Continue: manda uma ferramenta do cliente, confere que o agente a chama (stream com':
      'Follows the path of the VS Code, Cline, Roo and Continue chats: sends a client tool and checks that the agent calls it (stream with',
    ') e que usa o resultado para responder. Custa uma chamada curta ao LLM.':
      ') and uses the result to answer. Costs one short LLM call.',
    'Este agente ainda não está em': 'This agent is not yet in', ': as conexões apontam para': ': connections point to',
    'e só respondem depois do ship.': 'and only answer after the ship.', 'VS Code — extensão Agent Hangar': 'VS Code — Agent Hangar extension',
    'Baixar extensão (.vsix)': 'Download extension (.vsix)', 'Abrir no VS Code': 'Open in VS Code',
    'Baixe e instale a extensão (': 'Download and install the extension (', 'ou Extensions → … → Install from VSIX).':
      'or Extensions → … → Install from VSIX).', 'Clique em': 'Click', ', confirme aqui no portal e pronto.':
      ', confirm here in the portal and you are done.',
    ', o agente lê e edita o seu projeto e roda os testes no terminal, com a sua aprovação. A extensão também traz o MCP da plataforma (criar e editar agentes sem sair do editor). O login é pelo portal: nada de copiar chave.':
      ', the agent reads and edits your project and runs the tests in the terminal, with your approval. The extension also brings the platform MCP (create and edit agents without leaving the editor). Sign-in goes through the portal: no key to copy.',
    'Conectar o VS Code': 'Connect VS Code', 'Agent Hangar: Entrar pelo portal': 'Agent Hangar: Sign in through the portal',
    'Pedido incompleto. Comece pelo VS Code: comando': 'Incomplete request. Start from VS Code: command',
    'Esta sessão não tem um usuário (sessão de emergência). Entre com a sua conta para conectar o VS Code.':
      'This session has no user (emergency session). Sign in with your account to connect VS Code.',
    'Se o VS Code não abriu,': 'If VS Code did not open,', 'Conectar clientes': 'Connect clients',
    // ---- OAuth / apps conectados
    'Conectar um app': 'Connect an app', 'Comece de novo pelo app.': 'Start again from the app.',
    'Esta sessão não tem um usuário (sessão de emergência). Entre com a sua conta para conectar o app.':
      'This session has no user (emergency session). Sign in with your account to connect the app.',
    'quer usar o Agent Hangar como': 'wants to use Agent Hangar as',
    'O app poderá usar o MCP da plataforma com os seus times e papéis: listar, criar, testar e publicar agentes que você pode mexer.':
      'The app will be able to use the platform MCP with your teams and roles: list, create, test and publish the agents you can work on.',
    'Depois de autorizar, você volta para': 'After authorizing, you go back to', '. Se não reconhece este endereço,':
      '. If you do not recognize this address,', 'não autorize': 'do not authorize', 'O acesso aparece em': 'The access appears in',
    'Minhas chaves → Apps conectados': 'My keys → Connected apps', 'Voltando para': 'Going back to',
    'Apps conectados (OAuth)': 'Connected apps (OAuth)', '(como admin, você vê os de todos)': '(as an admin, you see everyone\'s)',
    'Nenhum app conectado. Veja': 'No connected apps. See', 'Apps registrados': 'Registered apps', 'Nenhum app registrado': 'No registered apps',
    'Apps que se registraram para pedir acesso (registro dinâmico). Bloquear derruba todas as autorizações do app e impede novas. Redirects permitidos: variável':
      'Apps that registered to request access (dynamic registration). Blocking removes all of the app\'s authorizations and prevents new ones. Allowed redirects: variable',
    'Autorizações ativas': 'Active authorizations', 'Autorizado': 'Authorized', 'Último uso': 'Last used', 'Pessoa': 'Person', 'App': 'App',
    'Estes apps exigem um endereço HTTPS público: publique o hangar atrás de um domínio ou túnel (hangar setup → endereço).':
      'These apps require a public HTTPS address: put the hangar behind a domain or tunnel (hangar setup → address).',
    // ---- chaves
    'Nova chave': 'New key', 'Nenhuma chave ainda': 'No keys yet', 'Chave revogada': 'Key revoked', 'Suas chaves.': 'Your keys.',
    'Todas as chaves da empresa.': 'All the company\'s keys.', 'Prefixo': 'Prefix', 'Escopo': 'Scope', 'Criada': 'Created',
    'O valor da chave aparece uma única vez.': 'The key value is shown only once.', '. O valor da chave aparece uma única vez.':
      '. The key value is shown only once.', 'Ctrl/Cmd+clique para vários': 'Ctrl/Cmd+click for several',
    '(obrigatório)': '(required)', '(sem seleção, só admin: invoca todos)': '(no selection, admin only: invokes all)',
    'Copie agora — não será exibido de novo': 'Copy it now — it will not be shown again', 'os seus': 'yours',
    'Revogar a chave "': 'Revoke the key "', '"? A ferramenta que usa essa chave para de funcionar.': '"? The tool using this key stops working.',
    // ---- montar a partir do catálogo
    '1. Reusar antes de construir': '1. Reuse before you build', '2. O agente novo': '2. The new agent',
    'Descreva o agente: o hangar procura no catálogo da empresa (só o que você vê, só versões em produção) agentes, skills e MCPs parecidos. Escolha as peças — os agentes existentes':
      'Describe the agent: the hangar searches the company catalog (only what you can see, only versions in production) for similar agents, skills and MCPs. Pick the pieces — existing agents',
    'não são alterados': 'are not changed', ': o novo agente chama os especialistas como estão ou começa de uma':
      ': the new agent calls the specialists as they are or starts from a', 'cópia': 'copy', 'da base.': 'of the base.',
    'O que o agente deve fazer': 'What the agent should do', 'Capacidades (opcional, uma por linha — melhora a busca)':
      'Capabilities (optional, one per line — improves the search)', 'Procurar peças no catálogo': 'Search the catalog for pieces',
    'busca semântica (embeddings locais da memória)': 'semantic search (memory\'s local embeddings)',
    'busca por palavras (ligue a memória para busca semântica)': 'keyword search (turn on memory for semantic search)',
    'Recomendação:': 'Recommendation:', 'Agentes parecidos': 'Similar agents', 'Usar como': 'Use as',
    'muito parecido': 'very similar', 'parecido': 'similar', 'você pode usar': 'you can use', 'pedir acesso': 'request access',
    'sem acesso': 'no access', 'especialista': 'specialist', 'base (cópia)': 'base (copy)', 'Skills do catálogo': 'Catalog skills',
    'Habilidades que faltam': 'Missing skills', 'Falta:': 'Missing:', 'tem teste': 'has a test',
    'deixe em branco se não precisar': 'leave blank if not needed', 'Descreva o agente': 'Describe the agent',
    'Escolhendo peças no passo 1, o botão vira': 'When you pick pieces in step 1, the button becomes',
    'Montar agente': 'Compose agent', ': as instruções acima viram só a parte nova.': ': the instructions above become only the new part.',
    'Agente montado:': 'Agent composed:', 'tokens que não precisaram ser escritos': 'tokens that did not have to be written',
    'Construído a partir de': 'Built from', 'Usado por': 'Used by', 'Como': 'How', 'Base copiada': 'Copied base',
    'Especialistas': 'Specialists', 'Skills criadas': 'Skills created', 'Reaproveitado': 'Reused',
    'chama especialistas': 'calls specialists', 'cópia de uma base': 'copy of a base', 'base + especialistas': 'base + specialists',
    'peças do catálogo': 'catalog pieces', 'do zero': 'from scratch', 'cópia (base)': 'copy (base)',
    'Os agentes de origem não foram alterados; mudanças futuras deles não mudam este agente sem um novo teste.':
      'The source agents were not changed; their future changes do not change this agent without a new test.',
    'Agentes montados a partir deste — ele continua igual; estes o chamam (especialista) ou começaram de uma cópia dele (base).':
      'Agents composed from this one — it stays the same; they call it (specialist) or started from a copy of it (base).',
    'Nome': 'Name', 'Objetivo': 'Goal', 'Agente de chat (LLM + tools/MCP)': 'Chat agent (LLM + tools/MCP)',
    'Conexão de LLM': 'LLM connection', 'testar e shipar em seguida': 'test and ship right after',
    'Nome, objetivo e saída final são obrigatórios': 'Name, goal and final output are required',
    'O jeito principal é pedir pelo chat (MCP) — este formulário cobre o básico; depois refine na aba': 'The main way is to ask through chat (MCP) — this form covers the basics; then refine in the tab',
    'padrão da empresa (': 'company default (', '— só o time vê': '— only the team sees it',
    '— no catálogo, uso sob pedido': '— in the catalog, use on request', '— qualquer pessoa da empresa usa': '— anyone in the company can use it',
    'pessoa ou canal para dúvidas (opcional)': 'person or channel for questions (optional)', 'o que o agente faz': 'what the agent does',
    'o que ele entrega': 'what it delivers', 'como ele deve se comportar': 'how it should behave',
    // ---- memória
    'Carregando memória…': 'Loading memory…', 'Memória (': 'Memory (', 'Memória apagada': 'Memory deleted',
    'Apagar toda a memória de': 'Delete all the memory of', 'Fato': 'Fact', 'Vale desde': 'Valid since', 'Situação': 'Status',
    'compartilhada com o time': 'shared with the team', 'compartilhada com a empresa': 'shared with the company', 'só o agente': 'agent only',
    'Nenhum fato ainda. O agente grava com memory__remember durante as conversas.': 'No facts yet. The agent stores them with memory__remember during conversations.',
    'Este agente não guarda memória entre conversas. Com memória, ele ganha as ferramentas': 'This agent does not keep memory between conversations. With memory, it gets the tools',
    'Memória ligada — faça o deploy em stage': 'Memory turned on — deploy to stage',
    ': grava fatos (clientes, decisões, preferências) num grafo com histórico — um fato que muda não é apagado, fica marcado como substituído a partir da data da mudança.':
      ': stores facts (customers, decisions, preferences) in a graph with history — a fact that changes is not deleted, it is marked as replaced from the date of the change.',
    'Clique em carregar.': 'Click load.', 'Apagar memória': 'Delete memory',
    // ---- agendamentos
    'Nenhum agendamento. O agente roda sozinho no dia e hora escolhidos, com a mensagem que você definir.':
      'No schedules. The agent runs on its own at the chosen day and time, with the message you set.',
    'Nenhuma execução ainda.': 'No runs yet.', 'ainda não rodou': 'has not run yet', 'Execução:': 'Run:',
    'Execução concluída — veja o histórico': 'Run completed — see the history', 'Agendamento excluído': 'Schedule deleted',
    'Excluir o agendamento e o histórico dele?': 'Delete the schedule and its history?', 'Escolha data e hora': 'Pick a date and time',
    'ex.: Gere o resumo de vendas da semana anterior com os 5 principais clientes': 'e.g. Write last week\'s sales summary with the top 5 customers',
    'Novo agendamento': 'New schedule', 'O que o agente deve fazer a cada disparo': 'What the agent should do on each run',
    'Frequência': 'Frequency', 'Hora': 'Time', 'Fuso horário': 'Time zone', 'Todo dia': 'Every day', 'Dias úteis': 'Weekdays',
    'Toda semana': 'Every week', 'Todo mês': 'Every month', 'Uma vez': 'Once', 'Dia da semana': 'Day of the week',
    'Dia do mês': 'Day of the month', 'Mensagem': 'Message', 'Próximo disparo': 'Next run', 'Última execução': 'Last run',
    'de segunda a sexta às': 'Monday to Friday at', 'Agendar': 'Schedule',
    // ---- aprovações e acesso
    'Promoções para produção (quatro olhos: quem pediu não aprova) e pedidos de uso de agentes dos seus times':
      'Promotions to production (four eyes: whoever asked does not approve) and requests to use your teams\' agents',
    'Para você decidir (': 'For you to decide (', 'Nada pendente.': 'Nothing pending.', 'Seus pedidos de acesso': 'Your access requests',
    'Nenhum. Procure agentes no': 'None. Look for agents in the', 'catálogo da empresa': 'company catalog', 'Suas promoções': 'Your promotions',
    'Aprovar e publicar esta versão em produção?': 'Approve and publish this version to production?',
    'Aprovado — agente publicado em produção': 'Approved — agent published to production', 'Promoção recusada': 'Promotion rejected',
    'Pedido recusado': 'Request rejected', 'Pedido enviado ao time dono do agente': 'Request sent to the agent\'s owner team',
    'Para que você vai usar este agente? (vai para o mantenedor do time)': 'What will you use this agent for? (goes to the team maintainer)',
    'Pedidos e acessos concedidos (': 'Requests and granted access (',
    'Nenhum pedido. Com visibilidade “empresa”, pessoas de outros times pedem acesso pelo catálogo.':
      'No requests. With “company” visibility, people from other teams request access through the catalog.',
    'Revogar o acesso? As chaves dessa pessoa para este agente param na hora.': 'Revoke access? This person\'s keys for this agent stop at once.',
    'Abrir mão do acesso? Suas chaves para este agente param de funcionar.': 'Give up access? Your keys for this agent stop working.',
    'Ao restringir o acesso, as chaves de quem perdeu permissão são revogadas na hora.': 'When access is restricted, the keys of whoever lost permission are revoked at once.',
    'Expor instruções e spec (somente leitura) para quem não é do time': 'Show instructions and spec (read-only) to people outside the team',
    'Produção exige aprovação de outro mantenedor (quatro olhos)': 'Production requires approval from another maintainer (four eyes)',
    'aprovação p/ produção': 'approval for production', 'Precisa de:': 'Needs:', '· precisa de': '· needs',
    // ---- times e usuários
    'Cada agente pertence a um time. Papéis:': 'Each agent belongs to a team. Roles:', 'A lista de membros é visível para quem é do time.':
      'The member list is visible to people on the team.', 'Agentes do time (': 'Team agents (', 'Time atualizado': 'Team updated',
    'Time excluído': 'Team deleted', 'Excluir o time': 'Delete the team', 'Dê um nome ao time': 'Give the team a name',
    'quem vai gerenciar o time': 'who will manage the team', 'ex.: Dados e BI': 'e.g. Data and BI', 'Descrição': 'Description',
    'Descrição (opcional)': 'Description (optional)', 'descrição': 'description', 'descrição (opcional)': 'description (optional)',
    'Orçamento mensal (US$)': 'Monthly budget (US$)', 'Ele é do time': 'They are on the team',
    'do time? As chaves dessa pessoa para agentes do time param na hora.': 'from the team? This person\'s keys for the team\'s agents stop at once.',
    'Criados no primeiro login (OAuth2), por SCIM ou pré-cadastrados.': 'Created at first sign-in (OAuth2), by SCIM or pre-registered.',
    'Papel na empresa': 'Company role', 'Último login': 'Last sign-in', 'Usuário atualizado': 'User updated', 'Usuário cadastrado': 'User registered',
    'Nenhum usuário': 'No users', 'e-mail da pessoa': 'person\'s e-mail', 'e-mail (entra por SSO)': 'e-mail (signs in with SSO)',
    'usuário (conta local, opcional)': 'username (local account, optional)', 'senha da conta local': 'local account password',
    'Nome de usuário para': 'Username for', '(minúsculas, números, . _ -):': '(lowercase, numbers, . _ -):',
    'Nova senha para': 'New password for', '(mínimo 8 caracteres). As sessões atuais dessa pessoa serão encerradas.':
      '(at least 8 characters). This person\'s current sessions will be ended.', 'Nova senha (mínimo 8 caracteres):':
      'New password (at least 8 characters):', 'Repita a nova senha:': 'Repeat the new password:', 'As senhas não conferem': 'Passwords do not match',
    '? Sessões encerradas e todas as chaves revogadas na hora.': '? Sessions ended and all keys revoked at once.', 'pré-cadastro': 'pre-registered',
    'o seu time': 'your team', 'os seus times': 'your teams', 'org/time': 'org/team', 'todos os times': 'all teams',
    // ---- login
    'Use a conta da empresa.': 'Use your company account.', 'Entrar com token (emergência, chave admin ou token pessoal)':
      'Sign in with a token (emergency, admin key or personal token)', 'O token vira uma sessão (cookie seguro) e não fica salvo no navegador.':
      'The token becomes a session (secure cookie) and is not stored in the browser.', 'Token inválido': 'Invalid token',
    'Usuário ou senha inválidos': 'Invalid username or password', 'Sessão expirada — entre de novo': 'Session expired — sign in again',
    'Os agentes de IA da empresa, do hangar à produção.': 'The company\'s AI agents, from the hangar to production.',
    'Construa, teste e publique agentes com segurança — cada time com os seus.': 'Build, test and ship agents safely — each team with its own.',
    'Usuário ou e-mail': 'Username or e-mail', 'Senha': 'Password', 'Nenhum login corporativo configurado ainda. Entre com o token de admin e configure em':
      'No company sign-in configured yet. Sign in with the admin token and configure it in', 'UI desatualizada no cache do navegador': 'Outdated UI in the browser cache',
    // ---- catálogo de skills, MCPs, provedores e SSO (console)
    'Skills e MCPs': 'Skills and MCPs', 'conteúdo': 'content', 'conteúdo (markdown)': 'content (markdown)', 'URL do MCP': 'MCP URL',
    '+ Conectar MCP remoto': '+ Connect remote MCP', 'Conectar (abre a tela de autorização)': 'Connect (opens the authorization screen)',
    'Origem pública para o navegador (opcional)': 'Public origin for the browser (optional)', 'Remover o MCP remoto': 'Remove the remote MCP',
    '? Os tokens são revogados e os agentes perdem essas ferramentas.': '? The tokens are revoked and the agents lose these tools.',
    '? Agentes que o usam perdem essas ferramentas.': '? Agents that use it lose these tools.', 'Falha ao conectar:': 'Failed to connect:',
    'MCPs remotos com OAuth (': 'Remote MCPs with OAuth (', 'aguardando autorização': 'waiting for authorization',
    '" conectado — use-o nos agentes pelo nome': '" connected — use it in agents by name', '" nos agentes': '" in agents',
    'Servidores MCP prontos, mantidos no catálogo oficial da Docker e rodando cada um num container isolado com imagem assinada. Ao ativar, o servidor vira o item':
      'Ready MCP servers, maintained in Docker\'s official catalog, each running in an isolated container with a signed image. When turned on, the server becomes the item',
    'deste catálogo e os agentes passam a usá-lo pela spec (': 'of this catalog and agents use it through the spec (',
    'gateway fora do ar': 'gateway down', 'Já conectados (': 'Already connected (', 'Gerenciar (editar/remover) na aba': 'Manage (edit/remove) in the tab',
    'nome da conexão': 'connection name', 'conexão openai (vazio = mock)': 'openai connection (empty = mock)',
    'US$ por 1M tokens de entrada': 'US$ per 1M input tokens', 'US$ por 1M tokens de saída': 'US$ per 1M output tokens',
    'US$/1M saída (opcional)': 'US$/1M output (optional)', 'Nenhuma — sem conexão, os agentes rodam em': 'None — without a connection, agents run on',
    'Nenhuma — registre pelo chat (': 'None — register it through chat (', ') ou abaixo': ') or below', 'Código e LLMs': 'Code and LLMs',
    'Qualquer conexão': 'Any connection', 'Só conexões aprovadas': 'Approved connections only', 'só conexões aprovadas': 'approved connections only',
    'No modo agente de código (VS Code, Cline, Continue) e nas avaliações de código, arquivos e saídas de terminal dos devs vão para o LLM do agente. Com':
      'In coding-agent mode (VS Code, Cline, Continue) and in code evaluations, the developers\' files and terminal output go to the agent\'s LLM. With',
    ', esse modo só funciona com conexões marcadas como aprovadas para código (ex.: o gateway corporativo). Segredos óbvios (chaves, tokens) são sempre mascarados antes de ir ao modelo.':
      ', this mode only works with connections approved for code (e.g. the company gateway). Obvious secrets (keys, tokens) are always masked before going to the model.',
    'Como funciona': 'How it works', 'Configuração': 'Configuration', 'Primeiro acesso e emergência': 'First access and emergency',
    'continua funcionando como acesso de emergência (“Entrar com token”): guarde-o num cofre e use só se o SSO cair.':
      'keeps working as emergency access (“Sign in with a token”): keep it in a vault and use it only if SSO goes down.',
    'OAuth2 genérico': 'Generic OAuth2', 'Nome no botão (ex.: Keycloak)': 'Button label (e.g. Keycloak)', 'Escopos (espaço)': 'Scopes (space-separated)',
    'Campo de grupos no userinfo (padrão groups)': 'Groups field in userinfo (default: groups)',
    'Confiar no e-mail sem email_verified (só se o provedor garante)': 'Trust the e-mail without email_verified (only if the provider guarantees it)',
    'Domínios permitidos (opcional)': 'Allowed domains (optional)', 'Domínios permitidos (vírgula) — ex.: empresa.com.br': 'Allowed domains (comma-separated) — e.g. company.com',
    'Organizações do GitHub exigidas (vírgula)': 'Required GitHub organizations (comma-separated)', 'Ler times do GitHub para mapear': 'Read GitHub teams to map',
    'Ler grupos (GroupMember.Read.All, consentimento de admin)': 'Read groups (GroupMember.Read.All, admin consent)',
    'Tenant (ID ou domínio, ex.: empresa.onmicrosoft.com)': 'Tenant (ID or domain, e.g. company.onmicrosoft.com)',
    'Grupos → times': 'Groups → teams', 'Nenhum mapeamento': 'No mappings',
    'Quem está no grupo entra no time com o papel indicado a cada login (OAuth2) ou mudança no diretório (SCIM). Quem foi adicionado à mão não é mexido. Microsoft: ID ou nome do grupo · GitHub:':
      'Group members join the team with the given role at each sign-in (OAuth2) or directory change (SCIM). People added by hand are not touched. Microsoft: group ID or name · GitHub:',
    '· OAuth2: valor do claim de grupos · SCIM: nome do grupo provisionado.': '· OAuth2: groups claim value · SCIM: provisioned group name.',
    'URL do locatário:': 'Tenant URL:', '(cole como “Token secreto” no diretório):': '(paste it as the “Secret token” in the directory):',
    'Revogar o token SCIM? O diretório para de sincronizar.': 'Revoke the SCIM token? The directory stops syncing.',
    'No Entra ID: Aplicativos empresariais → seu app → Provisionamento → Automático. Okta: app SCIM 2.0. Desligar alguém no diretório encerra as sessões e revoga as chaves dele aqui.':
      'In Entra ID: Enterprise applications → your app → Provisioning → Automatic. Okta: SCIM 2.0 app. Deactivating someone in the directory ends their sessions and revokes their keys here.',
    'Entra ID → Registros de aplicativo → Novo registro (conta só deste diretório) → Certificados e segredos. Permissões delegadas: User.Read (e GroupMember.Read.All para grupos).':
      'Entra ID → App registrations → New registration (this directory only) → Certificates & secrets. Delegated permissions: User.Read (and GroupMember.Read.All for groups).',
    'GitHub → Settings → Developer settings → OAuth Apps (ou da organização). Escopos pedidos: read:user, user:email, read:org.':
      'GitHub → Settings → Developer settings → OAuth Apps (or the organization\'s). Requested scopes: read:user, user:email, read:org.',
    'Google Cloud Console → APIs e serviços → Credenciais → ID do cliente OAuth (Aplicativo da Web). Tela de consentimento “Interno” restringe à sua organização.':
      'Google Cloud Console → APIs & Services → Credentials → OAuth client ID (Web application). An “Internal” consent screen restricts it to your organization.',
    'Qualquer provedor OAuth2 com endpoint de userinfo: Keycloak, Okta, Auth0, Authentik… Para SAML, use o Keycloak como ponte (identity brokering).':
      'Any OAuth2 provider with a userinfo endpoint: Keycloak, Okta, Auth0, Authentik… For SAML, use Keycloak as a bridge (identity brokering).',
    'Crie um em': 'Create one in', 'Nome (vira o nome no catálogo)': 'Name (becomes the catalog name)', 'Só developers e maintainers de um time aplicam templates.':
      'Only developers and maintainers of a team apply templates.', 'Nenhum template em TEMPLATES_DIR': 'No templates in TEMPLATES_DIR',
    '(Claude, Codex, OpenCode, LibreChat, Open WebUI…) ou teste no': '(Claude, Codex, OpenCode, LibreChat, Open WebUI…) or try it in the',
    '(gere em': '(generate it in', 'para métricas por canal.': 'for per-channel metrics.', ', a partir de um': ', from a',
    ': conforme os times.': ': according to teams.', ': lê tudo (uso, custo, auditoria, specs).': ': reads everything (usage, cost, audit, specs).',
    ': provisionamento pelo diretório.': ': provisioning from the directory.', 'Uso visível só para o time.': 'Usage visible only to the team.',
    'Agentes:': 'Agents:', 'Times (': 'Teams (', 'Catálogo da empresa (': 'Company catalog (', 'Time “': 'Team “', ')? Não dá para desfazer.': ')? This cannot be undone.',
    'sem efeito (nova versão)': 'no effect (new version)', 'só este agente': 'this agent only', 'nenhum definido': 'none set', 'do agente.': 'of the agent.',
  };
  window.I18N = D;
  // seletor de idioma: no rodapé do menu e, na tela de login, no canto da página
  const langSwitch = cls => {
    const b = document.createElement('button');
    b.className = 'ghost lang-sw ' + cls; b.setAttribute('data-noi18n', ''); b.type = 'button';
    b.title = LANG === 'en' ? 'Mudar para português' : 'Switch to English';
    b.innerHTML = LANG === 'en' ? 'PT · <b>EN</b>' : '<b>PT</b> · EN';
    b.onclick = () => window.setLang(LANG === 'en' ? 'pt' : 'en');
    return b;
  };
  const addSwitches = () => {
    const foot = document.querySelector('.side-foot .row');
    if (foot && !foot.querySelector('.lang-sw')) foot.insertBefore(langSwitch('on-dark'), document.getElementById('logout'));
    if (!document.querySelector('.lang-float')) document.body.append(langSwitch('lang-float'));
  };
  if (document.body) addSwitches(); else document.addEventListener('DOMContentLoaded', addSwitches);
  window.t = s => (LANG === 'en' && D[s]) || s;
  if (LANG !== 'en') return;

  const exact = new Map(Object.entries(D));
  // dentro de um texto maior ("5 chamadas · …") só se trocam frases (com espaço) e palavras de status: palavras soltas comuns
  // ("time", "empresa") estragariam textos misturados e dados
  const WORDS = new Set(['Rascunho', 'Testado', 'Produção', 'Rodando', 'Falhou', 'Parado', 'Substituído', 'substituído', 'multiagente',
    'mantenedor', 'privado', 'descrita', 'concluído', 'pendente', 'aprovado', 'recusado', 'revogada', 'revogado', 'bloqueado', 'produção']);
  const reEsc = k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // frases curtas ("no ar", "e com") também aparecem dentro de dados: só frases de 10+ letras entram aqui
  const W = /[\wÀ-ú]/;
  const parts = Object.entries(D).filter(([k]) => (/\s/.test(k.trim()) && k.trim().length >= 10) || WORDS.has(k))
    .sort((a, b) => b[0].length - a[0].length)
    .map(([k, v]) => [k, new RegExp((W.test(k[0]) ? '(^|[^\\wÀ-ú])' : '()') + reEsc(k) + (W.test(k[k.length - 1]) ? '(?![\\wÀ-ú])' : ''), 'g'), v]);
  // números com unidade, montados no código ("8 erros", "2 d atrás", "3 agentes")
  const UNITS = [[/(\d+(?:[.,]\d+)?%?) erros\b/g, '$1 errors'], [/(\d+) agentes\b/g, '$1 agents'], [/(\d+) agente\b/g, '$1 agent'],
    [/(\d+) membros\b/g, '$1 members'], [/(\d+) membro\b/g, '$1 member'], [/(\d+) execuções\b/g, '$1 runs'],
    [/(\d+) chamadas\b/g, '$1 calls'], [/(\d+) dias\b/g, '$1 days'], [/(\d+ (?:min|h|d)) atrás/g, '$1 ago'],
    [/\bagente\(s\)/g, 'agent(s)'], [/\blacuna\(s\)/g, 'gap(s)'], [/\brodada\(s\)/g, 'round(s)'], [/\bferramenta\(s\)/g, 'tool(s)'],
    [/ \(padrão\)$/, ' (default)'], [/^Agentes: /, 'Agents: '], [/^por (?=\S)/, 'by '], [/ em (\d+ days)\b/g, ' in $1'], [/^até (?=\d)/, 'until '], [/^Bom dia,/, 'Good morning,'], [/^Boa tarde,/, 'Good afternoon,'], [/^Boa noite,/, 'Good evening,'],
    [/(^|[^\d.,])1 calls\b/, '$11 call'], [/^Mantenedor · /, 'Maintainer · '], [/^Membro · /, 'Member · '],
    [/^Este texto foi escrito para a v(\d+); a versão descrita agora é a v(\d+)\. Confira se ainda vale\.$/,
      'This text was written for v$1; the version described is now v$2. Check that it still applies.'],
    [/(\d+)\/(\d+) checks aprovados/, '$1/$2 checks passed'], [/\((\d+) ativa\(s\)\)/, '($1 active)'],
    [/ — Como ferramenta \(MCP\)$/, ' — As a tool (MCP)'], [/ — Como modelo$/, ' — As a model'],
    [/^Já existe um guia escrito para a v(\d+); ele aparece aqui quando essa versão for publicada\.$/,
      'A guide is already written for v$1; it shows here when that version is published.'],
    [/\(empresa\)$/, '(company)'], [/\(privado\)$/, '(private)'], [/\(aberto\)$/, '(open)']];
  const PTISH = /[ãõçáéíóúâêôàÁÉÍÓÚÇ]|\b(de|do|da|para|com|sem|seu|sua|agente|agentes|chave|nenhum|em|por|que|erros|membros|dias|chamadas|bom|boa|mantenedor|membro|como|ativa|aprovados)\b/i;
  const tr = text => {
    const raw = text.trim();
    if (!raw || !/[A-Za-zÀ-ú]/.test(raw)) return text;
    const t = raw.replace(/\s+/g, ' ');  // textos quebrados em várias linhas no código-fonte
    if (exact.has(t)) return text.replace(raw, exact.get(t));
    const c = t.match(/^(.*?) ?\((\d+)\)$/);  // títulos com contagem: "Times (4)"
    if (c) { const h = exact.get(c[1]) || (exact.get(c[1] + ' (') || '').replace(/ \($/, ''); if (h) return text.replace(raw, `${h} (${c[2]})`); }
    if (!PTISH.test(t)) return text;
    let out = t;
    for (const [k, re, en] of parts) if (out.includes(k)) out = out.replace(re, (m, pre) => pre + en);
    for (const [re, en] of UNITS) out = out.replace(re, en);
    return out === t ? text : text.replace(raw, out);
  };
  window.tr = tr;
  // dados não se traduzem: conversas, saídas de agentes, código, specs, memória e campos de formulário
  const SKIP = 'script,style,code,pre,textarea,.msg,.run-out,.chat,.md,[data-noi18n]';
  const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  const skip = el => el && el.closest && el.closest(SKIP);
  const walk = root => {
    if (!root) return;
    if (root.nodeType === 3) {
      if (!skip(root.parentElement)) { const v = tr(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; }
      return;
    }
    if (root.nodeType !== 1 || skip(root)) return;
    for (const a of ATTRS) if (root.hasAttribute && root.hasAttribute(a)) { const v = tr(root.getAttribute(a)); if (v !== root.getAttribute(a)) root.setAttribute(a, v); }
    const attrs = el => { for (const a of ATTRS) if (el.hasAttribute(a)) { const v = tr(el.getAttribute(a)); if (v !== el.getAttribute(a)) el.setAttribute(a, v); } };
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: n => {
        if (n.nodeType !== 1) return NodeFilter.FILTER_ACCEPT;
        if (n.tagName === 'TEXTAREA' && !n.closest('[data-noi18n]')) attrs(n);  // o texto digitado não, o placeholder sim
        return skip(n) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      } });
    let n;
    while ((n = it.nextNode())) {
      if (n.nodeType === 3) { const v = tr(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; }
      else attrs(n);
    }
  };
  const start = () => {
    walk(document.body);
    document.title = tr(document.title);
    new MutationObserver(ms => { for (const m of ms) {
      if (m.type === 'characterData') walk(m.target);
      else m.addedNodes.forEach(walk);
    } }).observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
  const _confirm = window.confirm.bind(window), _prompt = window.prompt.bind(window), _alert = window.alert.bind(window);
  window.confirm = m => _confirm(tr(String(m)));
  window.prompt = (m, d) => _prompt(tr(String(m)), d);
  window.alert = m => _alert(tr(String(m)));
})();
