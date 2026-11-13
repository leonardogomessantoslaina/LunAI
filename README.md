# LunAI

MVP em português: envie uma imagem JPG/PNG/WebP e pergunte sobre ela. O backend FastAPI oferece adaptadores independentes para OpenAI (API hospedada) e Ollama (modelo vision local); nenhum provedor fica embutido no frontend.

## Recomendação

**Para começar, use OpenAI API com `gpt-4o-mini`**, configure um teto de gastos no painel e acompanhe o uso. É um modelo multimodal que aceita imagens e tende a ser simples de integrar; pagamento por uso significa custo inicial baixo, mas não é gratuito e pode crescer conforme imagens/tokens. Na tabela oficial consultada em 2026-11-13, a página do modelo exibe preços de texto de **US$ 0,15 por milhão de tokens de entrada e US$ 0,60 por milhão de tokens de saída**; imagem é tarifada/converte em tokens conforme resolução e detalhes, portanto não estime o custo apenas pelo tamanho da pergunta. Consulte o preço atualizado antes de produção. A API tem limites de taxa e disponibilidade dependentes da conta.

**Opção local/gratuita em uso: Ollama + `llama3.2-vision:11b`**. O software/modelo pode ser executado sem pagar por chamada, mas exige baixar vários GB e hardware adequado. O modelo 11B é mais realista em GPU com cerca de 8–16 GB de VRAM, conforme quantização/contexto; CPU ou pouca memória funciona mais devagar, e o modelo 90B requer recursos substancialmente maiores. Requisitos reais variam com quantização, tamanho de contexto e concorrência. Há também `minicpm-v` no catálogo Ollama; verifique licença específica do modelo e termos aplicáveis antes de uso comercial.

O modelo Llama 3.2 Vision usa licença Llama 3.2, não uma licença permissiva OSI padrão. Revise o acordo e a política de uso da Meta, especialmente para distribuição/uso comercial. Local evita enviar imagem a um serviço externo, mas o computador e logs continuam sendo responsabilidade do operador; inferência local não equivale a privacidade garantida. Ollama é o runtime, não uma garantia de que cada modelo seja open-source ou livre de restrições.

Python e FastAPI são tecnologias sem custo de licença para este MVP. Usá-los não reduz tokens, custo de inferência, hospedagem nem requisitos de hardware por si só.

## Proteção básica contra abuso

O endpoint `/api/ask` limita por padrão 10 pedidos por IP a cada 60 segundos. Ajuste `RATE_LIMIT_REQUESTS` e `RATE_LIMIT_WINDOW_SECONDS` no `.env`. O limitador é em memória, apropriado apenas para desenvolvimento/uma instância: reiniciar o servidor zera o histórico, e múltiplos workers/instâncias não compartilham limites. Para produção, adicionar limitação distribuída (por exemplo Redis), autenticação, HTTPS e configuração explícita de proxies confiáveis; não confie em `X-Forwarded-For` fornecido diretamente pelo cliente.

## Validação automática

```bash
pytest -q
```

Os testes cobrem rota inicial, saúde do serviço e validação básica de uploads/perguntas e do limite de pedidos.

## Configuração

Requer Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Copie `.env.example` para `.env` e edite `.env` localmente. Para OpenAI, substitua `cole_sua_chave_aqui` por uma chave criada na plataforma, mantendo `MODEL_PROVIDER=openai` e `MODEL_NAME=gpt-4o-mini`. A chave nunca vai para o navegador e `.env` está excluído do Git. A API e seu faturamento são separados da assinatura ChatGPT. Não cole sua chave no chat nem a envie ao GitHub.

Para Ollama, instale pelo site oficial, baixe e teste um modelo vision:

```bash
ollama pull llama3.2-vision:11b
```

No `.env`, configure `MODEL_PROVIDER=ollama`, `MODEL_NAME=llama3.2-vision:11b`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`. O servidor Ollama deve estar ativo.

Inicie:

```bash
uvicorn src.main:app --reload
```

Acesse http://127.0.0.1:8000. Verificação simples: `GET /health`; documentação da API em `/docs`.

## Teste local passo a passo

1. Instale Python 3.10+ e extraia o projeto para uma pasta local.
2. Abra um terminal nessa pasta e crie/ative o ambiente virtual conforme as instruções acima.
3. Instale as dependências com `pip install -r requirements.txt`.
4. Copie `.env.example` para `.env`. Abra `.env` no editor e substitua `cole_sua_chave_aqui` pela sua chave da API. Não a envie por mensagem nem publique o arquivo.
5. Inicie o servidor com `uvicorn src.main:app --reload`.
6. Em outro terminal ou navegador, abra `http://127.0.0.1:8000/health`. Deve aparecer `"provider_configured": true`.
7. Abra `http://127.0.0.1:8000`, selecione uma foto comum e pequena, e pergunte algo verificável como “Quais objetos aparecem?”. Evite fotos pessoais ou sensíveis.
8. Confirme que a resposta faz sentido. Se der erro, confira o terminal e a seção de solução de problemas. Não compartilhe a chave em capturas de tela.

