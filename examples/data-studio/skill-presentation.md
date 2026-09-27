# Design de apresentações (create_presentation)

## Estrutura (padrão executivo)
1. **title**: título orientado a mensagem ("Vendas crescem 18% no 1º semestre"), não "Análise de vendas".
2. **kpis**: 3 a 4 números que resumem a história (use `sql` para valores reais e `format` adequado).
3. De 2 a 5 slides de evidência, cada um com UMA mensagem:
   - **chart**: título = conclusão do gráfico; caption = fonte/nota.
   - **table**: no máximo 8 linhas × 6 colunas.
4. **bullets** "Recomendações / Próximos passos" com 3 a 5 itens acionáveis.
5. Use **section** para separar blocos em decks com mais de 8 slides.

## Regras de design
- Uma ideia por slide. No máximo 5 bullets por slide, cada um com até ~12 palavras. Sub-itens começam com dois
  espaços.
- Escolha do gráfico: tendência → line/area; comparação entre categorias → column (poucas) ou bar (muitas/nomes
  longos); composição → pie/doughnut (até 5 fatias) ou stacked; relação entre duas variáveis → scatter.
- Ordene as categorias por valor (exceto tempo). Limite a 12 categorias; agrupe o resto em "Outros".
- theme: `corporate` para diretoria, `dark` para palcos/telas, `light` como padrão; `accent` com a cor da marca
  quando o usuário informar.
- Coloque o racional detalhado em `notes` (notas do apresentador), não no slide.
- Figuras do matplotlib geradas antes (figura_N.png) entram com `{type:'image', path:'figura_N.png'}`.
- Padrão formats=['pptx','html']: o PPTX é editável no PowerPoint, e o HTML abre direto no navegador
  (setas/clique para navegar, F para tela cheia).
