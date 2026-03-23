# Inpo Web UI

Web frontend for the Inpo PDF imposition & prepress tools.

## Architecture

- **Frontend**: Static HTML/CSS/JS served by nginx or Apache
- **Backend**: Flask API that runs the Python pipeline scripts
- **Preview**: pdf.js renders PDFs directly in the browser

## Setup

### 1. Install Python dependencies

```bash
cd inpo-ui/backend
pip install -r requirements.txt
```

### 2. Start the Flask backend

```bash
cd inpo-ui/backend
python server.py
```

The API runs on `http://127.0.0.1:5000`.

### 3. Configure nginx

Copy or symlink the config:

```bash
# nginx
sudo ln -s /Users/leom1/Projects/Inpo/inpo-ui/nginx.conf /etc/nginx/sites-enabled/inpo
sudo nginx -s reload
```

Or for Apache, create a virtual host:

```apache
<VirtualHost *:80>
    ServerName inpo.local
    DocumentRoot /Users/leom1/Projects/Inpo/inpo-ui/frontend

    <Directory /Users/leom1/Projects/Inpo/inpo-ui/frontend>
        AllowOverride None
        Require all granted
    </Directory>

    ProxyPreserveHost On
    ProxyPass /api/ http://127.0.0.1:5000/api/
    ProxyPassReverse /api/ http://127.0.0.1:5000/api/
</VirtualHost>
```

### 4. Add host entry (optional)

```bash
echo "127.0.0.1 inpo.local" | sudo tee -a /etc/hosts
```

### 5. Open in browser

```
http://inpo.local
```

## Quick Start (development, no nginx)

For development, you can run Flask with static file serving:

```bash
cd inpo-ui/backend
FLASK_STATIC=1 python server.py
```

Then open `http://127.0.0.1:5000` — but for production, use nginx/Apache.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/presets` | List available sheet size presets |
| POST | `/api/upload` | Upload PDF (multipart form, field: `file`) |
| POST | `/api/process` | Run pipeline (JSON body) |
| GET | `/api/jobs/<id>/input.pdf` | Download original PDF |
| GET | `/api/jobs/<id>/result.pdf` | Download imposed PDF |
| GET | `/api/jobs/<id>/info` | Get PDF info JSON |
| DELETE | `/api/jobs/<id>` | Clean up job files |

### POST /api/process body

```json
{
    "job_id": "uuid",
    "remove_marks": true,
    "crop_to_bleed": true,
    "convert_to_cmyk": true,
    "cmyk_intent": 1,
    "sheet": "sra3",
    "orientation": null,
    "margin": 0.375,
    "outline": false,
    "marks": true
}
```
