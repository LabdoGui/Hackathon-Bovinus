# Site online (GitHub Pages)

Endereço: **https://labdogui.github.io/Hackathon-Bovinus/**

## O que é publicado

O GitHub Pages só hospeda arquivos estáticos (HTML, CSS, JavaScript e imagens). Ele **não roda
Python**, não acessa balança nem banco de dados. Por isso o site tem duas partes:

| Endereço | Conteúdo |
|----------|----------|
| `/` (`docs/index.html`) | Página de apresentação: problema, fluxo, perfis, tecnologia e o vídeo de 2 minutos |
| `/app/` (`docs/app/`) | **Demonstração**: as mesmas páginas do sistema (Início, Balcão, Câmera, Painel, Revisão) |

Na demonstração, as páginas usam uma **API simulada que roda no navegador** (`site/demo.js`) no
lugar do servidor:

* **balança e reconhecimento simulados** (o reconhecimento, como no modo `mock`, não analisa a imagem);
* **câmera simulada** por padrão; o visitante pode clicar em *Usar minha webcam* (o navegador pede
  permissão) e a foto fica só no navegador dele;
* catálogo **fictício** gerado a partir do `seed` (fichas técnicas "(demo)"), com custo por kg
  calculado pelo próprio sistema;
* cálculos com as mesmas regras do motor em Python (pesos em 0,1 g, dinheiro em centavos,
  arredondamento "meio para cima", distribuição pelo maior resto);
* dados guardados **apenas no `localStorage` do navegador do visitante**; o botão
  *Recomeçar a demonstração* apaga tudo. Nada é enviado para servidor algum.

Uma faixa no topo de todas as páginas da demonstração avisa isso ao visitante.

## Ativar o link (uma vez)

1. No GitHub, abra o repositório → **Settings** → **Pages**.
2. Em **Build and deployment → Source**, escolha **Deploy from a branch**.
3. Em **Branch**, escolha `claude/magical-fermat-438tis` e a pasta **`/docs`** → **Save**.
4. Aguarde 1 a 2 minutos (a aba **Actions** mostra o andamento de "pages build and deployment").
5. Abra **https://labdogui.github.io/Hackathon-Bovinus/**.

Se o código for para a branch `main` no futuro, troque a branch no passo 3.

## Atualizar o site depois de mudar as páginas

As páginas da demonstração são geradas a partir de `app/templates` e `app/static`, então o visual
é sempre o mesmo do sistema instalado:

```bash
python scripts/build_site.py
git add docs
git commit -m "Atualiza site"
git push
```

O teste `tests/test_site_build.py::test_published_docs_are_up_to_date` falha se `docs/` ficar
desatualizado em relação às páginas.

O script só reescreve o que ele gera (`docs/index.html`, `docs/.nojekyll`, `docs/app/`,
`docs/assets/`). A documentação em Markdown e o vídeo (`docs/media/`) não são tocados.

## Arquivos

| Arquivo | Papel |
|---------|-------|
| `scripts/build_site.py` | Gera o site: roda o seed num banco temporário, exporta o catálogo e renderiza as páginas |
| `site/demo.js` | API simulada no navegador (balança, câmera, reconhecimento, transações, revisão, relatórios, CSV) |
| `site/landing.html`, `site/assets/landing.css` | Página de apresentação |
| `docs/media/` | Vídeo de apresentação e capa |

## Segurança

As páginas publicadas têm Content-Security-Policy (`script-src 'self'`, sem scripts inline), não
carregam nada de fora do próprio site e não contêm chaves nem dados reais. O `.nojekyll` faz o
GitHub servir os arquivos como estão.
