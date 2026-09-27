# Design de dashboards (create_dashboard)

## Layout
- **KPIs no topo**, com 3 a 6 indicadores (total, variação, ticket médio, taxa…). Cada um tem `sql` retornando 1
  valor, `format` (int/dec/pct/brl/usd) e `delta` quando houver comparação.
- **insights**: 3 a 5 frases com os achados principais e seus números. Ficam logo abaixo dos KPIs.
- **Gráficos** (grade de 2 colunas): o mais importante usa `width: 2` (largura total), por exemplo a série temporal
  principal. Os demais usam width 1.
- **Tabela detalhada** no fim (`tables`, com filtro e ordenação embutidos), limitada a max_rows (padrão 500).

## Gráficos
- Cada gráfico tem `sql` que devolve a coluna de categoria/tempo (`x`) e uma ou mais colunas numéricas (`y`).
- Tipos: tendência → line/area; ranking → bar (horizontal) ordenado; comparação → column; composição →
  pie/doughnut/stacked; correlação → scatter; matriz (ex.: dia × hora) → heatmap (cada série = uma linha).
- Títulos descritivos com unidade ("Receita mensal (R$ mil)"); use x_title/y_title quando ajudar.
- Evite mais de 8 gráficos: prefira poucos e claros.

## Dados
- Os dados ficam embutidos no HTML (o arquivo abre offline, exceto a biblioteca do gráfico). Para bases enormes,
  agregue no SQL antes: um dashboard não precisa de 1 milhão de pontos.
