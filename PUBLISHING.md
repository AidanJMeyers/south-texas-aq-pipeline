# Publishing the Documentation Site

Short guide for getting `pipeline/docs/` published as a browsable,
searchable website at `https://aidanjmeyers.github.io/south-texas-aq-pipeline/`.

## What's already in place

- **`mkdocs.yml`** — site config using the Material for MkDocs theme.
  Points `docs_dir` at `pipeline/docs/` so the existing markdown is used
  as-is with zero rewriting.
- **`requirements-docs.txt`** — Python deps for building the site.
- **`.github/workflows/docs.yml`** — GitHub Actions workflow that builds
  and deploys the site automatically on every push to `main`.
- **`pipeline/docs/index.md`** — landing page with a visual quickstart
  and navigation cards.
- **`pipeline/docs/15_recipes.md`** — 10 copy-paste recipes for common
  research tasks.

## Local preview (before publishing)

```powershell
pip install -r requirements-docs.txt
python -m mkdocs serve
```

Open `http://127.0.0.1:8000` in a browser. Every edit to
`pipeline/docs/*.md` auto-reloads.

## Publishing to GitHub Pages

### Step 1 — Create a GitHub repository

On https://github.com/new, create a new repository. Suggested:

- **Name:** `south-texas-aq-pipeline` (or any name you like)
- **Visibility:** Public if you want the site publicly accessible; Private if
  you only want read access for the lab. (GitHub Pages works for both
  with a free GitHub plan, but the URL path differs for private repos.)
- **Do NOT initialize** with a README, license, or gitignore — the local
  repo already has those.

### Step 2 — Push to GitHub

```powershell
cd "C:\Users\aidan\OneDrive\Desktop\AirQuality South TX"
git remote add origin https://github.com/AidanJMeyers/south-texas-aq-pipeline.git
git branch -M main
git push -u origin main
```

### Step 3 — Enable GitHub Pages

1. Go to https://github.com/AidanJMeyers/south-texas-aq-pipeline
2. Click **Settings** (top right)
3. In the left sidebar, click **Pages**
4. Under **Source**, select **GitHub Actions** (NOT "Deploy from a branch")
5. Save

The first `push` to `main` will automatically kick off the docs workflow.
Watch progress under the **Actions** tab. The first build takes ~2–3
minutes (it installs Python, pip-installs the docs deps, then builds
and deploys).

### Step 4 — Visit your site

Once the workflow finishes successfully, your site will be live at:

**https://aidanjmeyers.github.io/south-texas-aq-pipeline/**

The first load may take a few seconds as GitHub Pages propagates.

## What the site looks like

- **Material theme** — clean, modern, fast
- **Left sidebar** — numbered document navigation
- **Right TOC** — per-page section navigation
- **Search bar** — full-text search across all docs
- **Dark mode toggle** — top right corner
- **Copy buttons** on every code block
- **Tabbed content** — Python/R/SQL snippets in tabs on the recipes page
- **Mermaid diagrams** — supported if you add them
- **Git revision timestamps** — "last updated X days ago" on every page
- **Edit links** — "Edit this page" button jumps to the markdown on GitHub

## Updating the docs

Just edit the markdown files under `pipeline/docs/`, commit, and push:

```powershell
git add pipeline/docs/
git commit -m "docs: update methodology section"
git push
```

GitHub Actions will automatically rebuild and redeploy within ~2 minutes.
No manual steps needed.

## Troubleshooting

**"Pages build failed" in Actions tab**
Click into the failed run. Usually caused by a broken markdown link after
a file was renamed or deleted. Run `mkdocs build --strict` locally to
reproduce.

**"404 — File not found" on the deployed site**
Either (a) the site hasn't finished deploying yet — wait 2 minutes and
retry, or (b) the link in the docs is broken — check with `mkdocs serve`
locally.

**Social / sharing cards look broken**
Material for MkDocs has a built-in social-card generator. To enable, add
to `mkdocs.yml`:

```yaml
plugins:
  - social  # requires `pip install "mkdocs-material[imaging]"`
```

**Private repo and collaborators can't see the site**
GitHub Pages on private repos requires every viewer to be a collaborator
on the repo. Either add them as collaborators (Settings → Collaborators)
or switch the repo to Public (Settings → General → Danger Zone).

## If you want a custom domain

E.g., `aq-pipeline.melaram.org` instead of `melaram-lab.github.io/...`:

1. Create a `CNAME` file at the repository root containing your domain
2. In your DNS provider, create a `CNAME` record pointing your domain to
   `<owner>.github.io`
3. In GitHub repo Settings → Pages → Custom domain, enter the domain
4. Check "Enforce HTTPS" once DNS propagates (~5 minutes)
