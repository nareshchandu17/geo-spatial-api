# Publishing this repository to GitHub

The environment in which this project was built does **not** have the
GitHub CLI (`gh`) installed and has no GitHub credentials configured, so
the repository could not be pushed automatically.

This document gives you the exact steps to publish it yourself.

---

## Option A: Using the GitHub web UI + a local clone (recommended for first-time setup)

1. **Create a new empty repository on GitHub.**
   * Go to https://github.com/new
   * Repository name: `geospatial-file-measurement-api`
   * Description: `FastAPI service that measures polygon areas and LineString lengths from uploaded Shapefile (.zip) and KML files.`
   * Visibility: **Public**
   * Do **NOT** initialize with a README / .gitignore / license -- the
     project already has all three.
   * Click **Create repository**.

2. **Extract the ZIP archive** you received alongside this project:

   ```bash
   unzip geospatial-file-measurement-api.zip
   cd geospatial-file-measurement-api
   ```

   The archive was produced via `git archive` so it contains exactly
   the same files that were committed locally -- nothing else.

3. **Initialise a fresh git repo and commit:**

   ```bash
   git init -b main
   git add -A
   git commit -m "Initial commit: Geospatial File Measurement API"
   ```

4. **Point it at GitHub and push:**

   ```bash
   git remote add origin https://github.com/<your-account>/geospatial-file-measurement-api.git
   git branch -M main
   git push -u origin main
   ```

   (Replace `<your-account>` with your GitHub username.  GitHub will
   prompt you for a personal access token the first time -- your password
   alone is no longer accepted for HTTPS git pushes.)

5. **Verify** the repository is public:

   ```
   https://github.com/<your-account>/geospatial-file-measurement-api
   ```

---

## Option B: Using the GitHub CLI (`gh`)

If you already have `gh` installed and authenticated locally:

```bash
cd geospatial-file-measurement-api
gh repo create geospatial-file-measurement-api \
    --public \
    --source=. \
    --remote=origin \
    --push \
    --description "FastAPI service that measures polygon areas and LineString lengths from uploaded Shapefile (.zip) and KML files."
```

`gh` will refuse to overwrite an existing repo with the same name, so
this is safe even if you've already created the repo by mistake.

---

## Verifying the publish worked

Whichever option you used, the published repository should contain these
26 files:

```
.env.example
.gitignore
Dockerfile
README.md
api/__init__.py
api/routes.py
config.py
data/.gitkeep
database.py
main.py
requirements.txt
schemas.py
scripts/smoke_demo.py
services/__init__.py
services/crs.py
services/errors.py
services/measurements.py
services/processor.py
services/readers.py
services/validation.py
tests/__init__.py
tests/conftest.py
tests/helpers.py
tests/test_health.py
tests/test_measurements.py
tests/test_upload.py
```

And the test suite must pass:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Expected: `33 passed`.

---

## What NOT to commit

The `.gitignore` already excludes:

* `data/` runtime directory contents (the SQLite database, the
  temporary uploads) -- only `data/.gitkeep` is committed so the
  directory exists on a fresh clone.
* `.env`, `.env.local`, `*.pem`, `*.key` -- secrets and env files.
* `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.coverage` -- Python and
  pytest build artefacts.
* `.venv/` -- the virtual environment.

If you forked or copied the project and want to double-check before
pushing, run:

```bash
git status --ignored
```

and confirm `data/geospatial.db` (or similar) does NOT appear in the
"untracked" or "to-be-committed" lists.
