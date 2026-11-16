# Deploying to PythonAnywhere

This guide targets `https://medicarehelper.pythonanywhere.com` and Python 3.12.
The app uses SQLite, uploaded documents, a ChromaDB index, and an embedding-model
cache, so the project must stay on persistent disk.

## 1. Upload the project and create a virtual environment

Open a PythonAnywhere Bash console:

```bash
cd /home/medicarehelper
# Clone the repository here, or upload it so this directory exists:
cd /home/medicarehelper/2340-Project-3

python3.12 -m venv /home/medicarehelper/.virtualenvs/medicare-helper
source /home/medicarehelper/.virtualenvs/medicare-helper/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps "chromadb==1.5.*"
```

ChromaDB is installed without its server-only dependencies to stay within
PythonAnywhere's disk quota. The embedded-client dependencies are listed
explicitly in `requirements.txt`.

## 2. Configure production environment variables

```bash
cp .env.production.example .env
chmod 600 .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Edit `.env` and replace every `CHANGE_ME` value:

- `SECRET_KEY`: use the generated random value.
- `LLM_API_KEY`: use the provider key.
- `HF_TOKEN`: use a read-only Hugging Face access token.

Do not commit `.env`. Keep `DEBUG=False`. The supplied hostname, trusted origin,
HTTPS settings, and persistent paths are already configured for
`medicarehelper.pythonanywhere.com`. The production example silences only the
HSTS subdomain/preload warnings: those options are intentionally unsafe for an
app that does not control the shared `pythonanywhere.com` parent domain.

## 3. Prepare persistent application data

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

Create a developer account without granting superuser access:

```bash
python manage.py shell
```

```python
from django.contrib.auth import get_user_model

User = get_user_model()
developer = User.objects.create_user(username="YOUR_USERNAME")
developer.set_password("YOUR_PASSWORD")
developer.is_staff = True
developer.save()
exit()
```

Build the initial RAG index:

```bash
python manage.py ingest --reset
```

Production uses Hugging Face's hosted embedding API, so it does not download the
67 MB local model. Rebuild the whole index whenever `EMBED_PROVIDER` or
`EMBED_MODEL` changes; vectors from different models must not be mixed.
PythonAnywhere free accounts restrict outbound requests to allowlisted sites. If
a source cannot be downloaded, upload its PDF/TXT file through the developer UI
or place it in `data/docs/`, then ingest it again. Run large initial ingests from
a Bash console so a web-request timeout cannot interrupt them.

For local, offline embeddings instead, install
`requirements-local-embeddings.txt` and set `EMBED_PROVIDER=local`.

## 4. Configure the PythonAnywhere web app

On the **Web** tab:

1. Create a manual-configuration web app using Python 3.12.
2. Set **Source code** to `/home/medicarehelper/2340-Project-3`.
3. Set **Virtualenv** to `/home/medicarehelper/.virtualenvs/medicare-helper`.
4. Replace the WSGI configuration with:

```python
import os
import sys

project_home = "/home/medicarehelper/2340-Project-3"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application
```

5. Add this static-files mapping:
   - URL: `/static/`
   - Directory: `/home/medicarehelper/2340-Project-3/staticfiles`
6. Reload the web app.

## 5. Run readiness checks

With the production virtual environment active:

```bash
python manage.py deployment_check
python manage.py test chat
```

`deployment_check` fails if Django security checks, required packages, the API
key, writable persistent paths, collected static files, the RAG index, source
manifest, database, or developer account are not ready.

Then verify:

- `https://medicarehelper.pythonanywhere.com/` loads with styling.
- `/developer/login/` accepts the developer account.
- `/sources/` returns 403 when signed out.
- A known question returns a grounded answer with at least one citation.
- Developer logout removes access to source management.

After confirming HTTPS works reliably, increase `SECURE_HSTS_SECONDS` gradually
from the initial one-hour value. Do not enable HSTS preload until the domain and
all subdomains are permanently HTTPS-only.

## Updating the deployment

After each code update:

```bash
cd /home/medicarehelper/2340-Project-3
source /home/medicarehelper/.virtualenvs/medicare-helper/bin/activate
git pull
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py deployment_check
```

Reload the app from the PythonAnywhere **Web** tab. Re-run ingestion only when
source files, source metadata, the embedding model, or chunking behavior change.