### Solução de problemas rápida

- `provider_configured: false`: confira se o arquivo chama-se exatamente `.env`, está na pasta do projeto e tem `MODEL_PROVIDER=openai` e `OPENAI_API_KEY` preenchida.
- Erro de autenticação: confirme que a chave foi criada na plataforma de API e que a conta tem acesso/faturamento configurado; ChatGPT Plus não inclui automaticamente créditos da API.
- Limite temporário: aguarde e confira cotas e limites no painel da API.
- Resposta muito lenta: tente imagem menor ou reduza `MODEL_TIMEOUT_SECONDS`/`MODEL_MAX_OUTPUT_TOKENS` conforme o caso.
- Nunca cole a chave em issues, prints públicos ou no GitHub. Se ela vazar, revogue-a no painel.

## Variáveis

| Variável | Uso |
|---|---|
| `MODEL_PROVIDER` | `openai` ou `ollama`; em branco deixa o MVP sem geração real |
| `MODEL_NAME` | Modelo multimodal habilitado na conta ou instalado localmente |
| `OPENAI_API_KEY` | Segredo só no servidor; obrigatório para OpenAI |
| `OPENAI_BASE_URL` | Endpoint OpenAI (HTTPS obrigatório) |
| `OLLAMA_BASE_URL` | Endpoint local (localhost) ou HTTPS |
| `MAX_UPLOAD_MB` | Tamanho máximo, 1–20 MB (padrão 10) |
| `MAX_QUESTION_CHARS` | Comprimento máximo da pergunta |
| `MODEL_TIMEOUT_SECONDS` | Timeout HTTP, 1–300 s |
| `MODEL_MAX_OUTPUT_TOKENS` | Limite de resposta, 1–4096 |

## Segurança, privacidade e limites

- Até 10 MB por padrão; somente JPEG, PNG ou WebP. Há validação de assinatura do arquivo, além do MIME informado.
- A imagem é lida em memória e não é persistida pela aplicação. Ao selecionar OpenAI, a imagem e pergunta são enviadas ao provedor. Revise retenção, controles de dados, localização, termos e consentimento do provedor antes de uso com informações pessoais/sensíveis.
- Não registramos prompt, imagem, chave ou corpo de erro do provedor. Use HTTPS, restrinja acesso e configure limites de gastos/concorrência em produção.
- Uma imagem até o limite de upload ainda pode consumir tokens de imagem; `detail=auto` ajuda o serviço a processá-la, não garante custo fixo.
- Não há autenticação, rate limiting, antivírus nem garantia de precisão no MVP. Não o exponha publicamente sem essas salvaguardas.

## Fontes oficiais consultadas (2026-11-13)

- OpenAI, preços da API: https://developers.openai.com/api/docs/pricing/
- OpenAI, modelo GPT-4o mini e preços/capacidades: https://developers.openai.com/api/docs/models/gpt-4o-mini
- OpenAI, guia oficial de imagens e visão: https://developers.openai.com/api/docs/guides/images-vision
- OpenAI, API Responses: https://developers.openai.com/api/docs/guides/text?api-mode=responses
- Ollama, biblioteca Llama 3.2 Vision (tamanhos e downloads): https://ollama.com/library/llama3.2-vision
- Meta, licença e termos Llama 3.2: https://www.llama.com/llama3_2/license/
- Ollama, documentação da API: https://github.com/ollama/ollama/blob/main/docs/api.md
- Ollama, instalação: https://ollama.com/download
- FastAPI, upload de arquivos: https://fastapi.tiangolo.com/tutorial/request-files/

Preços, disponibilidade, políticas, modelos e termos mudam. Os valores listados são referência oficial consultada na data acima e não incluem necessariamente custo de visão/imagem, impostos, hospedagem ou câmbio. Confirme na página de preços antes de tomar decisão.

## Estrutura

```text
lunai/
├── README.md
├── .env.example
├── requirements.txt
├── tests/
└── src/
    ├── main.py
    └── static/index.html
```

## Avaliação manual de qualidade

Use `tests/evaluation_cases.json` como roteiro, substituindo os nomes ilustrativos por imagens locais. Não coloque imagens privadas no repositório. Comece com 5–10 imagens não sensíveis e confira cada resposta contra a imagem, marcando os critérios esperados como passou/falhou. Registre apenas o caso, o critério e uma nota; evite armazenar imagem, resposta com dados pessoais ou credenciais. Repita as mesmas perguntas após mudanças e compare qualidade, latência e custo aproximado no painel do provedor.

Avalie especialmente: identificação dos elementos principais, contagem, leitura de texto, distinção entre observação e inferência, e capacidade de admitir incerteza. A saída do modelo não é prova: confirme fatos importantes por outra fonte. A avaliação é manual; o conjunto de exemplos não executa chamadas ao modelo nem envia dados.
