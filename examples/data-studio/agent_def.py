"""Definição compartilhada do agente Data Studio (skills e casos de teste) — usada por build_agent.py e
make_template.py."""
SKILLS = {
    "data-analysis-playbook": ("Método de análise de dados profunda (perfil, limpeza, EDA, estatística, conclusões)",
                               "skill-analysis.md"),
    "presentation-design": ("Como estruturar e desenhar apresentações executivas (PPTX/HTML)", "skill-presentation.md"),
    "dashboard-design": ("Como montar dashboards HTML claros e úteis", "skill-dashboard.md"),
}
TESTS = [
    {"name": "python no workspace", "input": "Use o Python para calcular a média de 3, 5 e 10. Responda só o número.",
     "expect_regex": r"\b6(\.0+)?\b"},
    {"name": "sql + planilha editada",
     "input": "Crie no workspace um CSV chamado teste_vendas.csv com colunas loja,valor e 4 linhas (A,10 / B,20 / "
              "A,5 / C,7). Depois some o valor por loja com SQL e me entregue o resultado como planilha Excel.",
     "judge": "A resposta deve mostrar A=15, B=20 e C=7 e conter um link para um arquivo .xlsx."},
    {"name": "apresentação pptx + html",
     "input": "Faça uma apresentação curta (3 slides) sobre por que usar DuckDB, com um gráfico de barras comparando "
              "velocidade relativa fictícia de 3 ferramentas. Quero PPTX e HTML.",
     "judge": "A resposta deve conter um link terminado em .pptx e outro terminado em .html."},
]
