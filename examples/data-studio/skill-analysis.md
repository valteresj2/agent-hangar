# Playbook de análise de dados

## 1. Perfil (sempre)
- Linhas, colunas, tipos, % de nulos, cardinalidade, faixas (min/máx), datas (período coberto).
- Verifique chaves duplicadas, datas como texto, números com vírgula decimal ("1.234,56"), unidades misturadas e
  categorias escritas de formas diferentes ("SP", "São Paulo").

## 2. Preparação
- Converta tipos explicitamente (`pd.to_datetime(..., dayfirst=True)`, `pd.to_numeric(..., errors='coerce')`).
- Registre toda limpeza feita, com as linhas afetadas, e conte isso ao usuário.
- Para bases grandes, prefira DuckDB (`run_sql`). Ele lê CSV/Parquet/Excel do workspace sem carregar tudo no pandas.

## 3. Análise exploratória
- Comece pelo que responde à pergunta. Depois procure o que surpreende: variações, outliers (IQR/z-score),
  concentração (Pareto 80/20), sazonalidade, tendência e comparação entre segmentos.
- Séries temporais: agregue no grão certo (dia/semana/mês) e compare período contra período (MoM, YoY).
- Correlação não é causalidade: diga isso quando relevante.

## 4. Estatística quando fizer diferença
- Diferença entre grupos: teste t / Mann-Whitney; proporções: qui-quadrado; tendência: regressão linear
  (statsmodels) com p-valor e R²; previsão simples: médias móveis, ETS/Holt-Winters (statsmodels).
- Segmentação: KMeans (sklearn) com variáveis padronizadas; explique os clusters em linguagem de negócio.
- Reporte incerteza (intervalos de confiança) em vez de números falsamente precisos.

## 5. Comunicação
- Três a cinco achados, cada um com número, contexto e implicação ("Sul cresce 18% MoM, puxado pelo produto B →
  priorizar estoque de B no Sul").
- Formate números no padrão brasileiro (1.234,5; R$; %) quando o usuário escrever em português.
